"""
Мониторинг каналов через Telethon userbot.
Один глобальный обработчик, список каналов обновляется динамически.
"""

import asyncio
import logging
from typing import Optional

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto

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
        self._channel_ids: dict[int, str] = {}

    async def start(self):
        self.client = TelegramClient(
            StringSession(self.session_string), self.api_id, self.api_hash
        )
        await self.client.start()
        logger.info("Telethon userbot запущен")

        await self._refresh_channels()

        # Важно: загружаем диалоги чтобы активировать получение событий из каналов
        logger.info("Загрузка диалогов...")
        try:
            async for _ in self.client.iter_dialogs():
                pass
            logger.info("Диалоги загружены")
        except Exception as e:
            logger.error(f"Ошибка загрузки диалогов: {e}")

        self.client.add_event_handler(
            self._handle_new_message,
            events.NewMessage(incoming=True)
        )

        logger.info(f"Слушаем {len(self._channel_ids)} каналов: {list(self._channel_ids.values())}")
        asyncio.create_task(self._channel_refresh_loop())

    async def _refresh_channels(self):
        channels = await self.get_channels()
        known_usernames = set(self._channel_ids.values())
        for channel in channels:
            if channel in known_usernames:
                continue
            try:
                entity = await self.client.get_entity(channel)
                self._channel_ids[entity.id] = channel
                logger.info(f"✅ Добавлен канал: {channel} (id={entity.id})")
            except Exception as e:
                logger.error(f"❌ Канал недоступен {channel}: {e}")

    async def _channel_refresh_loop(self):
        while True:
            await asyncio.sleep(60)
            try:
                await self._refresh_channels()
            except Exception as e:
                logger.error(f"Ошибка обновления каналов: {e}")

    async def _handle_new_message(self, event: events.NewMessage.Event):
        try:
            peer_id = getattr(event.message.peer_id, 'channel_id', None)
            if peer_id is None or peer_id not in self._channel_ids:
                return

            channel_key = self._channel_ids[peer_id]
            text = event.message.message or ""

            logger.info(f"[{channel_key}] Сообщение: {text[:120]!r}")

            if not text:
                return

            keywords = await self.get_keywords()
            text_lower = text.lower()
            matched = [kw for kw in keywords if kw in text_lower]

            if not matched:
                logger.info(f"[{channel_key}] Ключевые слова не найдены")
                return

            logger.info(f"[{channel_key}] ✅ Совпадение: {matched}")

            photo = event.message.media if isinstance(event.message.media, MessageMediaPhoto) else None

            await self.on_relevant_message(
                channel=channel_key,
                text=text,
                photo=photo,
                telethon_message=event.message
            )
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}", exc_info=True)

    async def send_message_to_user(self, user_id: int, text: str, photo=None) -> Optional[int]:
        try:
            if photo:
                msg = await self.client.send_message(user_id, text, file=photo)
            else:
                msg = await self.client.send_message(user_id, text)
            return msg.id
        except Exception as e:
            logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
            return None

    async def run_until_disconnected(self):
        await self.client.run_until_disconnected()
