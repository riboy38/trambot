"""
Мониторинг каналов через публичные веб-страницы t.me/s/канал.
Не требует авторизации и работает без Telethon.
"""

import asyncio
import logging
import hashlib
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30


class ChannelWatcher:
    def __init__(self, api_id, api_hash, session_string,
                 get_keywords_fn, get_channels_fn, on_relevant_message_fn):
        self.get_keywords = get_keywords_fn
        self.get_channels = get_channels_fn
        self.on_relevant_message = on_relevant_message_fn
        self._seen_posts: set[str] = set()
        self._running = False

    async def start(self):
        self._running = True
        logger.info("Мониторинг каналов через t.me запущен")
        asyncio.create_task(self._monitoring_loop())

    async def _monitoring_loop(self):
        await self._check_all_channels(initial=True)
        logger.info("Начальное состояние загружено, начинаем мониторинг новых постов")
        while self._running:
            await asyncio.sleep(CHECK_INTERVAL)
            try:
                await self._check_all_channels(initial=False)
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}")

    async def _check_all_channels(self, initial: bool = False):
        channels = await self.get_channels()
        keywords = await self.get_keywords()
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
        ) as session:
            for channel in channels:
                try:
                    await self._check_channel(session, channel, keywords, initial)
                except Exception as e:
                    logger.error(f"Ошибка проверки {channel}: {e}")

    async def _check_channel(self, session, channel_key: str, keywords: list, initial: bool):
        channel_name = channel_key.lstrip("@")
        url = f"https://t.me/s/{channel_name}"

        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"[{channel_key}] t.me вернул статус {resp.status}")
                    return
                html = await resp.text()
        except Exception as e:
            logger.error(f"[{channel_key}] Ошибка запроса: {e}")
            return

        soup = BeautifulSoup(html, "html.parser")

        # Ищем все сообщения с их ID
        messages = soup.find_all("div", class_=lambda c: c and "tgme_widget_message " in c)

        if not messages:
            # Запасной вариант — ищем просто по тексту
            messages = soup.find_all("div", class_="tgme_widget_message_text")
            for msg in messages:
                text = msg.get_text(separator="\n").strip()
                if not text:
                    continue
                post_id = hashlib.md5(f"{channel_key}{text[:50]}".encode()).hexdigest()
                if initial:
                    self._seen_posts.add(post_id)
                    continue
                if post_id in self._seen_posts:
                    continue
                self._seen_posts.add(post_id)
                await self._process_post(channel_key, post_id, text, keywords)
            return

        for msg_div in messages:
            # Получаем ID поста из атрибута data-post
            data_post = msg_div.get("data-post", "")
            post_id = data_post if data_post else hashlib.md5(
                f"{channel_key}{msg_div.get_text()[:50]}".encode()
            ).hexdigest()

            if initial:
                self._seen_posts.add(post_id)
                continue

            if post_id in self._seen_posts:
                continue

            self._seen_posts.add(post_id)

            text_div = msg_div.find("div", class_="tgme_widget_message_text")
            text = text_div.get_text(separator="\n").strip() if text_div else ""

            if not text:
                continue

            await self._process_post(channel_key, post_id, text, keywords)

    async def _process_post(self, channel_key: str, post_id: str, text: str, keywords: list):
        logger.info(f"[{channel_key}] Новый пост [{post_id}]: {text[:120]!r}")

        text_lower = text.lower()
        matched = [kw for kw in keywords if kw in text_lower]

        if not matched:
            logger.info(f"[{channel_key}] Ключевые слова не найдены")
            return

        logger.info(f"[{channel_key}] ✅ Совпадение: {matched}")

        await self.on_relevant_message(
            channel=channel_key,
            text=text,
            photo=None,
            telethon_message=None
        )

    async def send_message_to_user(self, user_id: int, text: str, photo=None) -> Optional[int]:
        return None

    async def run_until_disconnected(self):
        while self._running:
            await asyncio.sleep(3600)
