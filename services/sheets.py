from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Protocol, Sequence

import gspread
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
from gspread.utils import rowcol_to_a1

from utils.names import normalize_name

MARK = "+"



class SheetError(RuntimeError):
    """Постоянная ошибка: нет доступа, нет вкладки, нет таблицы."""


class SheetTransientError(SheetError):
    """Временная ошибка Google API: 429, 5xx, сеть."""


class SubjectSheet(Protocol):
    def student_rows(self) -> dict[str, int]:
        """Нормализованное ФИО → номер строки (1-based)."""
        ...

    def ensure_date_column(self, day: date) -> int:
        """Номер столбца с датой; создаёт столбец, если его нет."""
        ...

    def marked_rows(self, column: int) -> set[int]:
        """Номера строк, где в этом столбце уже стоит «+»."""
        ...

    def write_marks(self, marks: Sequence[tuple[int, int]]) -> None:
        """Проставить «+» во все (row, column) одной пачкой."""
        ...


def _parse_header_date(cell: str, today: date) -> date | None:
    """Разобрать дату из шапки: DD.MM.YYYY, DD.MM (год текущий) или ISO.

    Формат без года разбирается руками: strptime с "%d.%m" подставляет
    год 1900 и с Python 3.14 ругается DeprecationWarning.
    """
    value = cell.strip()
    if not value:
        return None

    try:
        full = datetime.strptime(value, "%d.%m.%Y")
        return date(full.year, full.month, full.day)
    except ValueError:
        pass

    day_month = value.split(".")
    if len(day_month) == 2 and all(part.isdigit() for part in day_month):
        try:
            return date(today.year, int(day_month[1]), int(day_month[0]))
        except ValueError:
            return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _translate(exc: APIError) -> SheetError:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 429 or (isinstance(status, int) and 500 <= status < 600):
        return SheetTransientError(str(exc))
    return SheetError(str(exc))


class GspreadSubjectSheet:
    """Вкладка одного предмета в Google-таблице."""

    def __init__(self, worksheet: "gspread.Worksheet") -> None:
        self._ws = worksheet
        self._cache: list[list[str]] | None = None

    @classmethod
    def open(
        cls, spreadsheet_id: str, worksheet: str, credentials_path: Path
    ) -> "GspreadSubjectSheet":
        try:
            client = gspread.service_account(filename=str(credentials_path))
        except Exception as exc:
            raise SheetError(f"Не удалось прочитать ключ сервисного аккаунта: {exc}") from exc

        try:
            spreadsheet = client.open_by_key(spreadsheet_id)
        except SpreadsheetNotFound as exc:
            raise SheetError(
                f"Таблица {spreadsheet_id} не найдена. Проверь, что она расшарена "
                f"на email сервисного аккаунта из {credentials_path}"
            ) from exc
        except APIError as exc:
            raise _translate(exc) from exc

        try:
            worksheet_object = spreadsheet.worksheet(worksheet)
        except WorksheetNotFound as exc:
            raise SheetError(f"В таблице нет вкладки {worksheet!r}") from exc
        except APIError as exc:
            raise _translate(exc) from exc

        return cls(worksheet_object)

    def _values(self) -> list[list[str]]:
        if self._cache is None:
            try:
                self._cache = self._ws.get_all_values()
            except APIError as exc:
                raise _translate(exc) from exc
        return self._cache

    def student_rows(self) -> dict[str, int]:
        rows: dict[str, int] = {}
        for index, record in enumerate(self._values(), start=1):
            if index == 1 or not record:
                continue
            name = record[0].strip()
            if name:
                rows[normalize_name(name)] = index
        return rows

    def ensure_date_column(self, day: date) -> int:
        header = self._values()[0] if self._values() else []
        for index, cell in enumerate(header, start=1):
            if _parse_header_date(cell, day) == day:
                return index

        # Колонка A занята ФИО, поэтому дата никогда не пишется в неё.
        column = max(len(header), 1) + 1
        try:
            self._ws.update_cell(1, column, day.strftime("%d.%m.%Y"))
        except APIError as exc:
            raise _translate(exc) from exc
        self._cache = None
        return column

    def marked_rows(self, column: int) -> set[int]:
        try:
            values = self._ws.col_values(column)
        except APIError as exc:
            raise _translate(exc) from exc
        return {
            index
            for index, value in enumerate(values, start=1)
            if index > 1 and value.strip() == MARK
        }

    def write_marks(self, marks: Sequence[tuple[int, int]]) -> None:
        if not marks:
            return
        data = [
            {"range": rowcol_to_a1(row, column), "values": [[MARK]]} for row, column in marks
        ]
        try:
            self._ws.batch_update(data, value_input_option="USER_ENTERED")
        except APIError as exc:
            raise _translate(exc) from exc
