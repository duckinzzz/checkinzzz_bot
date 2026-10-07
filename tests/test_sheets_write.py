import pytest

from services.sheets import MARK, GspreadSubjectSheet, SheetTransientError
from tests.fakes import FakeWorksheet


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
