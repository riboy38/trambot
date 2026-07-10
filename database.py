"""
Модуль для работы с базой данных PostgreSQL через asyncpg.
Содержит все запросы к БД. Защищен от внезапных разрывов соединений.
"""

import asyncio
import asyncpg
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Глобальный пул соединений
pool: Optional[asyncpg.Pool] = None


async def init_db(database_url: str):
    """Инициализация пула соединений и создание таблиц."""
    global pool
    pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
    await create_tables()
    await seed_keywords()
    await init_seen_posts_table()
    logger.info("База данных инициализирована")


async def create_tables():
    """Создание таблиц если их нет."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                user_id BIGINT PRIMARY KEY,
                subscribed_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS keywords (
                id SERIAL PRIMARY KEY,
                word TEXT UNIQUE NOT NULL
            );

            CREATE TABLE IF NOT EXISTS source_channels (
                id SERIAL PRIMARY KEY,
                channel TEXT UNIQUE NOT NULL,
                added_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS sent_notifications (
                id SERIAL PRIMARY KEY,
                source_channel TEXT,
                message_id_per_user BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                sent_at TIMESTAMPTZ DEFAULT NOW(),
                text TEXT,
                photo_file_id TEXT
            );

            CREATE TABLE IF NOT EXISTS suggested_posts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                text TEXT,
                photo_file_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)


async def seed_keywords():
    """Первоначальное заполнение базовых ключевых слов, если таблица пуста."""
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM keywords")
        if count == 0:
            base_keywords = [
                "трамвай", "трамваи", "трамваев", "трамвая", "трамваям",
                "вагон", "рельс", "рельсы", "рельсов", "сход", "сошел",
                "ул. марата", "ул. епифанская", "пролетарск", "криволуч",
                "менделеев", "станиславск", "оборонн", "красноармейск",
                "советск", "коминтерн", "луначарск", "октябрьск",
                "задержк", "задержив", "остановл", "встали", "стоят",
                "движение рельсового", "двухпутно", "однопутно"
            ]
            for kw in base_keywords:
                await conn.execute(
                    "INSERT INTO keywords (word) VALUES ($1) ON CONFLICT DO NOTHING", kw
                )
            logger.info(f"Добавлено {len(base_keywords)} начальных ключевых слов")
        else:
            logger.info(f"Установлено {count} ключевых слов")


async def get_source_channels():
    """Получить список целевых каналов с защитой от разрыва соединения."""
    for attempt in range(2):
        try:
            async with pool.acquire() as conn:
                return await conn.fetch("SELECT channel FROM source_channels")
        except asyncpg.exceptions.ConnectionDoesNotExistError:
            if attempt == 0:
                logger.warning("Соединение с БД было закрыто сервером. Повторная попытка...")
                await asyncio.sleep(1)
            else:
                raise
        except Exception as e:
            if "connection was closed" in str(e).lower() and attempt == 0:
                logger.warning("Обнаружен разрыв соединения с PostgreSQL. Переподключение...")
                await asyncio.sleep(1)
            else:
                raise


async def get_keywords():
    """Получить список ключевых слов с защитой от разрыва соединения."""
    for attempt in range(2):
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT word FROM keywords")
                return [row["word"] for row in rows]
        except asyncpg.exceptions.ConnectionDoesNotExistError:
            if attempt == 0:
                logger.warning("Соединение с БД для ключевых слов закрыто. Повторная попытка...")
                await asyncio.sleep(1)
            else:
                raise
        except Exception as e:
            if "connection was closed" in str(e).lower() and attempt == 0:
                logger.warning("Обнаружен разрыв соединения при запросе ключевых слов. Переподключение...")
                await asyncio.sleep(1)
            else:
                raise


async def add_channel(channel: str) -> bool:
    """Добавить канал в список мониторинга."""
    async with pool.acquire() as conn:
        try:
            await conn.execute("INSERT INTO source_channels (channel) VALUES ($1)", channel)
            return True
        except asyncpg.exceptions.UniqueViolationError:
            return False


async def remove_channel(channel: str) -> bool:
    """Удалить канал из списка мониторинга."""
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM source_channels WHERE channel = $1", channel)
        return "DELETE 1" in res


async def add_keyword(word: str) -> bool:
    """Добавить ключевое слово."""
    async with pool.acquire() as conn:
        try:
            await conn.execute("INSERT INTO keywords (word) VALUES ($1)", word.lower().strip())
            return True
        except asyncpg.exceptions.UniqueViolationError:
            return False


async def remove_keyword(word: str) -> bool:
    """Удалить ключевое слово."""
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM keywords WHERE word = $1", word.lower().strip())
        return "DELETE 1" in res


async def add_subscriber(user_id: int) -> bool:
    """Добавить пользователя в базу подписчиков рассылки."""
    async with pool.acquire() as conn:
        try:
            await conn.execute("INSERT INTO subscribers (user_id) VALUES ($1)", user_id)
            return True
        except asyncpg.exceptions.UniqueViolationError:
            return False


async def remove_subscriber(user_id: int) -> bool:
    """Удалить пользователя из подписчиков."""
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM subscribers WHERE user_id = $1", user_id)
        return "DELETE 1" in res


async def is_subscribed(user_id: int) -> bool:
    """Проверить, подписан ли пользователь."""
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT 1 FROM subscribers WHERE user_id = $1", user_id)
        return val is not None


async def get_all_subscribers():
    """Получить список всех ID подписчиков."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM subscribers")
        return [row["user_id"] for row in rows]


async def get_stats() -> dict:
    """Получить общую статистику для админ-панели."""
    async with pool.acquire() as conn:
        subs = await conn.fetchval("SELECT COUNT(*) FROM subscribers")
        chans = await conn.fetchval("SELECT COUNT(*) FROM source_channels")
        kws = await conn.fetchval("SELECT COUNT(*) FROM keywords")
        notifs = await conn.fetchval("SELECT COUNT(DISTINCT sent_at) FROM sent_notifications")
        return {
            "subscribers": subs,
            "channels": chans,
            "keywords": kws,
            "notifications": notifs or 0
        }


async def save_notification(user_id: int, message_id_per_user: int, text: str, source_channel: str, photo_file_id: str = None):
    """Сохранить лог отправленного уведомления."""
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO sent_notifications (source_channel, message_id_per_user, user_id, text, photo_file_id)
            VALUES ($1, $2, $3, $4, $5)
        """, source_channel, message_id_per_user, user_id, text, photo_file_id)


async def get_notification_history(limit: int = 5, offset: int = 0):
    """Получить историю уникальных рассылок."""
    async with pool.acquire() as conn:
        return await conn.fetch("""
            SELECT DISTINCT ON (sent_at) id, source_channel, text, photo_file_id, sent_at
            FROM sent_notifications
            ORDER BY sent_at DESC, id DESC
            LIMIT $1 OFFSET $2
        """, limit, offset)


async def add_suggested_post(user_id: int, text: str, photo_file_id: str = None) -> int:
    """Сохранить предложенный пост от пользователя."""
    async with pool.acquire() as conn:
        return await conn.fetchval("""
            INSERT INTO suggested_posts (user_id, text, photo_file_id)
            VALUES ($1, $2, $3) RETURNING id
        """, user_id, text, photo_file_id)


async def get_suggested_post(post_id: int):
    """Получить предложенный пост по ID."""
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM suggested_posts WHERE id = $1", post_id)


async def update_post_status(post_id: int, status: str):
    """Обновить статус модерации предложенного поста."""
    async with pool.acquire() as conn:
        await conn.execute("UPDATE suggested_posts SET status = $1 WHERE id = $2", status, post_id)


# ИСПРАВЛЕНО: Переименовано в fix_channel_urls для точного соответствия вызову из main.py
async def fix_channel_urls():
    """Скрипт миграции (убирает t.me/ ссылки, превращая их в юзернеймы)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, channel FROM source_channels")
        for row in rows:
            channel = row["channel"]
            if "t.me/" in channel:
                clean = "@" + channel.split("t.me/")[-1].strip("/")
                await conn.execute(
                    "UPDATE source_channels SET channel = $1 WHERE id = $2",
                    clean, row["id"]
                )
                logger.info(f"Исправлен формат ссылки канала: {channel!r} → {clean!r}")


async def init_seen_posts_table():
    """Создать таблицу для хранения уже обработанных постов."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_posts (
                post_id TEXT PRIMARY KEY,
                channel TEXT NOT NULL,
                seen_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # Автоматическая очистка: удаляем записи старше 7 дней
        await conn.execute("""
            DELETE FROM seen_posts WHERE seen_at < NOW() - INTERVAL '7 days'
        """)


async def is_post_seen(post_id: str) -> bool:
    """Проверить, был ли пост уже обработан парсером."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM seen_posts WHERE post_id = $1", post_id
        )
        return row is not None


async def mark_post_seen(post_id: str, channel: str):
    """Отметить ID поста как обработанный."""
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO seen_posts (post_id, channel) 
            VALUES ($1, $2) 
            ON CONFLICT (post_id) DO NOTHING
        """, post_id, channel)