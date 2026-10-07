import json
from pathlib import Path

from core.config import ConfigError


class Subjects:
    """Справочник предметов: название для кнопки → имя вкладки в таблице."""

    def __init__(self, by_title: dict[str, str]) -> None:
        self._by_title = dict(by_title)
        self._titles = tuple(by_title)

    @classmethod
    def load(cls, path: Path) -> "Subjects":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"Справочник предметов не найден: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Справочник предметов: некорректный JSON в {path}") from exc

        if not isinstance(raw, dict) or not raw:
            raise ConfigError(
                f'Справочник предметов пуст или не объект вида {{"Предмет": "Вкладка"}}: {path}'
            )

        by_title: dict[str, str] = {}
        used_worksheets: dict[str, str] = {}
        for title, worksheet in raw.items():
            if not isinstance(title, str) or not title.strip():
                raise ConfigError(f"Справочник предметов: пустое название предмета в {path}")
            if not isinstance(worksheet, str) or not worksheet.strip():
                raise ConfigError(f"Справочник предметов: у {title!r} не указана вкладка")
            worksheet = worksheet.strip()
            if worksheet in used_worksheets:
                raise ConfigError(
                    f"Справочник предметов: вкладка {worksheet!r} повторяется "
                    f"у {used_worksheets[worksheet]!r} и {title!r}"
                )
            used_worksheets[worksheet] = title
            by_title[title.strip()] = worksheet

        return cls(by_title)

    def titles(self) -> tuple[str, ...]:
        return self._titles

    def title_at(self, index: int) -> str | None:
        if 0 <= index < len(self._titles):
            return self._titles[index]
        return None

    def worksheet_of(self, title: str) -> str | None:
        return self._by_title.get(title)
