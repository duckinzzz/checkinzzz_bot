from aiogram import F, Router, types
from aiogram.enums import ChatType
from aiogram.filters import CommandStart

from core.log import logger
from keyboards import subjects_kb
from services.session import CheckinSession, StartResult
from services.subjects import Subjects

START_REPLIES: dict[StartResult, str] = {
    StartResult.STARTED: "Пара открыта, сообщение ушло в беседу.",
    StartResult.DAY_OVER: "Пары на сегодня закончились.",
    StartResult.UNKNOWN_SUBJECT: "Такого предмета нет в справочнике.",
    StartResult.SHEET_ERROR: "Не смог открыть вкладку в таблице, подробности выше.",
}


def start_should_alert(result: StartResult) -> bool:
    return result is not StartResult.STARTED


def build_admin_router(
    *, session: CheckinSession, subjects: Subjects, admin_ids: frozenset[int]
) -> Router:
    router = Router(name="admin")

    @router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
    async def cmd_start(message: types.Message) -> None:
        user = message.from_user
        if user is None or user.id not in admin_ids:
            logger.warning("Посторонний стартует бота: %s", user.id if user else "unknown")
            return
        await message.answer(
            "Выбери предмет текущей пары:", reply_markup=subjects_kb(subjects.titles())
        )

    @router.callback_query(F.data.startswith("subject:"))
    async def process_subject(callback: types.CallbackQuery) -> None:
        user = callback.from_user
        if user.id not in admin_ids:
            await callback.answer("Нет доступа", show_alert=True)
            return

        raw_index = (callback.data or "").split(":", 1)[1]
        title = subjects.title_at(int(raw_index)) if raw_index.isdigit() else None
        if title is None:
            await callback.answer("Предмет не найден", show_alert=True)
            return

        result = await session.start(title)
        await callback.answer(START_REPLIES[result], show_alert=start_should_alert(result))

    return router
