"""
Главный файл запуска.
Запускает aiogram-бота и Telethon userbot параллельно через asyncio.
Все файлы лежат в корне репозитория (плоская структура).
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from dotenv import load_dotenv

import database as db
from handlers import router as user_router
from admin import router as admin_router
from moderation import router as moderation_router
from watcher import ChannelWatcher

# Загружаем переменные окружения из .env (для локальной разработки)
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
TELETHON_API_ID = 0
TELETHON_API_HASH = ""
TELETHON_SESSION = ""
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")


async def broadcast_relevant_message(
    bot: Bot,
    channel: str,
    text: str,
    photo=None,
    photo_url: str = None,
    telethon_message=None,
    watcher: ChannelWatcher = None
):
    """
    Рассылка релевантного сообщения из канала всем подписчикам.
    """
    subscribers = await db.get_all_subscribers()
    notification_text = (
        f"🚃 <b>Уведомление о трамваях Тулы</b>\n\n"
        f"Источник: {channel}\n\n"
        f"{text}"
    )

    for user_id in subscribers:
        try:
            msg = await bot.send_message(
                user_id,
                text=notification_text,
                parse_mode=ParseMode.HTML
            )
            await db.save_notification(
                user_id=user_id,
                message_id=msg.message_id,
                text=notification_text,
                source_channel=channel
            )
        except Exception as e:
            err_str = str(e).lower()
            if "blocked" in err_str or "user is deactivated" in err_str or "bot was blocked" in err_str:
                await db.remove_subscriber(user_id)
                logger.info(f"Удалён подписчик {user_id} — бот заблокирован")
            else:
                logger.error(f"Ошибка при рассылке пользователю {user_id}: {e}")


async def main():
    """Точка входа: инициализация БД, запуск бота и userbot."""
    if not all([BOT_TOKEN, DATABASE_URL]):
        logger.error("Не заданы обязательные переменные окружения!")
        return

    logger.info("Подключение к базе данных...")
    await db.init_db(DATABASE_URL)
    await db.fix_channel_urls()  # Исправляем каналы, добавленные как полные ссылки
    await db.init_seen_posts_table()  # Таблица для дедупликации постов

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(admin_router)
    dp.include_router(moderation_router)
    dp.include_router(user_router)

    watcher = ChannelWatcher(
        api_id=TELETHON_API_ID,
        api_hash=TELETHON_API_HASH,
        session_string=TELETHON_SESSION,
        get_keywords_fn=db.get_keywords,
        get_channels_fn=db.get_source_channels,
        on_relevant_message_fn=lambda **kwargs: broadcast_relevant_message(
            bot=bot,
            watcher=watcher,
            **kwargs
        )
    )

    logger.info("Запуск Telethon userbot...")
    for attempt in range(10):
        try:
            await watcher.start()
            break
        except Exception as e:
            if "AuthKeyDuplicated" in str(e) or "auth key" in str(e).lower():
                wait = 10 * (attempt + 1)
                logger.warning(f"Сессия занята, ожидаем {wait} сек (попытка {attempt + 1}/10)...")
                await asyncio.sleep(wait)
            else:
                raise
    else:
        logger.error("Не удалось запустить userbot после 10 попыток")
        return

    # Устанавливаем команды бота в меню Telegram (без смайлика)
    await bot.set_my_commands([
        BotCommand(command="start", description="Подписаться на уведомления"),
        BotCommand(command="stop", description="Отписаться от уведомлений"),
        BotCommand(command="routes", description="Список маршрутов Тулы"),
        BotCommand(command="suggest", description="Предложить сообщение для публикации"),
    ])
    logger.info("Команды бота установлены")
    logger.info("Запуск aiogram бота...")
    
    await asyncio.gather(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        watcher.run_until_disconnected()
    )


if __name__ == "__main__":
    asyncio.run(main())