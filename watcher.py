"""
Мониторинг каналов через Telethon userbot.
Читает сообщения из каналов-источников и рассылает уведомления подписчикам.
"""

import asyncio
import logging
from typing import Callable, Optional

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Message, MessageMediaPhoto

logger = logging.getLogger(__name__)


class ChannelWatcher:
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_string: str,
        get_keywords_fn: Callable,
        get_channels_fn: Callable,
        on_relevant_message_fn: Callable,
    ):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_string = session_string

        # Функции-колбэки для получения данных из БД и рассылки
        self.get_keywords = get_keywords_fn
        self.get_channels = get_channels_fn
        self.on_relevant_message = on_relevant_message_fn

        self.client: Optional[TelegramClient] = None
        # Множество каналов, на которые уже подписаны
        self._watched_channels: set[str] = set()

    async def start(self):
        """Запуск userbot и подписка на каналы."""
        self.client = TelegramClient(
            StringSession(self.session_string),
            self.api_id,
            self.api_hash
        )
        await self.client.start()
        logger.info("Telethon userbot запущен")

        # Подписка на события новых сообщений
        self.client.add_event_handler(
            self._handle_new_message,
            events.NewMessage()
        )

        # Начальная загрузка каналов из БД
        await self._refresh_channels()

        # Запуск фоновой задачи для динамического добавления каналов
        asyncio.create_task(self._channel_refresh_loop())

    async def _refresh_channels(self):
        """Обновить список отслеживаемых каналов из БД."""
        channels = await self.get_channels()
        new_channels = set(channels) - self._watched_channels
        if new_channels:
            logger.info(f"Добавлены новые каналы для мониторинга: {new_channels}")
        self._watched_channels = set(channels)

    async def _channel_refresh_loop(self):
        """Периодически проверяем появление новых каналов в БД."""
        while True:
            await asyncio.sleep(30)  # Проверка каждые 30 секунд
            try:
                await self._refresh_channels()
            except Exception as e:
                logger.error(f"Ошибка при обновлении списка каналов: {e}")

    async def _handle_new_message(self, event: events.NewMessage.Event):
        """Обработчик новых сообщений из всех чатов."""
        try:
            message: Message = event.message
            chat = await event.get_chat()

            # Определяем username канала
            channel_username = getattr(chat, "username", None)
            if not channel_username:
                return

            channel_key = f"@{channel_username}"

            # Проверяем, что канал в нашем списке
            if channel_key not in self._watched_channels:
                return

            text = message.message or ""
            if not text:
                return

            # Проверка на ключевые слова
            keywords = await self.get_keywords()
            text_lower = text.lower()
            if not any(kw in text_lower for kw in keywords):
                return

            logger.info(f"Релевантное сообщение из {channel_key}: {text[:80]}...")

            # Определяем наличие фото
            photo_file_id = None
            if isinstance(message.media, MessageMediaPhoto):
                # Для aiogram нам нужен file_id — скачаем через userbot и получим bytes,
                # но проще передать сам объект media для пересылки через userbot
                photo_file_id = "__telethon_photo__"  # Флаг для отправки через userbot

            # Вызываем колбэк рассылки
            await self.on_relevant_message(
                channel=channel_key,
                text=text,
                photo=message.media if photo_file_id else None,
                telethon_message=message
            )

        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения: {e}")

    async def send_message_to_user(self, user_id: int, text: str, photo=None) -> Optional[int]:
        """
        Отправить сообщение пользователю через userbot (используется для медиа).
        Возвращает message_id.
        """
        try:
            if photo:
                msg = await self.client.send_message(user_id, text, file=photo)
            else:
                msg = await self.client.send_message(user_id, text)
            return msg.id
        except Exception as e:
            logger.error(f"Ошибка при отправке через userbot пользователю {user_id}: {e}")
            return None

    async def run_until_disconnected(self):
        """Держать userbot активным."""
        await self.client.run_until_disconnected()
