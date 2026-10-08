from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CHECKIN_CALLBACK_PREFIX = "att:"


def checkin_kb(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отметиться", callback_data=f"{CHECKIN_CALLBACK_PREFIX}{token}"
                )
            ],
        ]
    )
