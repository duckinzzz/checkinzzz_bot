import asyncio

from core.app import bot, dp, logger
from handlers import get_main_router


async def announce_start() -> None:
    logger.info("Bot started")


async def main() -> None:
    dp.include_router(get_main_router())

    await bot.delete_webhook(drop_pending_updates=True)
    await announce_start()

    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
