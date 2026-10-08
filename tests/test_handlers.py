from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from handlers import get_main_router
from handlers.admin import START_REPLIES, build_admin_router, start_should_alert
from handlers.attendance import CHECKIN_REPLIES, build_attendance_router
from keyboards.admin import subjects_kb
from services.session import CheckinResult, StartResult
from services.subjects import Subjects

ADMIN = 111

SUBJECTS = Subjects({"Матан": "Матан", "Физика": "Физика"})


def _router(*, start=StartResult.STARTED, checkin=CheckinResult.MARKED):
    return SimpleNamespace(
        start=AsyncMock(return_value=start),
        handle_checkin=AsyncMock(return_value=checkin),
        chat_id=-100,
    )


def test_get_main_router_registers_two_routers():
    router = get_main_router(_router(), SUBJECTS, frozenset({ADMIN}))
    assert len(router.sub_routers) == 2


def test_subjects_kb_uses_index_in_callback():
    markup = subjects_kb(SUBJECTS.titles())
    assert markup.inline_keyboard[0][0].text == "Матан"
    assert markup.inline_keyboard[0][0].callback_data == "subject:0"
    assert markup.inline_keyboard[1][0].callback_data == "subject:1"


def test_all_results_have_text():
    for result in StartResult:
        assert START_REPLIES[result]
    for result in CheckinResult:
        assert CHECKIN_REPLIES[result]


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (StartResult.DAY_OVER, True),
        (StartResult.SHEET_ERROR, True),
        (StartResult.UNKNOWN_SUBJECT, True),
        (StartResult.STARTED, False),
    ],
)
def test_start_reply_alert_flag(result, expected):
    assert start_should_alert(result) is expected


def test_admin_router_is_built():
    assert (
        build_admin_router(
            session=_router(), subjects=SUBJECTS, admin_ids=frozenset({ADMIN})
        )
        is not None
    )


def test_attendance_router_is_built():
    assert build_attendance_router(session=_router()) is not None
