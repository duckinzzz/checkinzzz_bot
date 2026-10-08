"""Поток админа в ЛС: подтверждение запуска и кнопка досрочного завершения.

Роутер здесь настоящий, апдейты прогоняются через Dispatcher.feed_update —
проверяется вся цепочка «нажатие → сессия → ответ», а не только тексты.
"""

from datetime import datetime, timezone

from aiogram import Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from handlers.admin import build_admin_router
from services.session import CheckinSession
from services.subjects import Subjects
from tests.fakes import FakeBot
from tests.test_session_start import build

ADMIN = 111
STRANGER = 999
SUBJECTS = Subjects({"Матан": "Матан", "Физика": "Физика"})

_update_id = iter(range(1000, 2000))


def _callback(data: str, user_id: int) -> CallbackQuery:
    user = User(id=user_id, is_bot=False, first_name="Кто-то")
    chat = Chat(id=user_id, type="private")
    message = Message(
        message_id=555,
        date=datetime.now(timezone.utc),
        chat=chat,
        from_user=user,
        text="меню",
    )
    return CallbackQuery(id=f"cb{next(_update_id)}", from_user=user, chat_instance="ci", data=data, message=message)


async def _press(session: CheckinSession, bot: FakeBot, data: str, user_id: int = ADMIN) -> None:
    dispatcher = Dispatcher()
    dispatcher.include_router(
        build_admin_router(session=session, subjects=SUBJECTS, admin_ids=frozenset({ADMIN}))
    )
    update = Update(update_id=next(_update_id), callback_query=_callback(data, user_id))
    await dispatcher.feed_update(bot, update)


def _last_edited(bot: FakeBot) -> dict:
    return bot.edited[-1]


def _buttons(bot: FakeBot) -> list[str]:
    markup = _last_edited(bot)["kwargs"]["reply_markup"]
    return [button.text for row in markup.inline_keyboard for button in row]


async def test_subject_press_asks_for_confirmation(tmp_path):
    session, bot, _, _ = build(tmp_path, subjects=SUBJECTS)

    await _press(session, bot, "subject:0")

    text = _last_edited(bot)["text"]
    assert "Открыть пару «Матан»?" in text
    assert "Сейчас идёт" not in text
    assert _buttons(bot) == ["Открыть", "Отмена"]
    assert session.active_subject is None, "до подтверждения пара не открывается"


async def test_subject_press_warns_about_running_pair(tmp_path):
    session, bot, _, _ = build(tmp_path, subjects=SUBJECTS)
    await session.start("Матан")

    await _press(session, bot, "subject:1")

    text = _last_edited(bot)["text"]
    assert "Сейчас идёт «Матан»" in text
    assert "будет закрыта" in text
    assert "Открыть пару «Физика»?" in text


async def test_open_starts_pair_and_offers_early_finish(tmp_path):
    session, bot, sheet, store = build(tmp_path, subjects=SUBJECTS)

    await _press(session, bot, "open:0")

    assert session.active_subject == "Матан"
    assert len(bot.sent) == 1, "сообщение в беседу ушло"
    assert bot.sent[0]["chat_id"] == -100
    assert "открыта" in _last_edited(bot)["text"]
    assert _buttons(bot) == ["Завершить досрочно"]


async def test_open_from_stale_confirmation_replaces_running_pair(tmp_path):
    session, bot, _, _ = build(tmp_path, subjects=SUBJECTS)
    await session.start("Матан")

    await _press(session, bot, "open:1")

    assert session.active_subject == "Физика"
    assert len(bot.sent) == 2, "новая пара открыта"
    assert bot.edited, "прошлая пара закрыта штатным путём"


async def test_cancel_returns_to_subject_menu(tmp_path):
    session, bot, _, _ = build(tmp_path, subjects=SUBJECTS)

    await _press(session, bot, "cancel")

    assert session.active_subject is None
    markup = _last_edited(bot)["kwargs"]["reply_markup"]
    assert [row[0].text for row in markup.inline_keyboard] == ["Матан", "Физика"]
    assert bot.sent == [], "в беседу ничего не ушло"


async def test_finish_closes_pair_early(tmp_path):
    session, bot, _, store = build(tmp_path, subjects=SUBJECTS)
    await session.start("Матан")

    await _press(session, bot, "finish")

    assert session.active_subject is None
    assert store.load() is None, "состояние очищено"
    assert "закрыта" in _last_edited(bot)["text"], "ответ в личке"

    in_group = [item for item in bot.edited if item["chat_id"] == -100]
    assert in_group[-1]["text"].startswith("Матан — пара закрыта"), "итог в беседе"


async def test_finish_without_active_pair_is_polite(tmp_path):
    session, bot, _, _ = build(tmp_path, subjects=SUBJECTS)

    await _press(session, bot, "finish")

    assert session.active_subject is None
    assert bot.answers[-1]["text"] == "Пары сейчас нет"
    assert bot.answers[-1]["show_alert"] is True


async def test_stranger_cannot_open_a_pair(tmp_path):
    session, bot, _, _ = build(tmp_path, subjects=SUBJECTS)

    await _press(session, bot, "open:0", user_id=STRANGER)

    assert session.active_subject is None
    assert bot.answers[-1]["text"] == "Нет доступа"
    assert bot.sent == []


async def test_stranger_cannot_finish_a_pair(tmp_path):
    session, bot, _, _ = build(tmp_path, subjects=SUBJECTS)
    await session.start("Матан")

    await _press(session, bot, "finish", user_id=STRANGER)

    assert session.active_subject == "Матан", "чужой не может закрыть пару"


async def test_unknown_subject_index_is_rejected(tmp_path):
    session, bot, _, _ = build(tmp_path, subjects=SUBJECTS)

    await _press(session, bot, "subject:99")

    assert bot.answers[-1]["text"] == "Предмет не найден"
    assert session.active_subject is None
