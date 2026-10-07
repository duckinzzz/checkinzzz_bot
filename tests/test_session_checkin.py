import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from services.session import CheckinResult
from tests.fakes import FakeSubjectSheet
from tests.test_session_start import ENDS, MSK, build

IVAN = 111
PETR = 222
STRANGER = 999

NOW = datetime(2026, 10, 7, 12, 30, tzinfo=MSK)


async def _started(tmp_path: Path, sheet: FakeSubjectSheet | None = None):
    session, bot, active_sheet, store = build(tmp_path, now=NOW, sheet=sheet)
    await session.start("Матан")
    token = session._active.token
    return session, bot, active_sheet, store, token


async def test_marks_and_writes_to_sheet(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path)
    assert await session.handle_checkin(IVAN, token) is CheckinResult.MARKED
    await session.flush_now()
    assert sheet.written == [(2, 2)]


async def test_second_press_is_idempotent(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path)
    await session.handle_checkin(IVAN, token)
    assert await session.handle_checkin(IVAN, token) is CheckinResult.ALREADY
    await session.flush_now()
    assert sheet.written == [(2, 2)]


async def test_mark_already_present_in_sheet(tmp_path: Path):
    sheet = FakeSubjectSheet(students=["Иванов Иван", "Петров Пётр"], cells={(2, 2): "+"})
    session, _, _, _, token = await _started(tmp_path, sheet=sheet)
    assert await session.handle_checkin(IVAN, token) is CheckinResult.ALREADY


async def test_unknown_student(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path)
    assert await session.handle_checkin(STRANGER, token) is CheckinResult.NOT_IN_GROUP
    await session.flush_now()
    assert sheet.written == []


async def test_student_missing_from_sheet(tmp_path: Path):
    sheet = FakeSubjectSheet(students=["Петров Пётр"])
    session, _, _, _, token = await _started(tmp_path, sheet=sheet)
    assert await session.handle_checkin(IVAN, token) is CheckinResult.NOT_IN_SHEET
    await session.flush_now()
    assert sheet.written == []


async def test_wrong_token(tmp_path: Path):
    session, _, _, _, _ = await _started(tmp_path)
    assert await session.handle_checkin(IVAN, "чужой") is CheckinResult.NO_SESSION


async def test_without_active_pair(tmp_path: Path):
    session, _, _, _, token = await _started(tmp_path)
    await session.close()
    assert await session.handle_checkin(IVAN, token) is CheckinResult.NO_SESSION


async def test_after_end_time(tmp_path: Path):
    session, _, _, _, token = await _started(tmp_path)
    session._clock.moment = datetime(2026, 10, 7, 13, 16, tzinfo=MSK)
    assert await session.handle_checkin(IVAN, token) is CheckinResult.NO_SESSION


async def test_buffer_flushes_after_delay(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path)
    await session.handle_checkin(IVAN, token)
    assert sheet.written == []
    await asyncio.wait_for(_drain(session), timeout=1)
    assert sheet.written == [(2, 2)]


async def _drain(session) -> None:
    while session._flush_task is not None:
        await asyncio.sleep(0)


async def test_transient_failure_keeps_marks_for_retry(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path)
    sheet.fail_next_writes = 3  # три попытки call_with_retry израсходованы
    await session.handle_checkin(IVAN, token)
    await session.flush_now()
    assert sheet.written == []
    assert session._active.pending == [(2, 2)]


async def test_close_flushes_pending_marks(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path)
    await session.handle_checkin(IVAN, token)
    await session.close()
    assert sheet.written == [(2, 2)]


async def test_close_sends_summary_to_admins(tmp_path: Path):
    reports: list[str] = []

    async def report(text: str) -> None:
        reports.append(text)

    session, _, _, _, token = await _started(tmp_path)
    session._report_hook = report
    await session.handle_checkin(IVAN, token)
    await session.close()
    assert len(reports) == 1
    assert "Иванов Иван" in reports[0]
    assert "Петров Пётр" in reports[0]
    assert "Не отметились" in reports[0]


async def test_state_updated_on_each_mark(tmp_path: Path):
    session, _, _, store, token = await _started(tmp_path)
    await session.handle_checkin(IVAN, token)
    stored = store.load()
    assert stored is not None
    assert stored.marked_rows == {IVAN: 2}


async def test_flush_size_forces_write(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path)
    session._flush_size = 2
    await session.handle_checkin(IVAN, token)
    await session.handle_checkin(PETR, token)
    await asyncio.wait_for(_drain(session), timeout=1)
    assert sorted(sheet.written) == [(2, 2), (3, 2)]


async def test_restore_keeps_marks_after_restart(tmp_path: Path):
    session, _, sheet, store, token = await _started(tmp_path)
    await session.handle_checkin(IVAN, token)
    await session.flush_now()

    revived, bot2, sheet2, store2 = build(tmp_path, now=NOW, sheet=sheet)
    await revived.restore()
    assert revived.active_subject == "Матан"
    assert await revived.handle_checkin(IVAN, token) is CheckinResult.ALREADY
    await revived.close()


async def test_restore_of_finished_pair_closes_it(tmp_path: Path):
    session, _, sheet, store, token = await _started(tmp_path)
    await session.handle_checkin(IVAN, token)
    await session._flush(session._active)

    later = NOW + timedelta(hours=2)
    revived, bot2, _, store2 = build(tmp_path, now=later, sheet=sheet)
    await revived.restore()
    assert store2.load() is None
    assert bot2.edited[-1]["text"].startswith("Матан — пара закрыта")
