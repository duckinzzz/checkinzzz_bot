from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Button", callback_data=f"user:{uid}:default_button")],
        ]
    )
