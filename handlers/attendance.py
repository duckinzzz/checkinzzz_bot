from aiogram import F, Router, types

from services.session import CheckinResult, CheckinSession

CHECKIN_REPLIES: dict[CheckinResult, str] = {
    CheckinResult.MARKED: "Отмечен ✅",
    CheckinResult.ALREADY: "Ты уже отмечен",
    CheckinResult.NO_SESSION: "Эта пара уже закончилась",
    CheckinResult.NOT_IN_GROUP: "Тебя нет в списке группы",
    CheckinResult.NOT_IN_SHEET: "Не нашёл тебя в таблице, написал админу",
}


def build_attendance_router(*, session: CheckinSession) -> Router:
    router = Router(name="attendance")

    @router.callback_query(F.data.startswith("att:"))
    async def process_checkin(callback: types.CallbackQuery) -> None:
        # Нажатия из чужих чатов игнорируем: кнопка живёт только в беседе группы.
        if callback.message is None or callback.message.chat.id != session.chat_id:
            await callback.answer()
            return

        token = (callback.data or "").split(":", 1)[1]
        result = await session.handle_checkin(callback.from_user.id, token)
        await callback.answer(
            CHECKIN_REPLIES[result], show_alert=result is CheckinResult.NOT_IN_SHEET
        )

    return router
