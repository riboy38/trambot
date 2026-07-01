"""
Обработчики команд для обычных пользователей: /start, /stop, /suggest
Доступ к боту только для подписчиков канала @tulaurban.
"""

import logging
import os
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
# ВСЕ ИМПОРТЫ ДЛЯ КЛАВИАТУР ТЕПЕРЬ НА МЕСТЕ:
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

import database as db

logger = logging.getLogger(__name__)
router = Router()

REQUIRED_CHANNEL = "@tulaurban"
REQUIRED_CHANNEL_URL = "https://t.me/tulaurban"


class SuggestStates(StatesGroup):
    waiting_for_content = State()


def subscription_required_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url=REQUIRED_CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")],
    ])


async def check_channel_subscription(bot: Bot, user_id: int) -> bool:
    """Проверяет подписку пользователя на обязательный канал."""
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.warning(f"Не удалось проверить подписку {user_id}: {e}")
        return True
    except Exception as e:
        logger.error(f"Ошибка проверки подписки {user_id}: {e}")
        return True


WELCOME_TEXT = """
🚃 <b>Бот мониторинга трамваев Тулы</b>

Я буду присылать вам актуальные уведомления о задержках, авариях и изменениях в работе трамваев города Тула.

<b>Команды:</b>
/start — подписаться на уведомления
/stop — отписаться от уведомлений
/routes — список маршрутов Тулы 🚧
/suggest — предложить своё сообщение для публикации

Вы успешно подписались на уведомления! ✅
"""

ALREADY_SUBSCRIBED_TEXT = """
🚃 <b>Бот мониторинга трамваев Тулы</b>

Вы уже подписаны на уведомления.

<b>Команды:</b>
/stop — отписаться
/routes — список маршрутов Тулы 🚧
/suggest — предложить сообщение для публикации
"""


@router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot):
    if not await check_channel_subscription(bot, message.from_user.id):
        await send_subscribe_prompt(message)
        return
    is_new = await db.add_subscriber(message.from_user.id)
    if is_new:
        await message.answer(WELCOME_TEXT, parse_mode="HTML")
        logger.info(f"Новый подписчик: {message.from_user.id}")
    else:
        await message.answer(ALREADY_SUBSCRIBED_TEXT, parse_mode="HTML")


@router.message(Command("stop"))
async def cmd_stop(message: Message, bot: Bot):
    if not await check_channel_subscription(bot, message.from_user.id):
        await send_subscribe_prompt(message)
        return
    await db.remove_subscriber(message.from_user.id)
    await message.answer("Вы отписались от уведомлений. Чтобы снова подписаться — /start")
    logger.info(f"Пользователь отписался: {message.from_user.id}")


@router.message(Command("suggest"))
async def cmd_suggest(message: Message, state: FSMContext, bot: Bot):
    if not await check_channel_subscription(bot, message.from_user.id):
        await send_subscribe_prompt(message)
        return
    user_id = message.from_user.id
    pending = await db.get_pending_post_by_user(user_id)
    if pending:
        await message.answer(
            "⏳ У вас уже есть сообщение на модерации. "
            "Дождитесь его рассмотрения перед отправкой нового."
        )
        return
    await state.set_state(SuggestStates.waiting_for_content)
    await message.answer("📝 Отправьте текст сообщения (можно с фото).\nДля отмены напишите /cancel")


@router.message(Command("cancel"), StateFilter(SuggestStates.waiting_for_content))
async def cmd_cancel_suggest(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.")


@router.message(StateFilter(SuggestStates.waiting_for_content))
async def receive_suggestion(message: Message, state: FSMContext, bot: Bot):
    if not await check_channel_subscription(bot, message.from_user.id):
        await state.clear()
        await send_subscribe_prompt(message)
        return
    text = message.text or message.caption or ""
    photo_file_id = message.photo[-1].file_id if message.photo else None
    if not text and not photo_file_id:
        await message.answer("Пожалуйста, отправьте текст или фото с подписью.")
        return
    post_id = await db.create_suggested_post(
        user_id=message.from_user.id, text=text, photo_file_id=photo_file_id
    )
    await state.clear()
    await message.answer("✅ Ваше сообщение отправлено на модерацию. Мы уведомим вас о результате.")
    logger.info(f"Новое предложение #{post_id} от пользователя {message.from_user.id}")
    admin_id = int(os.getenv("ADMIN_ID", "0"))
    if admin_id:
        await _notify_admin_about_suggestion(bot, admin_id, post_id, text, photo_file_id)


@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery, bot: Bot):
    """Проверка подписки после нажатия кнопки 'Я подписался'."""
    user_id = callback.from_user.id
    if not await check_channel_subscription(bot, user_id):
        await callback.answer(
            "❌ Вы ещё не подписались на канал. Подпишитесь и попробуйте снова.",
            show_alert=True
        )
        return
    is_new = await db.add_subscriber(user_id)
    await callback.message.edit_text(
        WELCOME_TEXT if is_new else ALREADY_SUBSCRIBED_TEXT,
        parse_mode="HTML"
    )
    await callback.answer()
    logger.info(f"Подписка подтверждена для пользователя {user_id}")


async def _notify_admin_about_suggestion(bot: Bot, admin_id: int, post_id: int, text: str, photo_file_id: str):
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


async def send_subscribe_prompt(message: Message):
    await message.answer(
        f"🔒 Для использования бота необходимо подписаться на канал {REQUIRED_CHANNEL}\n\n"
        f"После подписки нажмите кнопку <b>«✅ Я подписался»</b>.",
        reply_markup=subscription_required_keyboard(),
        parse_mode="HTML"
    )


# ─── Меню маршрутов для пользователей ────────────────────────────────────────

def route_sort_key(route: dict) -> tuple:
    """
    Ключ сортировки для номеров маршрутов:
    1. Сначала идут числовые (включая со слэшем '/') по первому числу.
    2. В самом конце идут чисто текстовые маршруты.
    """
    num_str = route['route_number'].strip()
    
    # Если маршрут содержит слэш (например, 1/12, 9/10)
    if '/' in num_str:
        first_part = num_str.split('/')[0].strip()
        if first_part.isdigit():
            return (0, int(first_part), num_str)
            
    # Если это просто чистое число (например, 3, 6, 11)
    if num_str.isdigit():
        return (0, int(num_str), num_str)
        
    # Если это текст — отправляем в самый конец
    return (1, 0, num_str)


async def build_user_routes_keyboard() -> InlineKeyboardMarkup:
    routes = await db.get_all_routes()
    
    # Сортируем список маршрутов по правилу
    sorted_routes = sorted(routes, key=route_sort_key)
    
    buttons = []
    row = []
    for r in sorted_routes:
        # Убрали слово "Трамвай", оставляем только чистый номер (например, "№ 3" или "№ Челнок")
        button_text = f"№ {r['route_number']}"
        row.append(InlineKeyboardButton(text=button_text, callback_data=f"user:route_info:{r['route_number']}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("routes"))
async def cmd_user_routes(message: Message, bot: Bot):
    if not await check_channel_subscription(bot, message.from_user.id):
        await send_subscribe_prompt(message)
        return
    
    keyboard = await build_user_routes_keyboard()
    if not keyboard.inline_keyboard:
        await message.answer("🚧 На данный момент список маршрутов пуст.")
        return

    # Изменили текст заголовка
    await message.answer(
        "🚧 <b>Список трамвайных маршрутов Тулы</b>\n\n"
        "Выберите интересующий вас номер ниже, чтобы узнать его актуальный путь следования:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("user:route_info:"))
async def user_route_info_callback(callback: CallbackQuery, bot: Bot):
    route_num = callback.data.split(":")[2]
    route_data = await db.get_route(route_num)
    
    if not route_data:
        await callback.answer("Информация об этом маршруте уже не актуальна.", show_alert=True)
        return

    caption = f"🚃 <b>Маршрут № {route_data['route_number']}</b>\n\n{route_data['description']}"
    
    try:
        await callback.message.delete()
    except Exception:
        pass

    back_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Назад к списку", callback_data="user:routes:back")
    ]])

    if route_data['photo_file_id']:
        await bot.send_photo(
            chat_id=callback.from_user.id,
            photo=route_data['photo_file_id'],
            caption=caption,
            reply_markup=back_kb,
            parse_mode="HTML"
        )
    else:
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=caption,
            reply_markup=back_kb,
            parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data == "user:routes:back")
async def user_routes_back(callback: CallbackQuery, bot: Bot):
    try:
        await callback.message.delete()
    except Exception:
        pass
        
    keyboard = await build_user_routes_keyboard()
    # Текст при возврате назад
    await bot.send_message(
        chat_id=callback.from_user.id,
        text="🚧 <b>Список трамвайных маршрутов Тулы</b>\n\nВыберите номер:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()