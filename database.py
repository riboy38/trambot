"""
Модуль для работы с базой данных PostgreSQL через asyncpg.
Содержит все запросы к БД.
"""

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
    logger.info("Таблицы созданы/проверены")


async def seed_keywords():
    """Установка ключевых слов для мониторинга трамваев."""
    keywords = [
        "автомобиль на трамвайных путях",
        "встала на трамвайных путях",
        "встали трамваи",
        "встал трамвай",
        "движение рельсового транспорта остановлено",
        "движение трамваев остановлено",
        "заехал на рельсы",
        "застрявший на рельсах",
        "застряла машина на трамвайных путях",
        "застряла на трамвайных путях",
        "застряли на трамвайных путях",
        "застрял на трамвайных путях",
        "на рельсах застрял",
        "на рельсах застряла",
        "на трамвайных путях столкнулись",
        "остановки движения рельсового транспорта",
        "остановлено движение трамваев",
        "перекрыл трамвайные пути",
        "прекращено трамвайное сообщение",
        "решил проехать по трамвайным путям",
        "сел на трамвайные рельсы",
        "сошел с рельсов",
        "сошел с рельсов трамвай",
        "сошёл трамвай с рельсов",
        "трамваи встали",
        "трамваи на аварийке",
        "трамваи не могут проехать",
        "трамваи сломались",
        "трамваи стоят",
        "трамвай на аварийке",
        "трамвай не может ехать",
        "трамвай сломался",
        "трамвай сошел с рельс",
        "трамвай сошел с рельсов",
        "трамвай сошёл с рельсов",
        "трамвая встали",
    ]
    async with pool.acquire() as conn:
        # Очищаем старые ключевые слова и устанавливаем новые
        await conn.execute("DELETE FROM keywords")
        for word in keywords:
            await conn.execute(
                "INSERT INTO keywords (word) VALUES ($1) ON CONFLICT (word) DO NOTHING",
                word
            )
    logger.info(f"Установлено {len(keywords)} ключевых слов")


# ─── Подписчики ───────────────────────────────────────────────────────────────

async def add_subscriber(user_id: int) -> bool:
    """Подписать пользователя. Возвращает True если новый."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "INSERT INTO subscribers (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id
        )
        return result == "INSERT 0 1"


async def remove_subscriber(user_id: int):
    """Отписать пользователя."""
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM subscribers WHERE user_id = $1", user_id)


async def is_subscriber(user_id: int) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM subscribers WHERE user_id = $1", user_id)
        return row is not None


async def get_all_subscribers() -> list[int]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM subscribers")
        return [r["user_id"] for r in rows]


async def get_subscribers_count() -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM subscribers")


# ─── Ключевые слова ──────────────────────────────────────────────────────────

async def get_keywords() -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT word FROM keywords ORDER BY word")
        return [r["word"] for r in rows]


async def add_keyword(word: str) -> bool:
    """Добавить ключевое слово. Возвращает True если добавлено."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "INSERT INTO keywords (word) VALUES ($1) ON CONFLICT (word) DO NOTHING",
            word.lower()
        )
        return result == "INSERT 0 1"


async def remove_keyword(word: str) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM keywords WHERE word = $1", word.lower())
        return result == "DELETE 1"


# ─── Каналы-источники ─────────────────────────────────────────────────────────

async def get_source_channels() -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT channel FROM source_channels ORDER BY added_at")
        return [r["channel"] for r in rows]


async def add_source_channel(channel: str) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "INSERT INTO source_channels (channel) VALUES ($1) ON CONFLICT (channel) DO NOTHING",
            channel
        )
        return result == "INSERT 0 1"


async def remove_source_channel(channel: str) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM source_channels WHERE channel = $1", channel)
        return result == "DELETE 1"


async def get_channels_count() -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM source_channels")


# ─── Уведомления ─────────────────────────────────────────────────────────────

async def save_notification(
    user_id: int,
    message_id: int,
    text: str,
    source_channel: str = None,
    photo_file_id: str = None
):
    """Сохранить запись об отправленном уведомлении."""
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO sent_notifications
               (source_channel, message_id_per_user, user_id, text, photo_file_id)
               VALUES ($1, $2, $3, $4, $5)""",
            source_channel, message_id, user_id, text, photo_file_id
        )


async def get_notifications_history(offset: int = 0, limit: int = 10) -> list[dict]:
    """Получить историю уведомлений с пагинацией."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, source_channel, text, photo_file_id, sent_at
               FROM sent_notifications
               ORDER BY sent_at DESC
               LIMIT $1 OFFSET $2""",
            limit, offset
        )
        return [dict(r) for r in rows]


async def get_notifications_for_deletion(notification_id: int) -> list[dict]:
    """Получить все записи уведомления для удаления по id одной записи."""
    async with pool.acquire() as conn:
        # Получаем текст/источник эталонной записи
        ref = await conn.fetchrow(
            "SELECT text, source_channel FROM sent_notifications WHERE id = $1",
            notification_id
        )
        if not ref:
            return []
        rows = await conn.fetch(
            """SELECT id, user_id, message_id_per_user
               FROM sent_notifications
               WHERE text = $1 AND source_channel IS NOT DISTINCT FROM $2""",
            ref["text"], ref["source_channel"]
        )
        return [dict(r) for r in rows]


async def delete_notification_records(notification_id: int):
    """Удалить все записи уведомления из БД."""
    async with pool.acquire() as conn:
        ref = await conn.fetchrow(
            "SELECT text, source_channel FROM sent_notifications WHERE id = $1",
            notification_id
        )
        if not ref:
            return
        await conn.execute(
            """DELETE FROM sent_notifications
               WHERE text = $1 AND source_channel IS NOT DISTINCT FROM $2""",
            ref["text"], ref["source_channel"]
        )


async def get_notifications_24h_count() -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(DISTINCT text) FROM sent_notifications WHERE sent_at > NOW() - INTERVAL '24 hours'"
        )


# ─── Предложения постов ───────────────────────────────────────────────────────

async def create_suggested_post(user_id: int, text: str, photo_file_id: str = None) -> int:
    """Создать предложение, вернуть id."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO suggested_posts (user_id, text, photo_file_id)
               VALUES ($1, $2, $3) RETURNING id""",
            user_id, text, photo_file_id
        )


async def get_pending_post_by_user(user_id: int) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM suggested_posts WHERE user_id = $1 AND status = 'pending'",
            user_id
        )
        return dict(row) if row else None


async def get_suggested_post(post_id: int) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM suggested_posts WHERE id = $1", post_id)
        return dict(row) if row else None


async def update_post_status(post_id: int, status: str):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE suggested_posts SET status = $1 WHERE id = $2",
            status, post_id
        )


async def get_pending_posts_count() -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM suggested_posts WHERE status = 'pending'"
        )


async def fix_channel_urls():
    """
    Исправляет каналы, добавленные как полные ссылки.
    Например @https://t.me/tula_smi → @tula_smi
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, channel FROM source_channels")
        for row in rows:
            channel = row["channel"]
            # Убираем лишнее: @https://t.me/ или https://t.me/
            if "t.me/" in channel:
                clean = "@" + channel.split("t.me/")[-1].strip("/")
                await conn.execute(
                    "UPDATE source_channels SET channel = $1 WHERE id = $2",
                    clean, row["id"]
                )
                logger.info(f"Исправлен канал: {channel!r} → {clean!r}")
