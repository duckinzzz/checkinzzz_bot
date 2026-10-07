from aiogram import Router, types

from core.app import logger
from utils.users import get_user_name

echo_router = Router()


@echo_router.message()
async def universal_handler(message: types.Message) -> None:
    user_name = get_user_name(message.from_user)
    uid = message.from_user.id if message.from_user else 0
    content_type = str(message.content_type).split(".")[-1]
    text = message.text or message.caption

    logger.info(
        f"\nuserID: {uid}\nusername: {user_name}\ncontent_type: {content_type}\ntext: {text}"
    )

    await message.answer(
        f"userID: {uid}\n"
        f"username: {user_name}\n"
        f"content_type: {content_type}\n"
        f"text: {text}"
    )
