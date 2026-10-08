from typing import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

SUBJECT_CALLBACK_PREFIX = "subject:"
OPEN_CALLBACK_PREFIX = "open:"
CANCEL_CALLBACK = "cancel"
FINISH_CALLBACK = "finish"


def subjects_kb(titles: Sequence[str]) -> InlineKeyboardMarkup:
    # Индекс, а не название: в callback_data умещается 64 байта, кириллица — по два на символ.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=title, callback_data=f"{SUBJECT_CALLBACK_PREFIX}{index}")]
            for index, title in enumerate(titles)
        ]
    )


def confirm_kb(index: int) -> InlineKeyboardMarkup:
    """Открыть выбранный предмет или вернуться к списку."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть", callback_data=f"{OPEN_CALLBACK_PREFIX}{index}"
                ),
                InlineKeyboardButton(text="Отмена", callback_data=CANCEL_CALLBACK),
            ]
        ]
    )


def finish_kb() -> InlineKeyboardMarkup:
    """Досрочное завершение пары — только в личке админа."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Завершить досрочно", callback_data=FINISH_CALLBACK)],
        ]
    )
