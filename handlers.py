"""
Обработчики команд для обычных пользователей: /start, /stop, /suggest
"""

import logging
import os
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

import database as db

logger = logging.getLogger(__name__)
router = Router()


class SuggestStates(StatesGroup):
    waiting_for_content = State()


WELCOME_TEXT = """
🚃 <b>Бот мониторинга трамваев Тулы</b>

Я буду присылать вам актуальные уведомления о задержках, авариях и изменениях в работе трамваев города Тула.

<b>Команды:</b>
/start — подписаться на уведомления
/stop — отписаться от уведомлений
/suggest — предложить своё сообщение для публикации

Вы успешно подписались на уведомления! ✅
"""

ALREADY_SUBSCRIBED_TEXT = """
🚃 <b>Бот мониторинга трамваев Тулы</b>

Вы уже подписаны на уведомления.

<b>Команды:</b>
/stop — отписаться
/suggest — предложить сообщение для публикации
"""


@router.message(Command("start"))
async def cmd_start(message: Message):
    is_new = await db.add_subscriber(message.from_user.id)
    if is_new:
        await message.answer(WELCOME_TEXT, parse_mode="HTML")
        logger.info(f"Новый подписчик: {message.from_user.id}")
    else:
        await message.answer(ALREADY_SUBSCRIBED_TEXT, parse_mode="HTML")


@router.message(Command("stop"))
async def cmd_stop(message: Message):
    await db.remove_subscriber(message.from_user.id)
    await message.answer("Вы отписались от уведомлений. Чтобы снова подписаться — /start")
    logger.info(f"Пользователь отписался: {message.from_user.id}")


@router.message(Command("suggest"))
async def cmd_suggest(message: Message, state: FSMContext):
    user_id = message.from_user.id
    pending = await db.get_pending_post_by_user(user_id)
    if pending:
        await message.answer(
            "⏳ У вас уже есть сообщение на модерации. "
            "Дождитесь его рассмотрения перед отправкой нового."
        )
        return
    await state.set_state(SuggestStates.waiting_for_content)
    await message.answer(
        "📝 Отправьте текст сообщения (можно с фото).\n"
        "Для отмены напишите /cancel"
    )


@router.message(Command("cancel"), StateFilter(SuggestStates.waiting_for_content))
async def cmd_cancel_suggest(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.")


@router.message(StateFilter(SuggestStates.waiting_for_content))
async def receive_suggestion(message: Message, state: FSMContext):
    text = message.text or message.caption or ""
    photo_file_id = None
    if message.photo:
        photo_file_id = message.photo[-1].file_id

    if not text and not photo_file_id:
        await message.answer("Пожалуйста, отправьте текст или фото с подписью.")
        return

    post_id = await db.create_suggested_post(
        user_id=message.from_user.id,
        text=text,
        photo_file_id=photo_file_id
    )
    await state.clear()
    await message.answer("✅ Ваше сообщение отправлено на модерацию. Мы уведомим вас о результате.")
    logger.info(f"Новое предложение #{post_id} от пользователя {message.from_user.id}")

    from aiogram import Bot
    bot: Bot = message.bot
    admin_id = int(os.getenv("ADMIN_ID", "0"))
    if admin_id:
        await _notify_admin_about_suggestion(bot, admin_id, post_id, text, photo_file_id)


async def _notify_admin_about_suggestion(bot, admin_id: int, post_id: int, text: str, photo_file_id: str):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    caption = (
        f"📬 <b>Новое предложение поста #{post_id}</b>\n\n"
        f"{text or '(без текста)'}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"approve_post:{post_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_post:{post_id}"),
    ]])
    try:
        if photo_file_id:
            await bot.send_photo(admin_id, photo=photo_file_id, caption=caption,
                                 parse_mode="HTML", reply_markup=keyboard)
        else:
            await bot.send_message(admin_id, text=caption, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка при уведомлении администратора: {e}")
