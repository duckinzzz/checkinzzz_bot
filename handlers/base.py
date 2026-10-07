from aiogram import F, Router, types
from aiogram.filters import CommandStart

import keyboards as kb
from core.app import logger
from utils.users import get_user_name

base_router = Router()


@base_router.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
    user_name = get_user_name(message.from_user)
    uid = message.from_user.id if message.from_user else 0

    welcome_text = "aiogram template with echo-bot"

    await message.answer(welcome_text, reply_markup=kb.main_kb(uid))

    logger.info(f"User {user_name} ({uid}) started the bot")


@base_router.callback_query(F.data.split(':')[2] == 'default_button')
async def process_button(callback: types.CallbackQuery) -> None:
    await callback.answer("You pressed the button")
