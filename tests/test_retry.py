import pytest

from utils.retry import call_with_retry


class Transient(Exception):
    pass


class Permanent(Exception):
    pass


async def test_returns_result_without_retries():
    def func(value: int) -> int:
        return value * 2

    assert await call_with_retry(func, 21, retry_on=(Transient,)) == 42


async def test_retries_transient_then_succeeds():
    attempts = []

    def func() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise Transient("429")
        return "ok"

    assert await call_with_retry(func, attempts=3, base_delay=0, retry_on=(Transient,)) == "ok"
    assert len(attempts) == 3


async def test_gives_up_after_attempts():
    def func() -> None:
        raise Transient("429")

    with pytest.raises(Transient):
        await call_with_retry(func, attempts=3, base_delay=0, retry_on=(Transient,))


async def test_permanent_error_is_not_retried():
    attempts = []

    def func() -> None:
        attempts.append(1)
        raise Permanent("нет вкладки")

    with pytest.raises(Permanent):
        await call_with_retry(func, attempts=3, base_delay=0, retry_on=(Transient,))
    assert len(attempts) == 1


async def test_delay_grows_exponentially():
    delays = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    def func() -> None:
        raise Transient("429")

    with pytest.raises(Transient):
        await call_with_retry(
            func, attempts=3, base_delay=1.0, retry_on=(Transient,), sleep=fake_sleep
        )
    assert delays == [1.0, 2.0]
