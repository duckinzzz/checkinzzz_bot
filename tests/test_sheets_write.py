from datetime import date

import pytest

from services.sheets import MARK, GspreadSubjectSheet, SheetTransientError
from tests.fakes import FakeWorksheet

TODAY = date(2026, 10, 7)


def _sheet(rows: list[list[str]]) -> tuple[GspreadSubjectSheet, FakeWorksheet]:
    worksheet = FakeWorksheet(rows)
    return GspreadSubjectSheet(worksheet), worksheet


def test_write_marks_uses_single_batch_call():
    sheet, worksheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", ""]])
    sheet.write_marks([(2, 2), (3, 2)])
    assert len(worksheet.batch_updates) == 1
    assert len(worksheet.batch_updates[0]) == 2


def test_write_marks_puts_plus_in_cells():
    sheet, worksheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", ""]])
    sheet.write_marks([(2, 2)])
    assert worksheet.rows[1][1] == MARK


def test_write_marks_with_empty_list_makes_no_call():
    sheet, worksheet = _sheet([["ФИО", "07.10.2026"]])
    sheet.write_marks([])
    assert worksheet.batch_updates == []


def test_write_marks_builds_a1_ranges():
    sheet, worksheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", ""]])
    sheet.write_marks([(2, 2)])
    assert worksheet.batch_updates[0][0]["range"] == "B2"


def test_write_marks_wraps_transient_error():
    sheet, worksheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", ""]])

    def boom(*args: object, **kwargs: object) -> None:
        raise SheetTransientError("429")

    worksheet.batch_update = boom  # type: ignore[method-assign]
    with pytest.raises(SheetTransientError):
        sheet.write_marks([(2, 2)])


def test_plus_is_not_turned_into_a_formula():
    sheet, worksheet = _sheet([["№", "ФИО", "07.10.2026"], ["1", "Иванов Иван", ""]])
    sheet.write_marks([(2, 3)])

    assert worksheet.rows[1][2] == MARK
    assert worksheet.rows[1][2] != "#ERROR!", "«+» нельзя писать как формулу"


def test_marks_are_written_with_raw_input():
    sheet, worksheet = _sheet([["№", "ФИО", "07.10.2026"]])
    sheet.write_marks([(2, 3)])

    assert worksheet.input_options == ["RAW"]


def test_date_header_is_written_with_raw_input():
    worksheet = FakeWorksheet([["№", "ФИО"]])
    sheet = GspreadSubjectSheet(worksheet)
    sheet.ensure_date_column(TODAY)

    assert worksheet.input_options == ["RAW"]
    assert worksheet.rows[0][2] == "07.10.2026"
    assert worksheet.rows[0][2] != "#ERROR!"
