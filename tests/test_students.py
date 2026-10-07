import json
from pathlib import Path

import pytest

from core.config import ConfigError
from services.students import StudentDirectory


def _write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "students.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_and_lookup(tmp_path: Path):
    directory = StudentDirectory.load(_write(tmp_path, {"111": "Иванов Иван Иванович"}))
    assert directory.name_of(111) == "Иванов Иван Иванович"
    assert directory.name_of(999) is None


def test_all_names_sorted(tmp_path: Path):
    directory = StudentDirectory.load(_write(tmp_path, {"2": "Петров Пётр", "1": "Иванов Иван"}))
    assert directory.all_names() == ["Иванов Иван", "Петров Пётр"]


def test_names_are_stripped(tmp_path: Path):
    directory = StudentDirectory.load(_write(tmp_path, {"1": "  Иванов Иван  "}))
    assert directory.name_of(1) == "Иванов Иван"


def test_missing_file(tmp_path: Path):
    with pytest.raises(ConfigError, match="не найден"):
        StudentDirectory.load(tmp_path / "nope.json")


def test_broken_json(tmp_path: Path):
    path = tmp_path / "students.json"
    path.write_text("{не json", encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON"):
        StudentDirectory.load(path)


def test_not_an_object(tmp_path: Path):
    with pytest.raises(ConfigError, match="объект"):
        StudentDirectory.load(_write(tmp_path, ["111"]))


def test_non_numeric_key(tmp_path: Path):
    with pytest.raises(ConfigError, match="ключ"):
        StudentDirectory.load(_write(tmp_path, {"student": "Иванов Иван"}))


@pytest.mark.parametrize("value", ["", "   ", 42])
def test_bad_name(tmp_path: Path, value: object):
    with pytest.raises(ConfigError, match="ФИО"):
        StudentDirectory.load(_write(tmp_path, {"1": value}))
