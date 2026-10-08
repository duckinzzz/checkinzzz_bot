from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from services.schedule import current_pair

MSK = ZoneInfo("Europe/Moscow")
ENDS = [time(10, 5), time(11, 40), time(13, 15)]


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 10, 7, hour, minute, second, tzinfo=MSK)


def test_before_first_pair():
    pair = current_pair(_at(9, 0), ENDS)
    assert pair is not None
    assert pair.number == 1
    assert pair.end_at == _at(10, 5)


def test_between_pairs_picks_next():
    pair = current_pair(_at(11, 0), ENDS)
    assert pair is not None
    assert pair.number == 2
    assert pair.end_at == _at(11, 40)


def test_exactly_at_end_time_pair_is_over():
    pair = current_pair(_at(10, 5), ENDS)
    assert pair is not None
    assert pair.number == 2
    assert pair.end_at == _at(11, 40)


def test_after_last_pair():
    assert current_pair(_at(15, 0), ENDS) is None


def test_exactly_at_last_end_time():
    assert current_pair(_at(13, 15), ENDS) is None


def test_single_pair_list():
    pair = current_pair(_at(9, 0), [time(10, 5)])
    assert pair is not None
    assert pair.number == 1


def test_naive_datetime_rejected():
    with pytest.raises(ValueError, match="таймзон"):
        current_pair(datetime(2026, 10, 7, 9, 0), ENDS)
