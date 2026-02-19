"""
Панель администратора.
"""

import logging
import os
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)

import database as db

logger = logging.getLogger(__name__)
router = Router()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))


class AdminStates(StatesGroup):
    adding_channel = State()
    removing_channel = State()
    adding_keyword = State()
    removing_keyword = State()
    creating_broadcast = State()


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📡 Каналы", callback_data="admin:channels"),
            InlineKeyboardButton(text="🔑 Ключевые слова", callback_data="admin:keywords"),
        ],
        [InlineKeyboardButton(text="📢 Создать уведомление", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="📋 История уведомлений", callback_data="admin:history:0")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
    ])


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🔧 <b>Панель администратора</b>",
                         reply_markup=main_menu_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer()
    subs = await db.get_subscribers_count()
    notifs = await db.get_notifications_24h_count()
    channels = await db.get_channels_count()
    pending = await db.get_pending_posts_count()
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Подписчиков: <b>{subs}</b>\n"
        f"📨 Уведомлений за 24 ч: <b>{notifs}</b>\n"
        f"📡 Каналов-источников: <b>{channels}</b>\n"
        f"⏳ На модерации: <b>{pending}</b>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="◀️ Назад", callback_data="admin:main")
        ]]),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin:main")
async def admin_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🔧 <b>Панель администратора</b>",
                                     reply_markup=main_menu_keyboard(), parse_mode="HTML")
    await callback.answer()


# ─── Каналы ──────────────────────────────────────────────────────────────────

def channels_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Список", callback_data="admin:channels:list"),
            InlineKeyboardButton(text="➕ Добавить", callback_data="admin:channels:add"),
            InlineKeyboardButton(text="➖ Удалить", callback_data="admin:channels:remove"),
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:main")],
    ])


@router.callback_query(F.data == "admin:channels")
async def admin_channels(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer()
    await callback.message.edit_text("📡 <b>Управление каналами</b>",
                                     reply_markup=channels_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:channels:list")
async def channels_list(callback: CallbackQuery):
    channels = await db.get_source_channels()
    text = ("📡 <b>Каналы-источники:</b>\n\n" + "\n".join(f"• {c}" for c in channels)
            if channels else "📡 Каналы ещё не добавлены.")
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="◀️ Назад", callback_data="admin:channels")
        ]]),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin:channels:add")
async def channels_add_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.adding_channel)
    await callback.message.edit_text("Введите username канала (например @tula_transport):\n\nДля отмены: /cancel")
    await callback.answer()


@router.callback_query(F.data == "admin:channels:remove")
async def channels_remove_prompt(callback: CallbackQuery, state: FSMContext):
    channels = await db.get_source_channels()
    if not channels:
        await callback.answer("Нет каналов для удаления.", show_alert=True)
        return
    await state.set_state(AdminStates.removing_channel)
    await callback.message.edit_text("Введите username канала для удаления:\n\n" + "\n".join(f"• {c}" for c in channels))
    await callback.answer()


# ─── Ключевые слова ───────────────────────────────────────────────────────────

def keywords_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Список", callback_data="admin:keywords:list"),
            InlineKeyboardButton(text="➕ Добавить", callback_data="admin:keywords:add"),
            InlineKeyboardButton(text="➖ Удалить", callback_data="admin:keywords:remove"),
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:main")],
    ])


@router.callback_query(F.data == "admin:keywords")
async def admin_keywords(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer()
    await callback.message.edit_text("🔑 <b>Управление ключевыми словами</b>",
                                     reply_markup=keywords_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:keywords:list")
async def keywords_list(callback: CallbackQuery):
    words = await db.get_keywords()
    text = ("🔑 <b>Ключевые слова:</b>\n\n" + "\n".join(f"• {w}" for w in words)
            if words else "🔑 Ключевые слова не заданы.")
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="◀️ Назад", callback_data="admin:keywords")
        ]]),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin:keywords:add")
async def keywords_add_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.adding_keyword)
    await callback.message.edit_text("Введите ключевое слово или фразу:\n\nДля отмены: /cancel")
    await callback.answer()


@router.callback_query(F.data == "admin:keywords:remove")
async def keywords_remove_prompt(callback: CallbackQuery, state: FSMContext):
    words = await db.get_keywords()
    if not words:
        await callback.answer("Нет слов для удаления.", show_alert=True)
        return
    await state.set_state(AdminStates.removing_keyword)
    await callback.message.edit_text("Введите слово для удаления:\n\n" + "\n".join(f"• {w}" for w in words))
    await callback.answer()


# ─── Рассылка ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_prompt(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer()
    await state.set_state(AdminStates.creating_broadcast)
    await callback.message.edit_text("📢 Отправьте текст уведомления (можно с фото).\n\nДля отмены: /cancel")
    await callback.answer()


# ─── История ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:history:"))
async def admin_history(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer()
    page = int(callback.data.split(":")[2])
    try:
        items = await db.get_notifications_history(offset=page * 10, limit=10)
    except Exception as e:
        logger.error(f"Ошибка загрузки истории: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)
        return
    if not items:
        await callback.answer("Нет уведомлений.", show_alert=True)
        return
    buttons = []
    for item in items:
        date_str = item["sent_at"].strftime("%d.%m %H:%M")
        source = item["source_channel"] or "вручную"
        preview = (item["text"] or "")[:50]
        label = f"[{date_str}] {source}: {preview}"
        buttons.append([
            InlineKeyboardButton(text=label[:60], callback_data=f"admin:notif_info:{item['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"admin:delete_notif:{item['id']}"),
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin:history:{page - 1}"))
    if len(items) == 10:
        nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"admin:history:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="🏠 Меню", callback_data="admin:main")])
    await callback.message.edit_text(
        f"📋 <b>История уведомлений</b> (стр. {page + 1})",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:delete_notif:"))
async def delete_notification(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        return await callback.answer()
    notif_id = int(callback.data.split(":")[2])
    records = await db.get_notifications_for_deletion(notif_id)
    if not records:
        await callback.answer("Записей не найдено.", show_alert=True)
        return
    deleted = 0
    notified = 0
    for rec in records:
        try:
            await bot.delete_message(rec["user_id"], rec["message_id_per_user"])
            deleted += 1
        except Exception:
            try:
                await bot.send_message(
                    rec["user_id"],
                    "⚠️ Предыдущее уведомление о трамваях было опубликовано ошибочно "
                    "и не является актуальным."
                )
                notified += 1
            except Exception:
                pass
    await db.delete_notification_records(notif_id)
    await callback.answer(f"✅ Удалено: {deleted}\n📩 Уведомлено об ошибке: {notified}", show_alert=True)


# ─── FSM-обработчики текстовых сообщений ─────────────────────────────────────

@router.message(AdminStates.adding_channel)
async def process_add_channel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu_keyboard())
        return
    channel = message.text.strip()
    if not channel.startswith("@"):
        channel = "@" + channel
    added = await db.add_source_channel(channel)
    await message.answer(
        f"✅ Канал {channel} добавлен." if added else f"⚠️ Канал {channel} уже существует.",
        reply_markup=main_menu_keyboard()
    )
    await state.clear()


@router.message(AdminStates.removing_channel)
async def process_remove_channel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu_keyboard())
        return
    channel = message.text.strip()
    if not channel.startswith("@"):
        channel = "@" + channel
    removed = await db.remove_source_channel(channel)
    await message.answer(
        f"✅ Канал {channel} удалён." if removed else f"⚠️ Канал {channel} не найден.",
        reply_markup=main_menu_keyboard()
    )
    await state.clear()


@router.message(AdminStates.adding_keyword)
async def process_add_keyword(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu_keyboard())
        return
    word = message.text.strip().lower()
    added = await db.add_keyword(word)
    await message.answer(
        f"✅ Слово «{word}» добавлено." if added else f"⚠️ Слово «{word}» уже есть.",
        reply_markup=main_menu_keyboard()
    )
    await state.clear()


@router.message(AdminStates.removing_keyword)
async def process_remove_keyword(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu_keyboard())
        return
    word = message.text.strip().lower()
    removed = await db.remove_keyword(word)
    await message.answer(
        f"✅ Слово «{word}» удалено." if removed else f"⚠️ Слово «{word}» не найдено.",
        reply_markup=main_menu_keyboard()
    )
    await state.clear()


@router.message(AdminStates.creating_broadcast)
async def process_broadcast(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    # Если администратор ввёл команду — не отправлять как уведомление
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu_keyboard())
        return
    text = message.text or message.caption or ""
    photo_file_id = message.photo[-1].file_id if message.photo else None
    notification_text = f"🚃 <b>Уведомление о трамваях Тулы</b>\n\nИсточник: администратор\n\n{text}"
    subscribers = await db.get_all_subscribers()
    sent_count = 0
    for user_id in subscribers:
        try:
            if photo_file_id:
                msg = await bot.send_photo(user_id, photo=photo_file_id,
                                           caption=notification_text, parse_mode="HTML")
            else:
                msg = await bot.send_message(user_id, text=notification_text, parse_mode="HTML")
            await db.save_notification(user_id=user_id, message_id=msg.message_id,
                                       text=notification_text, source_channel="admin",
                                       photo_file_id=photo_file_id)
            sent_count += 1
        except Exception as e:
            if "blocked" in str(e).lower():
                await db.remove_subscriber(user_id)
    await state.clear()
    await message.answer(f"✅ Разослано {sent_count} подписчикам.", reply_markup=main_menu_keyboard())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    kb = main_menu_keyboard() if is_admin(message.from_user.id) else None
    await message.answer("Отменено.", reply_markup=kb)
