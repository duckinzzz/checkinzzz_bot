from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.config import ConfigError, load_settings, parse_admin_ids, parse_pair_end_times


def _env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}", encoding="utf-8")
    env = {
        "ADMIN_IDS": "111,222",
        "CHAT_ID": "-1001234567890",
        "PAIR_END_TIMES": "10:05,11:40,13:15",
        "SPREADSHEET_ID": "sheet-id",
        "GOOGLE_CREDENTIALS_PATH": str(credentials),
    }
    env.update(overrides)
    return env


def test_parse_pair_end_times_reads_hh_mm():
    assert parse_pair_end_times("10:05, 11:40,13:15") == [time(10, 5), time(11, 40), time(13, 15)]


@pytest.mark.parametrize("raw", ["", "  ", "10:05,чепуха", "13:15,10:05"])
def test_parse_pair_end_times_rejects_bad_input(raw: str):
    with pytest.raises(ConfigError):
        parse_pair_end_times(raw)


def test_parse_admin_ids_skips_spaces():
    assert parse_admin_ids(" 111 , 222 ") == frozenset({111, 222})


def test_parse_admin_ids_rejects_garbage():
    with pytest.raises(ConfigError):
        parse_admin_ids("111,abc")


def test_load_settings_uses_defaults(tmp_path: Path):
    settings = load_settings(_env(tmp_path))
    assert settings.admin_ids == frozenset({111, 222})
    assert settings.chat_id == -1001234567890
    assert settings.pair_end_times == (time(10, 5), time(11, 40), time(13, 15))
    assert settings.spreadsheet_id == "sheet-id"
    assert settings.tz == ZoneInfo("Europe/Moscow")
    assert settings.students_path == Path("data/students.json")
    assert settings.subjects_path == Path("data/subjects.json")
    assert settings.state_path == Path("data/state.json")


def test_load_settings_honours_tz_and_paths(tmp_path: Path):
    settings = load_settings(
        _env(tmp_path, TZ="Asia/Yekaterinburg", STUDENTS_PATH=str(tmp_path / "s.json"))
    )
    assert settings.tz == ZoneInfo("Asia/Yekaterinburg")
    assert settings.students_path == tmp_path / "s.json"


@pytest.mark.parametrize(
    "missing",
    ["ADMIN_IDS", "CHAT_ID", "PAIR_END_TIMES", "SPREADSHEET_ID", "GOOGLE_CREDENTIALS_PATH"],
)
def test_load_settings_requires_variable(tmp_path: Path, missing: str):
    env = _env(tmp_path)
    env.pop(missing)
    with pytest.raises(ConfigError, match=missing):
        load_settings(env)


def test_load_settings_rejects_missing_credentials_file(tmp_path: Path):
    with pytest.raises(ConfigError, match="GOOGLE_CREDENTIALS_PATH"):
        load_settings(_env(tmp_path, GOOGLE_CREDENTIALS_PATH=str(tmp_path / "nope.json")))


def test_load_settings_rejects_unknown_tz(tmp_path: Path):
    with pytest.raises(ConfigError, match="TZ"):
        load_settings(_env(tmp_path, TZ="Mars/Olympus"))


def test_load_settings_rejects_non_numeric_chat_id(tmp_path: Path):
    with pytest.raises(ConfigError, match="CHAT_ID"):
        load_settings(_env(tmp_path, CHAT_ID="group-chat"))
