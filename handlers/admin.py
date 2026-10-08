from aiogram import F, Router, types
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup

from core.log import logger
from keyboards import (
    CANCEL_CALLBACK,
    FINISH_CALLBACK,
    confirm_kb,
    finish_kb,
    subjects_kb,
)
from services.session import CheckinSession, StartPreview, StartResult
from services.subjects import Subjects

START_REPLIES: dict[StartResult, str] = {
    StartResult.STARTED: "Пара открыта, сообщение ушло в беседу.",
    StartResult.DAY_OVER: "Пары на сегодня закончились.",
    StartResult.UNKNOWN_SUBJECT: "Такого предмета нет в справочнике.",
    StartResult.SHEET_ERROR: "Не смог открыть вкладку в таблице, подробности выше.",
    StartResult.SEND_ERROR: "Не смог отправить сообщение в беседу — проверь, что бот в ней.",
}

def start_should_alert(result: StartResult) -> bool:
    return result is not StartResult.STARTED


def confirmation_text(preview: StartPreview) -> str:
    warning = ""
    if preview.active_subject is not None:
        warning = (
            f"⚠️ Сейчас идёт «{preview.active_subject}» — она будет закрыта, "
            "а её отметки уйдут в отчёт.\n\n"
        )
    return (
        f"{warning}Открыть пару «{preview.subject}»?\n"
        f"{preview.pair_number} пара, до {preview.end_at:%H:%M}."
    )


def build_admin_router(
    *, session: CheckinSession, subjects: Subjects, admin_ids: frozenset[int]
) -> Router:
    router = Router(name="admin")

    def is_admin(user_id: int) -> bool:
        return user_id in admin_ids

    async def edit(callback: types.CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
        message = callback.message
        # Telegram отдаёт InaccessibleMessage, если сообщение слишком старое —
        # его нельзя редактировать, но падать из-за этого незачем.
        if not isinstance(message, types.Message):
            logger.warning("Нажатие без редактируемого сообщения: %s", callback.data)
            return
        await message.edit_text(text, reply_markup=markup)

    def subject_at(raw_index: str) -> str | None:
        return subjects.title_at(int(raw_index)) if raw_index.isdigit() else None

    @router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
    async def cmd_start(message: types.Message) -> None:
        user = message.from_user
        if user is None or not is_admin(user.id):
            logger.warning("Посторонний стартует бота: %s", user.id if user else "unknown")
            return
        await message.answer(
            "Выбери предмет текущей пары:", reply_markup=subjects_kb(subjects.titles())
        )

    @router.callback_query(F.data.startswith("subject:"))
    async def process_subject(callback: types.CallbackQuery) -> None:
        if not is_admin(callback.from_user.id):
            await callback.answer("Нет доступа", show_alert=True)
            return

        raw_index = (callback.data or "").split(":", 1)[1]
        title = subject_at(raw_index)
        if title is None:
            await callback.answer("Предмет не найден", show_alert=True)
            return

        preview = session.preview(title)
        if isinstance(preview, StartResult):
            await callback.answer(START_REPLIES[preview], show_alert=start_should_alert(preview))
            return

        await edit(callback, confirmation_text(preview), confirm_kb(int(raw_index)))

    @router.callback_query(F.data.startswith("open:"))
    async def process_open(callback: types.CallbackQuery) -> None:
        if not is_admin(callback.from_user.id):
            await callback.answer("Нет доступа", show_alert=True)
            return

        raw_index = (callback.data or "").split(":", 1)[1]
        title = subject_at(raw_index)
        if title is None:
            await callback.answer("Предмет не найден", show_alert=True)
            return

        result = await session.start(title)
        if result is StartResult.STARTED:
            await edit(callback, f"Пара «{title}» открыта, сообщение ушло в беседу.", finish_kb())
        else:
            await edit(callback, START_REPLIES[result], subjects_kb(subjects.titles()))
        await callback.answer(START_REPLIES[result], show_alert=start_should_alert(result))

    @router.callback_query(F.data == CANCEL_CALLBACK)
    async def process_cancel(callback: types.CallbackQuery) -> None:
        if not is_admin(callback.from_user.id):
            await callback.answer("Нет доступа", show_alert=True)
            return
        await edit(callback, "Выбери предмет текущей пары:", subjects_kb(subjects.titles()))
        await callback.answer("Отменено")

    @router.callback_query(F.data == FINISH_CALLBACK)
    async def process_finish(callback: types.CallbackQuery) -> None:
        if not is_admin(callback.from_user.id):
            await callback.answer("Нет доступа", show_alert=True)
            return

        subject = session.active_subject
        if subject is None:
            # Кнопка осталась от пары, которая уже закрылась сама по расписанию.
            await callback.answer("Пары сейчас нет", show_alert=True)
            return

        await session.close()
        await edit(callback, f"Пара «{subject}» закрыта.", subjects_kb(subjects.titles()))
        await callback.answer("Пара закрыта")

    return router
