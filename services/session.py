from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import Awaitable, Callable, Sequence
from uuid import uuid4

from aiogram import Bot

from core.log import logger
from keyboards import checkin_kb
from services.schedule import CurrentPair, current_pair
from services.sheets import SheetError, SheetTransientError, SubjectSheet
from services.state import StateStore, StoredSession
from services.students import StudentDirectory
from services.subjects import Subjects
from utils.names import normalize_name
from utils.retry import call_with_retry


class StartResult(Enum):
    STARTED = "started"
    DAY_OVER = "day_over"
    UNKNOWN_SUBJECT = "unknown_subject"
    SHEET_ERROR = "sheet_error"


class CheckinResult(Enum):
    MARKED = "marked"
    ALREADY = "already"
    NO_SESSION = "no_session"
    NOT_IN_GROUP = "not_in_group"
    NOT_IN_SHEET = "not_in_sheet"


def format_pair_message(subject: str, pair: CurrentPair) -> str:
    return (
        f"📚 Сейчас идёт: {subject} ({pair.number} пара, до {pair.end_at:%H:%M})\n"
        "Отметься, если присутствуешь."
    )


def _closed_message(active: "_Active") -> str:
    total = len(active.rows)
    marked = len(set(active.marked_rows.values()) | active.sheet_marked_rows)
    return f"{active.subject} — пара закрыта, отметились {marked} из {total}"


@dataclass
class _Active:
    token: str
    subject: str
    worksheet: str
    sheet: SubjectSheet
    day: date
    pair_number: int
    end_at: datetime
    message_id: int
    column: int
    rows: dict[str, int]
    sheet_marked_rows: set[int]
    marked_rows: dict[int, int] = field(default_factory=dict)
    pending: list[tuple[int, int]] = field(default_factory=list)

    def to_stored(self) -> StoredSession:
        return StoredSession(
            token=self.token,
            subject=self.subject,
            worksheet=self.worksheet,
            message_id=self.message_id,
            day=self.day,
            pair_number=self.pair_number,
            end_at=self.end_at,
            marked_rows=dict(self.marked_rows),
            pending=tuple(self.pending),
        )


class CheckinSession:
    """Активная пара: сообщение в беседе, буфер отметок, таймеры."""

    def __init__(
        self,
        *,
        bot: Bot,
        chat_id: int,
        pair_end_times: Sequence[time],
        directory: StudentDirectory,
        subjects: Subjects,
        open_sheet: Callable[[str], SubjectSheet],
        store: StateStore,
        clock: Callable[[], datetime],
        report: Callable[[str], Awaitable[None]] | None = None,
        flush_delay: float = 2.0,
        flush_size: int = 20,
        retry_base_delay: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._pair_end_times = tuple(pair_end_times)
        self._directory = directory
        self._subjects = subjects
        self._open_sheet = open_sheet
        self._store = store
        self._clock = clock
        self._report_hook = report
        self._flush_delay = flush_delay
        self._flush_size = flush_size
        self._retry_base_delay = retry_base_delay
        self._sleep = sleep
        self._active: _Active | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def chat_id(self) -> int:
        return self._chat_id

    @property
    def close_task(self) -> asyncio.Task[None] | None:
        return self._close_task

    @property
    def active_subject(self) -> str | None:
        return self._active.subject if self._active else None

    @property
    def marked_count(self) -> int:
        if self._active is None:
            return 0
        return len(set(self._active.marked_rows.values()) | self._active.sheet_marked_rows)

    async def start(self, subject_title: str) -> StartResult:
        worksheet = self._subjects.worksheet_of(subject_title)
        if worksheet is None:
            logger.warning("Неизвестный предмет: %r", subject_title)
            return StartResult.UNKNOWN_SUBJECT

        pair = current_pair(self._clock(), self._pair_end_times)
        if pair is None:
            return StartResult.DAY_OVER

        async with self._lock:
            previous = self._detach_active()
            if previous is not None:
                await self._finish(previous)

            try:
                sheet = self._open_sheet(worksheet)
                column = await asyncio.to_thread(sheet.ensure_date_column, pair.end_at.date())
                rows = await asyncio.to_thread(sheet.student_rows)
                already = await asyncio.to_thread(sheet.marked_rows, column)
            except SheetError as exc:
                logger.exception("Не удалось подготовить вкладку %r", worksheet)
                await self._report(f"⚠️ Не смог открыть вкладку «{worksheet}»: {exc}")
                return StartResult.SHEET_ERROR

            token = uuid4().hex[:12]
            message = await self._bot.send_message(
                self._chat_id,
                format_pair_message(subject_title, pair),
                reply_markup=checkin_kb(token),
            )

            self._active = _Active(
                token=token,
                subject=subject_title,
                worksheet=worksheet,
                sheet=sheet,
                day=pair.end_at.date(),
                pair_number=pair.number,
                end_at=pair.end_at,
                message_id=message.message_id,
                column=column,
                rows=rows,
                sheet_marked_rows=already,
            )
            self._store.save(self._active.to_stored())
            self._arm_close(pair.end_at)

        logger.info(
            "Пара %s (%s, до %s) открыта, студентов в листе: %d",
            subject_title,
            pair.number,
            pair.end_at,
            len(rows),
        )
        return StartResult.STARTED

    async def close(self) -> None:
        async with self._lock:
            active = self._detach_active()
            if active is None:
                return
            await self._finish(active)
        logger.info("Пара %s закрыта", active.subject)

    def _detach_active(self) -> "_Active | None":
        """Снять активную пару и погасить её таймеры. Вызывать под self._lock."""
        active = self._active
        if active is None:
            return None
        self._active = None

        self._cancel_flush()
        task = self._close_task
        self._close_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        return active

    async def _finish(self, active: _Active) -> None:
        """Дописать буфер, объявить итог в беседе, отчитаться админу. Вызывать под self._lock."""
        await self._flush(active)
        await self._announce_closed(active)
        await self._report_summary(active)
        self._store.clear()

    async def restore(self) -> None:
        stored = self._store.load()
        if stored is None:
            return

        try:
            sheet = self._open_sheet(stored.worksheet)
            column = await asyncio.to_thread(sheet.ensure_date_column, stored.day)
            rows = await asyncio.to_thread(sheet.student_rows)
            already = await asyncio.to_thread(sheet.marked_rows, column)
        except SheetError as exc:
            logger.exception("Не удалось восстановить пару %r", stored.subject)
            await self._report(f"⚠️ Не смог восстановить пару «{stored.subject}»: {exc}")
            self._store.clear()
            return

        self._active = _Active(
            token=stored.token,
            subject=stored.subject,
            worksheet=stored.worksheet,
            sheet=sheet,
            day=stored.day,
            pair_number=stored.pair_number,
            end_at=stored.end_at,
            message_id=stored.message_id,
            column=column,
            rows=rows,
            sheet_marked_rows=already,
            marked_rows=dict(stored.marked_rows),
            pending=list(stored.pending),
        )
        logger.info("Восстановил пару %s до %s", stored.subject, stored.end_at)

        if stored.end_at <= self._clock():
            await self.close()
        else:
            self._arm_close(stored.end_at)

    def _arm_close(self, end_at: datetime) -> None:
        self._close_task = asyncio.create_task(self._close_at(end_at))

    async def _close_at(self, end_at: datetime) -> None:
        delay = max((end_at - self._clock()).total_seconds(), 0.0)
        await self._sleep(delay)
        await self.close()

    async def flush_now(self) -> None:
        async with self._lock:
            active = self._active
            if active is None:
                return
            self._cancel_flush()
            await self._flush(active)

    async def handle_checkin(self, tg_id: int, token: str) -> CheckinResult:
        async with self._lock:
            active = self._active
            if active is None or active.token != token or self._clock() >= active.end_at:
                return CheckinResult.NO_SESSION

            name = self._directory.name_of(tg_id)
            if name is None:
                return CheckinResult.NOT_IN_GROUP

            row = active.rows.get(normalize_name(name))
            if row is None:
                logger.warning(
                    "Студент %s (id %s) не найден в листе %r", name, tg_id, active.worksheet
                )
                await self._report(
                    f"⚠️ {name} (id {tg_id}) жмёт «Отметиться», но его нет в листе "
                    f"«{active.worksheet}». Отметка не поставлена."
                )
                return CheckinResult.NOT_IN_SHEET

            already = row in active.sheet_marked_rows or row in set(active.marked_rows.values())
            if already:
                return CheckinResult.ALREADY

            active.marked_rows[tg_id] = row
            active.pending.append((row, active.column))
            self._store.save(active.to_stored())

            if len(active.pending) >= self._flush_size:
                self._cancel_flush()
                await self._flush(active)
            else:
                self._schedule_flush()

            return CheckinResult.MARKED

    async def _announce_closed(self, active: _Active) -> None:
        try:
            await self._bot.edit_message_text(
                _closed_message(active),
                chat_id=self._chat_id,
                message_id=active.message_id,
            )
        except Exception:
            logger.exception(
                "Не удалось отредактировать сообщение о закрытии пары %s", active.subject
            )

    async def _report(self, text: str) -> None:
        """Сообщение админам в ЛС; вызывается только из хендлеров сессии."""
        if self._report_hook is None:
            logger.info("Отчёт админам: %s", text)
            return
        await self._report_hook(text)

    async def _report_summary(self, active: _Active) -> None:
        marked_rows = set(active.marked_rows.values()) | active.sheet_marked_rows
        present = [
            name
            for name in self._directory.all_names()
            if (row := active.rows.get(normalize_name(name))) is not None and row in marked_rows
        ]
        missing = [
            name
            for name in self._directory.all_names()
            if (row := active.rows.get(normalize_name(name))) is not None and row not in marked_rows
        ]
        lines = [
            f"📊 {active.subject} ({active.pair_number} пара), {active.day:%d.%m.%Y}",
            f"Отметились {len(present)} из {len(present) + len(missing)}",
        ]
        lines += [f"• {name}" for name in present]
        if missing:
            lines.append("Не отметились:")
            lines += [f"• {name}" for name in missing]
        await self._report("\n".join(lines))

    async def _flush(self, active: _Active) -> None:
        if not active.pending:
            return
        batch = active.pending
        active.pending = []
        try:
            await call_with_retry(
                active.sheet.write_marks,
                batch,
                retry_on=(SheetTransientError,),
                base_delay=self._retry_base_delay,
            )
        except SheetError as exc:
            logger.exception("Не удалось записать отметки (%s)", active.subject)
            active.pending = batch + active.pending
            await self._report(f"⚠️ Отметки по «{active.subject}» не записались: {exc}")

    def _cancel_flush(self) -> None:
        if self._flush_task is not None:
            self._flush_task.cancel()
            self._flush_task = None

    def _schedule_flush(self) -> None:
        self._cancel_flush()
        self._flush_task = asyncio.create_task(self._flush_later())

    async def _flush_later(self) -> None:
        # Только под локом: иначе таймер и handle_checkin полезут в pending разом.
        current = asyncio.current_task()
        try:
            await self._sleep(self._flush_delay)
            async with self._lock:
                active = self._active
                if active is not None:
                    await self._flush(active)
        finally:
            if self._flush_task is current:
                self._flush_task = None
