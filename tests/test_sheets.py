import warnings
from datetime import date

from services.sheets import MARK, GspreadSubjectSheet
from tests.fakes import FakeWorksheet

TODAY = date(2026, 10, 7)


def _sheet(rows: list[list[str]]) -> GspreadSubjectSheet:
    return GspreadSubjectSheet(FakeWorksheet(rows))


def test_student_rows_maps_normalized_names():
    sheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", ""], ["Петров Пётр", ""]])
    assert sheet.student_rows() == {"иванов иван": 2, "петров петр": 3}


def test_student_rows_skips_blank_rows():
    sheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", ""], ["", ""]])
    assert sheet.student_rows() == {"иванов иван": 2}


def test_student_rows_on_empty_sheet():
    assert _sheet([]).student_rows() == {}


def test_ensure_date_column_finds_existing():
    sheet = _sheet([["ФИО", "07.10.2026", "09.10.2026"], ["Иванов Иван", "", ""]])
    assert sheet.ensure_date_column(TODAY) == 2


def test_ensure_date_column_finds_date_without_year():
    sheet = _sheet([["ФИО", "07.10"], ["Иванов Иван", ""]])
    assert sheet.ensure_date_column(TODAY) == 2


def test_ensure_date_column_does_not_duplicate_same_day():
    sheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", ""]])
    assert sheet.ensure_date_column(TODAY) == 2
    assert sheet.ensure_date_column(TODAY) == 2


def test_ensure_date_column_appends_after_last_filled():
    sheet = _sheet([["ФИО", "01.10.2026", "03.10.2026"], ["Иванов Иван", "", ""]])
    assert sheet.ensure_date_column(TODAY) == 4


def test_ensure_date_column_never_writes_into_column_a():
    worksheet = FakeWorksheet([])
    sheet = GspreadSubjectSheet(worksheet)
    assert sheet.ensure_date_column(TODAY) == 2
    assert worksheet.updates == [(1, 2, "07.10.2026")]


def test_marked_rows_reads_plus_only():
    sheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", "+"], ["Петров Пётр", "н"]])
    assert sheet.marked_rows(2) == {2}


def test_marked_rows_ignores_other_columns():
    sheet = _sheet([["ФИО", "07.10.2026", "09.10.2026"], ["Иванов Иван", "+", "+"]])
    assert sheet.marked_rows(3) == {2}


def test_mark_literal_is_plus():
    assert MARK == "+"


def test_parse_header_date_handles_iso_fallback():
    sheet = _sheet([["ФИО", "2026-10-07"], ["Иванов Иван", ""]])
    assert sheet.ensure_date_column(TODAY) == 2


def test_year_less_date_parses_without_deprecation_warning():
    sheet = _sheet([["ФИО", "07.10"], ["Иванов Иван", ""]])
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        assert sheet.ensure_date_column(TODAY) == 2
