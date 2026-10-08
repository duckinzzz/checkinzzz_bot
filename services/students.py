import json
from pathlib import Path

from core.config import ConfigError


class StudentDirectory:
    """Справочник группы: tg_id → ФИО."""

    def __init__(self, by_id: dict[int, str]) -> None:
        self._by_id = dict(by_id)

    @classmethod
    def load(cls, path: Path) -> "StudentDirectory":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"Справочник студентов не найден: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Справочник студентов: некорректный JSON в {path}") from exc

        if not isinstance(raw, dict):
            raise ConfigError(
                f'Справочник студентов: ожидался объект вида {{"tg_id": "ФИО"}}, {path}'
            )

        by_id: dict[int, str] = {}
        for key, value in raw.items():
            try:
                tg_id = int(key)
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"Справочник студентов: ключ {key!r} не число") from exc
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"Справочник студентов: у {tg_id} пустое ФИО")
            by_id[tg_id] = value.strip()

        return cls(by_id)

    def name_of(self, tg_id: int) -> str | None:
        return self._by_id.get(tg_id)

    def all_names(self) -> list[str]:
        return sorted(self._by_id.values())
