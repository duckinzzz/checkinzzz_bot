import asyncio
from datetime import date
from types import SimpleNamespace
from typing import Sequence

from services.sheets import MARK


class FakeWorksheet:
    """Минимальная подделка gspread.worksheet.Worksheet.

    Повторяет поведение Google Sheets: при valueInputOption=USER_ENTERED значение,
    начинающееся с «=», «+», «-» или «@», разбирается как формула и превращается в
    ошибку. Именно на этом ломается запись отметки «+» — проверено на живой таблице.
    """

    FORMULA_PREFIXES = ("=", "+", "-", "@")

    def __init__(self, rows: list[list[str]] | None = None) -> None:
        self.rows: list[list[str]] = [list(row) for row in (rows or [])]
        self.updates: list[tuple[int, int, str]] = []
        self.batch_updates: list[list[dict]] = []
        self.input_options: list[str] = []

    def _ensure_cell(self, row: int, column: int) -> None:
        while len(self.rows) < row:
            self.rows.append([])
        while len(self.rows[row - 1]) < column:
            self.rows[row - 1].append("")

    def get_all_values(self) -> list[list[str]]:
        width = max((len(row) for row in self.rows), default=0)
        return [list(row) + [""] * (width - len(row)) for row in self.rows]

    def col_values(self, column: int) -> list[str]:
        values = []
        for row in self.rows:
            values.append(row[column - 1] if len(row) >= column else "")
        return values

    def _store(
        self, row: int, column: int, value: str, value_input_option: str | None
    ) -> None:
        # gspread по умолчанию пишет RAW, поэтому «не задано» — это тоже RAW.
        option = value_input_option or "RAW"
        self.input_options.append(option)
        stored = value
        if option != "RAW" and str(value)[:1] in self.FORMULA_PREFIXES:
            stored = "#ERROR!"
        self._ensure_cell(row, column)
        self.rows[row - 1][column - 1] = stored
        self.updates.append((row, column, stored))

    def update(
        self, values: list[list[str]], range_name: str | None = None, **kwargs: object
    ) -> None:
        option = kwargs.get("value_input_option")
        start = _parse_a1_cell(range_name or "A1")
        for row_offset, record in enumerate(values):
            for column_offset, value in enumerate(record):
                self._store(
                    start[0] + row_offset,
                    start[1] + column_offset,
                    value,
                    option,  # type: ignore[arg-type]
                )

    def update_cell(self, row: int, column: int, value: str) -> None:
        # gspread жёстко зашивает в update_cell USER_ENTERED.
        self._store(row, column, value, "USER_ENTERED")

    def batch_update(self, data: list[dict], **kwargs: object) -> None:
        option = kwargs.get("value_input_option")
        self.batch_updates.append(data)
        for item in data:
            target = item["range"]
            if isinstance(target, str):
                row, column = _parse_a1_cell(target)
            else:
                row, column = target
            self._store(row, column, item["values"][0][0], option)  # type: ignore[arg-type]


def _parse_a1_cell(reference: str) -> tuple[int, int]:
    letters = "".join(char for char in reference if char.isalpha())
    digits = "".join(char for char in reference if char.isdigit())
    column = 0
    for char in letters.upper():
        column = column * 26 + (ord(char) - ord("A") + 1)
    return int(digits), column


class FakeSubjectSheet:
    """Реализация протокола SubjectSheet в памяти.

    Колонка A — ФИО, даты начинаются с колонки B.
    """

    def __init__(
        self,
        students: Sequence[str] = (),
        dates: Sequence[date] = (),
        cells: dict[tuple[int, int], str] | None = None,
    ) -> None:
        self.students = list(students)
        self.dates = list(dates)
        self.cells = dict(cells or {})
        self.written: list[tuple[int, int]] = []
        self.fail_next_writes = 0

    def student_rows(self) -> dict[str, int]:
        from utils.names import normalize_name

        return {normalize_name(name): row for row, name in enumerate(self.students, start=2)}

    def ensure_date_column(self, day: date) -> int:
        if day in self.dates:
            return self.dates.index(day) + 2
        self.dates.append(day)
        return len(self.dates) + 1

    def marked_rows(self, column: int) -> set[int]:
        return {
            row
            for (row, col), value in self.cells.items()
            if col == column and value.strip() == MARK
        }

    def write_marks(self, marks: Sequence[tuple[int, int]]) -> None:
        if self.fail_next_writes > 0:
            self.fail_next_writes -= 1
            from services.sheets import SheetTransientError

            raise SheetTransientError("429")
        self.written.extend(marks)
        for row, column in marks:
            self.cells[(row, column)] = MARK


class FakeBot:
    """Подделка aiogram.Bot: запоминает отправленные и отредактированные сообщения."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.edited: list[dict] = []
        self.fail_send = False

    async def send_message(self, chat_id: int, text: str, **kwargs: object):
        if self.fail_send:
            raise RuntimeError("telegram недоступен")
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})
        return SimpleNamespace(message_id=100 + len(self.sent))

    async def edit_message_text(self, text: str, chat_id: int, message_id: int, **kwargs: object):
        self.edited.append(
            {"chat_id": chat_id, "message_id": message_id, "text": text, "kwargs": kwargs}
        )
        return SimpleNamespace(message_id=message_id)


class ManualSleeper:
    """Замена asyncio.sleep для тестов: короткие паузы пропускает, длинную держит.

    flush_delay в тестах нулевой — он должен срабатывать сразу. Пауза до конца
    пары измеряется часами; её держим до явного release(), иначе таймер закрытия
    сработает посреди теста и пара исчезнет из-под проверок.
    """

    def __init__(self, threshold: float = 1.0) -> None:
        self.threshold = threshold
        self.delays: list[float] = []
        self._released = asyncio.Event()

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        if delay <= self.threshold:
            await asyncio.sleep(0)
            return
        await self._released.wait()

    def release(self) -> None:
        self._released.set()
