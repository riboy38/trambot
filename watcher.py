"""
Мониторинг каналов через RSS (без Telethon userbot).
Использует публичные RSS-ленты Telegram каналов через rsshub.app
"""

import asyncio
import logging
import hashlib
import xml.etree.ElementTree as ET
from typing import Callable, Optional
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)

# Интервал проверки каналов в секундах
CHECK_INTERVAL = 30

# RSS источники (пробуем несколько на случай недоступности)
RSS_TEMPLATES = [
    "https://tgstat.ru/channel/@{channel}/rss",
    "https://rsshub.app/telegram/channel/{channel}",
    "https://rss.app/feeds/telegram/{channel}.xml",
]


class ChannelWatcher:
    def __init__(self, api_id, api_hash, session_string,
                 get_keywords_fn, get_channels_fn, on_relevant_message_fn):
        # api_id, api_hash, session_string оставлены для совместимости, но не используются
        self.get_keywords = get_keywords_fn
        self.get_channels = get_channels_fn
        self.on_relevant_message = on_relevant_message_fn
        # Храним хэши уже обработанных постов чтобы не дублировать
        self._seen_posts: set[str] = set()
        self._running = False

    async def start(self):
        """Запуск мониторинга."""
        self._running = True
        logger.info("RSS-мониторинг каналов запущен")
        # Запускаем фоновую задачу проверки
        asyncio.create_task(self._monitoring_loop())

    async def _monitoring_loop(self):
        """Основной цикл проверки каналов."""
        # Первый прогон — просто запоминаем существующие посты без рассылки
        await self._check_all_channels(initial=True)
        logger.info("Начальное состояние каналов загружено, начинаем мониторинг новых постов")

        while self._running:
            await asyncio.sleep(CHECK_INTERVAL)
            try:
                await self._check_all_channels(initial=False)
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}")

    async def _check_all_channels(self, initial: bool = False):
        """Проверить все каналы из БД."""
        channels = await self.get_channels()
        keywords = await self.get_keywords()

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ) as session:
            for channel in channels:
                # Убираем @ из имени канала
                channel_name = channel.lstrip("@")
                try:
                    await self._check_channel(
                        session, channel, channel_name, keywords, initial
                    )
                except Exception as e:
                    logger.error(f"Ошибка проверки канала {channel}: {e}")

    async def _check_channel(
        self, session, channel_key: str, channel_name: str,
        keywords: list, initial: bool
    ):
        """Проверить один канал через RSS."""
        # Пробуем разные RSS источники
        feed_text = None
        for template in RSS_TEMPLATES:
            url = template.format(channel=channel_name)
            try:
                async with session.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; TramBot/1.0)"
                }) as resp:
                    if resp.status == 200:
                        feed_text = await resp.text()
                        break
            except Exception:
                continue

        if not feed_text:
            logger.warning(f"Не удалось получить RSS для {channel_key}")
            return

        # Парсим RSS
        try:
            root = ET.fromstring(feed_text)
        except ET.ParseError as e:
            logger.error(f"Ошибка парсинга RSS {channel_key}: {e}")
            return

        # Ищем элементы item (RSS) или entry (Atom)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//item") or root.findall(".//atom:entry", ns)

        for item in items:
            # Получаем текст поста
            title = item.findtext("title") or item.findtext("atom:title", namespaces=ns) or ""
            description = item.findtext("description") or item.findtext("atom:summary", namespaces=ns) or ""
            link = item.findtext("link") or item.findtext("atom:link", namespaces=ns) or ""
            guid = item.findtext("guid") or link or title

            # Уникальный хэш поста
            post_hash = hashlib.md5(guid.encode()).hexdigest()

            if initial:
                # При старте только запоминаем, не рассылаем
                self._seen_posts.add(post_hash)
                continue

            if post_hash in self._seen_posts:
                continue

            self._seen_posts.add(post_hash)

            # Полный текст = заголовок + описание
            full_text = f"{title}\n{description}".strip()
            # Убираем HTML теги
            import re
            clean_text = re.sub(r"<[^>]+>", "", full_text).strip()

            if not clean_text:
                continue

            logger.info(f"[{channel_key}] Новый пост: {clean_text[:120]!r}")

            # Проверяем ключевые слова
            text_lower = clean_text.lower()
            matched = [kw for kw in keywords if kw in text_lower]

            if not matched:
                logger.info(f"[{channel_key}] Ключевые слова не найдены")
                continue

            logger.info(f"[{channel_key}] ✅ Совпадение: {matched}")

            await self.on_relevant_message(
                channel=channel_key,
                text=clean_text,
                photo=None,
                telethon_message=None
            )

    async def send_message_to_user(self, user_id: int, text: str, photo=None) -> Optional[int]:
        """Заглушка — в RSS-режиме медиа не пересылаем."""
        return None

    async def run_until_disconnected(self):
        """Держим процесс живым."""
        while self._running:
            await asyncio.sleep(3600)
