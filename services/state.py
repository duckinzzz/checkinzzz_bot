import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.log import logger


@dataclass(frozen=True)
class StoredSession:
    """Активная пара в том виде, в каком она переживает рестарт."""

    token: str
    subject: str
    worksheet: str
    message_id: int
    day: date
    pair_number: int
    end_at: datetime
    marked_rows: dict[int, int]
    pending: tuple[tuple[int, int], ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "subject": self.subject,
            "worksheet": self.worksheet,
            "message_id": self.message_id,
            "day": self.day.isoformat(),
            "pair_number": self.pair_number,
            "end_at": self.end_at.isoformat(),
            "marked_rows": {str(tg_id): row for tg_id, row in self.marked_rows.items()},
            "pending": [[row, column] for row, column in self.pending],
        }

    @classmethod
    def from_json(cls, raw: object) -> "StoredSession":
        if not isinstance(raw, dict):
            raise ValueError("состояние не объект")

        marked = raw["marked_rows"]
        pending = raw["pending"]
        if not isinstance(marked, dict) or not isinstance(pending, list):
            raise ValueError("marked_rows или pending не той формы")

        end_at = datetime.fromisoformat(str(raw["end_at"]))
        if end_at.tzinfo is None:
            raise ValueError("end_at без таймзоны")

        return cls(
            token=str(raw["token"]),
            subject=str(raw["subject"]),
            worksheet=str(raw["worksheet"]),
            message_id=int(raw["message_id"]),
            day=date.fromisoformat(str(raw["day"])),
            pair_number=int(raw["pair_number"]),
            end_at=end_at,
            marked_rows={int(tg_id): int(row) for tg_id, row in marked.items()},
            pending=tuple((int(row), int(column)) for row, column in pending),
        )


class StateStore:
    """Файл состояния на volume: активная пара и буфер отметок."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> StoredSession | None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Файл состояния %s не читается (%s), стартую с чистого листа", self._path, exc
            )
            return None

        try:
            return StoredSession.from_json(raw)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Файл состояния %s повреждён (%s), стартую с чистого листа", self._path, exc
            )
            return None

    def save(self, state: StoredSession) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(f"{self._path.name}.tmp")
        tmp.write_text(json.dumps(state.to_json(), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path)

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
