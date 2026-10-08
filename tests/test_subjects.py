import json
from pathlib import Path

import pytest

from core.config import ConfigError
from services.subjects import Subjects


def _write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "subjects.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_titles_keep_file_order(tmp_path: Path):
    subjects = Subjects.load(_write(tmp_path, {"Матан": "Матан", "Физика": "Физика 1 сем"}))
    assert subjects.titles() == ("Матан", "Физика")


def test_title_at(tmp_path: Path):
    subjects = Subjects.load(_write(tmp_path, {"Матан": "Матан"}))
    assert subjects.title_at(0) == "Матан"
    assert subjects.title_at(5) is None


def test_worksheet_of(tmp_path: Path):
    subjects = Subjects.load(_write(tmp_path, {"Матан": "Матан 1 сем"}))
    assert subjects.worksheet_of("Матан") == "Матан 1 сем"
    assert subjects.worksheet_of("Неизвестный") is None


def test_missing_file(tmp_path: Path):
    with pytest.raises(ConfigError, match="не найден"):
        Subjects.load(tmp_path / "nope.json")


def test_broken_json(tmp_path: Path):
    path = tmp_path / "subjects.json"
    path.write_text("{не json", encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON"):
        Subjects.load(path)


def test_empty_object(tmp_path: Path):
    with pytest.raises(ConfigError, match="пуст"):
        Subjects.load(_write(tmp_path, {}))


def test_blank_worksheet(tmp_path: Path):
    with pytest.raises(ConfigError, match="вкладк"):
        Subjects.load(_write(tmp_path, {"Матан": "  "}))


def test_duplicate_worksheets_rejected(tmp_path: Path):
    with pytest.raises(ConfigError, match="повтор"):
        Subjects.load(_write(tmp_path, {"Матан": "Лист", "Физика": "Лист"}))
