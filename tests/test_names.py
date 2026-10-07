import pytest

from utils.names import normalize_name


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Иванов Иван Иванович", "  Иванов   Иван  Иванович "),
        ("Пётр Семёнов", "Петр Семенов"),
        ("ПЁТР СЕМЁНОВ", "петр семенов"),
        ("Иванов\tИван\nИванович", "Иванов Иван Иванович"),
    ],
)
def test_normalize_name_matches_variants(left: str, right: str):
    assert normalize_name(left) == normalize_name(right)


def test_normalize_name_keeps_different_people_apart():
    assert normalize_name("Иванов Иван") != normalize_name("Иванов Иван Иванович")


def test_normalize_name_of_blank_is_empty():
    assert normalize_name("   ") == ""
