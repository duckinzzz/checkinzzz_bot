from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from core.bootstrap import build_context
from core.config import Settings
from handlers import get_main_router
from tests.fakes import FakeBot


def _settings(tmp_path: Path) -> Settings:
    students = tmp_path / "students.json"
    students.write_text('{"111": "Иванов Иван"}', encoding="utf-8")
    subjects = tmp_path / "subjects.json"
    subjects.write_text('{"Матан": "Матан"}', encoding="utf-8")
    return Settings(
        admin_ids=frozenset({111}),
        chat_id=-100,
        pair_end_times=(time(10, 5),),
        spreadsheet_id="x",
        credentials_path=tmp_path / "credentials.json",
        tz=ZoneInfo("Europe/Moscow"),
        students_path=students,
        subjects_path=subjects,
        state_path=tmp_path / "state.json",
    )


def test_bootstrap_wires_session_and_router(tmp_path: Path):
    context = build_context(_settings(tmp_path), FakeBot())  # type: ignore[arg-type]

    assert context.session.chat_id == -100
    assert context.subjects.titles() == ("Матан",)
    assert context.admin_ids == frozenset({111})

    router = get_main_router(context.session, context.subjects, context.admin_ids)
    assert len(router.sub_routers) == 2
