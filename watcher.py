"""
Мониторинг каналов через Telethon userbot.
"""

import asyncio
import logging
from typing import Callable, Optional

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Message, MessageMediaPhoto

logger = logging.getLogger(__name__)


class ChannelWatcher:
    def __init__(self, api_id, api_hash, session_string,
                 get_keywords_fn, get_channels_fn, on_relevant_message_fn):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_string = session_string
        self.get_keywords = get_keywords_fn
        self.get_channels = get_channels_fn
        self.on_relevant_message = on_relevant_message_fn
        self.client: Optional[TelegramClient] = None
        self._watched_channels: set = set()

    async def start(self):
        self.client = TelegramClient(
            StringSession(self.session_string), self.api_id, self.api_hash
        )
        await self.client.start()
        logger.info("Telethon userbot запущен")
        self.client.add_event_handler(self._handle_new_message, events.NewMessage())
        await self._refresh_channels()
        asyncio.create_task(self._channel_refresh_loop())

    async def _refresh_channels(self):
        channels = await self.get_channels()
        new_channels = set(channels) - self._watched_channels
        if new_channels:
            logger.info(f"Новые каналы для мониторинга: {new_channels}")
        self._watched_channels = set(channels)

    async def _channel_refresh_loop(self):
        while True:
            await asyncio.sleep(30)
            try:
                await self._refresh_channels()
            except Exception as e:
                logger.error(f"Ошибка при обновлении каналов: {e}")

    async def _handle_new_message(self, event: events.NewMessage.Event):
        try:
            message: Message = event.message
            chat = await event.get_chat()
            channel_username = getattr(chat, "username", None)
            if not channel_username:
                return
            channel_key = f"@{channel_username}"
            if channel_key not in self._watched_channels:
                return
            text = message.message or ""
            if not text:
                return
            keywords = await self.get_keywords()
            text_lower = text.lower()
            if not any(kw in text_lower for kw in keywords):
                return
            logger.info(f"Релевантное сообщение из {channel_key}: {text[:80]}...")
            photo = message.media if isinstance(message.media, MessageMediaPhoto) else None
            await self.on_relevant_message(
                channel=channel_key,
                text=text,
                photo=photo,
                telethon_message=message
            )
        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения: {e}")

    async def send_message_to_user(self, user_id: int, text: str, photo=None) -> Optional[int]:
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
        await self.client.run_until_disconnected()
