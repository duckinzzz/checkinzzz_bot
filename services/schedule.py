from dataclasses import dataclass
from datetime import datetime, time
from typing import Sequence


@dataclass(frozen=True)
class CurrentPair:
    number: int
    end_at: datetime


def current_pair(now: datetime, pair_end_times: Sequence[time]) -> CurrentPair | None:
    """Ближайший конец пары, который ещё не наступил.

    Ровно в момент окончания пара уже считается закончившейся, поэтому
    сравнение строгое. `None` — все пары на сегодня прошли.
    """
    if now.tzinfo is None:
        raise ValueError("now должен быть с таймзоной")

    for index, end in enumerate(pair_end_times, start=1):
        candidate = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
        if candidate > now:
            return CurrentPair(number=index, end_at=candidate)
    return None
