import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from services.state import StateStore, StoredSession

MSK = ZoneInfo("Europe/Moscow")


def _state() -> StoredSession:
    return StoredSession(
        token="abc123",
        subject="Матан",
        worksheet="Матан",
        message_id=42,
        day=date(2026, 10, 7),
        pair_number=3,
        end_at=datetime(2026, 10, 7, 13, 15, tzinfo=MSK),
        marked_rows={111: 2, 222: 5},
        pending=((2, 4),),
    )


def test_round_trip(tmp_path: Path):
    store = StateStore(tmp_path / "state.json")
    store.save(_state())
    assert store.load() == _state()


def test_load_without_file(tmp_path: Path):
    assert StateStore(tmp_path / "state.json").load() is None


def test_save_is_atomic_and_leaves_no_tmp(tmp_path: Path):
    store = StateStore(tmp_path / "state.json")
    store.save(_state())
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]


def test_save_creates_parent_directory(tmp_path: Path):
    store = StateStore(tmp_path / "nested" / "state.json")
    store.save(_state())
    assert (tmp_path / "nested" / "state.json").is_file()


def test_clear_removes_file(tmp_path: Path):
    store = StateStore(tmp_path / "state.json")
    store.save(_state())
    store.clear()
    assert store.load() is None


def test_clear_without_file_is_noop(tmp_path: Path):
    StateStore(tmp_path / "state.json").clear()


@pytest.mark.parametrize(
    "payload",
    [
        "{не json",
        "{}",
        "[]",
        '{"token": "a", "subject": "Матан"}',
        '{"token": "a", "subject": "Матан", "worksheet": "М", "message_id": 1, '
        '"day": "07.10.2026", "pair_number": 1, "end_at": "2026-10-07T13:15:00+03:00", '
        '"marked_rows": {}, "pending": []}',
    ],
)
def test_broken_state_is_ignored(tmp_path: Path, payload: str):
    path = tmp_path / "state.json"
    path.write_text(payload, encoding="utf-8")
    assert StateStore(path).load() is None


def test_json_keeps_cyrillic_and_aware_datetime(tmp_path: Path):
    path = tmp_path / "state.json"
    store = StateStore(path)
    store.save(_state())
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["subject"] == "Матан"
    assert raw["marked_rows"] == {"111": 2, "222": 5}
    assert raw["end_at"].endswith("+03:00")


def test_from_json_rejects_bad_end_at():
    with pytest.raises(ValueError):
        StoredSession.from_json(
            {
                "token": "a",
                "subject": "Матан",
                "worksheet": "Матан",
                "message_id": 1,
                "day": "2026-10-07",
                "pair_number": 1,
                "end_at": "вчера",
                "marked_rows": {},
                "pending": [],
            }
        )
