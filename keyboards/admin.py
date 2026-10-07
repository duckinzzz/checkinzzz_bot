from typing import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

SUBJECT_CALLBACK_PREFIX = "subject:"


def subjects_kb(titles: Sequence[str]) -> InlineKeyboardMarkup:
    # Индекс, а не название: в callback_data умещается 64 байта, кириллица — по два на символ.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=title, callback_data=f"{SUBJECT_CALLBACK_PREFIX}{index}")]
            for index, title in enumerate(titles)
        ]
    )
