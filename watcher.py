"""
Мониторинг каналов через публичные веб-страницы t.me/s/канал.
Защищен от бесконечных зависаний сети (Infinity Timeout).
"""

import asyncio
import logging
import re
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup
import database as db

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 45  # Интервал проверки каналов в секундах


class ChannelWatcher:
    def __init__(self, api_id, api_hash, session_string,
                 get_keywords_fn, get_channels_fn, on_relevant_message_fn):
        self.get_keywords = get_keywords_fn
        self.get_channels = get_channels_fn
        self.on_relevant_message = on_relevant_message_fn
        self._running = False

    async def start(self):
        self._running = True
        logger.info("Мониторинг каналов через t.me запущен")
        asyncio.create_task(self._monitoring_loop())

    async def _monitoring_loop(self):
        try:
            await self._check_all_channels(initial=True)
        except Exception as e:
            logger.error(f"Ошибка при начальной инициализации каналов: {e}", exc_info=True)

        logger.info("Начальное состояние обработано, запуск постоянного цикла мониторинга...")
        
        while self._running:
            await asyncio.sleep(CHECK_INTERVAL)
            try:
                await self._check_all_channels(initial=False)
            except Exception as e:
                logger.error(f"Критическая ошибка в итерации цикла мониторинга: {e}", exc_info=True)

    async def _check_all_channels(self, initial: bool = False):
        channels = await self.get_channels()
        keywords = await self.get_keywords()

        if not channels or not keywords:
            return

        keywords_lower = [kw.lower().strip() for kw in keywords if kw.strip()]

        # Устанавливаем жесткие лимиты на подключение (10 сек на коннект, 15 сек на чтение), 
        # чтобы запросы гарантированно не зависали навсегда при сетевых сбоях
        timeout_config = aiohttp.ClientTimeout(total=25, connect=10, sock_read=15)

        async with aiohttp.ClientSession(timeout=timeout_config) as session:
            for ch in channels:
                channel_key = ch["channel"]
                username = channel_key.replace("@", "").strip()
                url = f"https://t.me/s/{username}"

                try:
                    async with session.get(url) as response:
                        if response.status != 200:
                            logger.error(f"[{channel_key}] Ошибка парсинга: HTTP Status {response.status}")
                            continue
                        html = await response.text()
                except asyncio.TimeoutError:
                    logger.error(f"[{channel_key}] Превышено время ожидания ответа (Таймаут сети)")
                    continue
                except Exception as e:
                    logger.error(f"[{channel_key}] Ошибка запроса сети: {e}")
                    continue

                soup = BeautifulSoup(html, "html.parser")
                post_elements = soup.find_all("div", class_="tgme_widget_message_wrap")

                if not post_elements:
                    continue

                # При первом запуске берем последние 3 поста и полноценно проверяем их на ключи,
                # чтобы не пропускать важного из-за перезапуска бота
                elements_to_check = post_elements[-3:] if initial else post_elements

                for elem in elements_to_check:
                    msg_elem = elem.find("div", class_="tgme_widget_message")
                    if not msg_elem or not msg_elem.has_attr("data-post"):
                        continue

                    post_id = msg_elem["data-post"]

                    if await db.is_post_seen(post_id):
                        continue

                    text_elem = elem.find("div", class_="tgme_widget_message_text")
                    # Соединяем через пробел, чтобы внутренние теги Telegram не рвали слова
                    text = text_elem.get_text(separator=" ") if text_elem else ""

                    photo_url = None
                    photo_elem = elem.find("a", class_="tgme_widget_message_photo_wrap")
                    if photo_elem and photo_elem.has_attr("style"):
                        style = photo_elem["style"]
                        match = re.search(r"background-image:url\(['\"](.*?)['\"]\)", style)
                        if match:
                            photo_url = match.group(1)

                    await self._process_post(channel_key, post_id, text, keywords_lower, photo_url)
                    await db.mark_post_seen(post_id, channel_key)

    def _clean_text(self, text: str) -> str:
        stop_phrases = [
            "подписаться", "наш канал", "прислать новость",
            "тула. происшествия", "тг-канал"
        ]
        
        # Удаляем ссылки из текста, не ломая строки целиком
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"t\.me/\S+", "", text)
        text = re.sub(r"max\.ru/\S+", "", text)

        lines = text.split("\n")
        clean_lines = []
        for line in lines:
            line_lower = line.lower().strip()
            
            if any(phrase in line_lower for phrase in stop_phrases):
                continue
            
            line = re.sub(r"\s+", " ", line).strip()
            if line:
                clean_lines.append(line)
                
        return "\n".join(clean_lines).strip()

    async def _process_post(self, channel_key: str, post_id: str, text: str, keywords: list, photo_url: str = None):
        cleaned_text = self._clean_text(text) if text else ""
        if not cleaned_text and not photo_url:
            return

        # Убираем все разрывы строк исключительно ради точного поиска совпадений
        text_for_search = re.sub(r"\s+", " ", cleaned_text.lower()).strip()
        matched = [kw for kw in keywords if kw in text_for_search]

        if not matched:
            return

        logger.info(f"[{channel_key}] Пост {post_id}: ✅ Найдено совпадение по ключам: {matched}")

        await self.on_relevant_message(
            channel=channel_key,
            text=cleaned_text,
            photo=photo_url,
            telethon_message=None
        )

    async def run_until_disconnected(self):
        while self._running:
            await asyncio.sleep(1)

    def stop(self):
        self._running = False
        logger.info("Мониторинг каналов остановлен")