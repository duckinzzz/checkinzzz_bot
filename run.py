import asyncio

from aiogram.types import BotCommand

from core.app import bot, dp, logger
from core.bootstrap import build_context
from core.config import load_settings
from handlers import get_main_router


async def main() -> None:
    settings = load_settings()
    context = build_context(settings, bot)

    dp.include_router(get_main_router(context.session, context.subjects, context.admin_ids))
    await bot.set_my_commands(
        [BotCommand(command="start", description="Выбрать предмет текущей пары")]
    )

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot started")

    await context.session.restore()
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
