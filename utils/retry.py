import asyncio
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


async def call_with_retry(
    func: Callable[..., T],
    *args: Any,
    attempts: int = 3,
    base_delay: float = 1.0,
    retry_on: tuple[type[BaseException], ...],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Вызвать синхронную func в отдельном потоке, повторяя на retry_on.

    Задержка между попытками растёт вдвое: base_delay, 2*base_delay, ...
    """
    for attempt in range(attempts):
        try:
            return await asyncio.to_thread(func, *args)
        except retry_on:
            if attempt == attempts - 1:
                raise
            await sleep(base_delay * (2**attempt))
    raise AssertionError("недостижимо: цикл заканчивается return или raise")
