from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from services.schedule import current_pair
from services.session import CheckinSession, StartResult, format_pair_message
from services.state import StateStore
from services.students import StudentDirectory
from services.subjects import Subjects
from tests.fakes import FakeBot, FakeSubjectSheet, ManualSleeper

MSK = ZoneInfo("Europe/Moscow")
ENDS = [time(10, 5), time(11, 40), time(13, 15)]
STUDENTS = ["Иванов Иван", "Петров Пётр"]


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


def build(
    tmp_path: Path,
    *,
    now: datetime = datetime(2026, 10, 7, 12, 30, tzinfo=MSK),
    sheet: FakeSubjectSheet | None = None,
    sleeper: ManualSleeper | None = None,
) -> tuple[CheckinSession, FakeBot, FakeSubjectSheet, StateStore]:
    bot = FakeBot()
    active_sheet = sheet or FakeSubjectSheet(students=STUDENTS)
    store = StateStore(tmp_path / "state.json")
    session = CheckinSession(
        bot=bot,  # type: ignore[arg-type]
        chat_id=-100,
        pair_end_times=tuple(ENDS),
        directory=StudentDirectory({111: "Иванов Иван", 222: "Петров Пётр"}),
        subjects=Subjects({"Матан": "Матан"}),
        open_sheet=lambda worksheet: active_sheet,
        store=store,
        clock=Clock(now),
        flush_delay=0,
        retry_base_delay=0,
        sleep=sleeper or ManualSleeper(),
    )
    return session, bot, active_sheet, store


def test_format_pair_message():
    pair = current_pair(datetime(2026, 10, 7, 12, 30, tzinfo=MSK), ENDS)
    assert pair is not None
    text = format_pair_message("Матан", pair)
    assert "Матан" in text
    assert "3 пара" in text
    assert "13:15" in text


async def test_start_posts_message_with_button(tmp_path: Path):
    session, bot, sheet, store = build(tmp_path)
    assert await session.start("Матан") is StartResult.STARTED
    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == -100
    markup = bot.sent[0]["kwargs"]["reply_markup"]
    assert markup.inline_keyboard[0][0].text == "Отметиться"
    assert store.load() is not None


async def test_start_creates_today_column(tmp_path: Path):
    session, _, sheet, _ = build(tmp_path)
    await session.start("Матан")
    assert sheet.dates == [date(2026, 10, 7)]


async def test_start_unknown_subject(tmp_path: Path):
    session, bot, _, store = build(tmp_path)
    assert await session.start("Философия") is StartResult.UNKNOWN_SUBJECT
    assert bot.sent == []
    assert store.load() is None


async def test_start_after_last_pair(tmp_path: Path):
    session, bot, _, _ = build(tmp_path, now=datetime(2026, 10, 7, 15, 0, tzinfo=MSK))
    assert await session.start("Матан") is StartResult.DAY_OVER
    assert bot.sent == []


async def test_start_exactly_at_end_time_is_day_over(tmp_path: Path):
    session, bot, _, _ = build(tmp_path, now=datetime(2026, 10, 7, 13, 15, tzinfo=MSK))
    assert await session.start("Матан") is StartResult.DAY_OVER
    assert bot.sent == []


def _broken_sheet() -> FakeSubjectSheet:
    from services.sheets import SheetError

    sheet = FakeSubjectSheet(students=STUDENTS)

    def boom(day: date) -> int:
        raise SheetError("нет вкладки")

    sheet.ensure_date_column = boom  # type: ignore[method-assign]
    return sheet


async def test_start_reports_sheet_error(tmp_path: Path):
    session, bot, _, store = build(tmp_path)
    session._open_sheet = lambda worksheet: _broken_sheet()
    assert await session.start("Матан") is StartResult.SHEET_ERROR
    assert bot.sent == []
    assert store.load() is None


async def test_close_edits_message_and_clears_state(tmp_path: Path):
    session, bot, _, store = build(tmp_path)
    await session.start("Матан")
    await session.close()
    assert bot.edited[-1]["text"].startswith("Матан — пара закрыта")
    assert store.load() is None
    assert session.close_task is None


async def test_close_without_active_session_is_noop(tmp_path: Path):
    session, bot, _, _ = build(tmp_path)
    await session.close()
    assert bot.edited == []


async def test_close_survives_edit_failure(tmp_path: Path):
    session, bot, _, store = build(tmp_path)
    await session.start("Матан")

    async def boom(**kwargs: object) -> None:
        raise RuntimeError("message is not modified")

    bot.edit_message_text = boom  # type: ignore[method-assign]
    await session.close()
    assert store.load() is None


async def test_starting_new_pair_closes_previous(tmp_path: Path):
    session, bot, _, _ = build(tmp_path)
    await session.start("Матан")
    await session.start("Матан")
    assert len(bot.sent) == 2
    assert len(bot.edited) == 1
    assert bot.edited[0]["message_id"] == 101


async def test_close_task_armed(tmp_path: Path):
    session, _, _, _ = build(tmp_path)
    await session.start("Матан")
    assert session.close_task is not None
    await session.close()


async def test_close_timer_closes_pair(tmp_path: Path):
    sleeper = ManualSleeper()
    session, bot, _, store = build(tmp_path, sleeper=sleeper)
    await session.start("Матан")
    assert store.load() is not None

    sleeper.release()
    await session.close_task

    assert store.load() is None
    assert bot.edited[-1]["text"].startswith("Матан — пара закрыта")
