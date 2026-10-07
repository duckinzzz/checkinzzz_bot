import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found")


class ConfigError(ValueError):
    """Некорректная конфигурация окружения."""


def parse_pair_end_times(raw: str) -> list[time]:
    times: list[time] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            hour, minute = chunk.split(":")
            times.append(time(int(hour), int(minute)))
        except ValueError as exc:
            raise ConfigError(f"PAIR_END_TIMES: не удалось разобрать {chunk!r}") from exc
    if not times:
        raise ConfigError("PAIR_END_TIMES: список пуст")
    if times != sorted(times):
        raise ConfigError("PAIR_END_TIMES: времена должны идти по возрастанию")
    return times


def parse_admin_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError as exc:
            raise ConfigError(f"ADMIN_IDS: {chunk!r} не похоже на id") from exc
    if not ids:
        raise ConfigError("ADMIN_IDS: список пуст")
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    admin_ids: frozenset[int]
    chat_id: int
    pair_end_times: tuple[time, ...]
    spreadsheet_id: str
    credentials_path: Path
    tz: ZoneInfo
    students_path: Path
    subjects_path: Path
    state_path: Path


def _required(env: Mapping[str, str], name: str) -> str:
    value = (env.get(name) or "").strip()
    if not value:
        raise ConfigError(f"{name}: переменная не задана")
    return value


def _required_int(env: Mapping[str, str], name: str) -> int:
    raw = _required(env, name)
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}: {raw!r} не число") from exc


def _optional_path(env: Mapping[str, str], name: str, default: str) -> Path:
    value = (env.get(name) or "").strip()
    return Path(value or default)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env

    tz_name = (env.get("TZ") or "").strip() or "Europe/Moscow"
    try:
        tz = ZoneInfo(tz_name)
    except Exception as exc:  # ZoneInfoNotFoundError и производные
        raise ConfigError(f"TZ: неизвестная таймзона {tz_name!r}") from exc

    credentials_path = Path(_required(env, "GOOGLE_CREDENTIALS_PATH"))
    if not credentials_path.is_file():
        raise ConfigError(f"GOOGLE_CREDENTIALS_PATH: файл не найден: {credentials_path}")

    return Settings(
        admin_ids=parse_admin_ids(_required(env, "ADMIN_IDS")),
        chat_id=_required_int(env, "CHAT_ID"),
        pair_end_times=tuple(parse_pair_end_times(_required(env, "PAIR_END_TIMES"))),
        spreadsheet_id=_required(env, "SPREADSHEET_ID"),
        credentials_path=credentials_path,
        tz=tz,
        students_path=_optional_path(env, "STUDENTS_PATH", "data/students.json"),
        subjects_path=_optional_path(env, "SUBJECTS_PATH", "data/subjects.json"),
        state_path=_optional_path(env, "STATE_PATH", "data/state.json"),
    )
