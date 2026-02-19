"""
Скрипт для генерации Telethon StringSession.
Запускается ОДИН РАЗ локально перед деплоем.

Использование:
    python generate_session.py

Полученную строку сессии вставьте в переменную окружения TELETHON_SESSION.
"""

import asyncio
import os
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("TELETHON_API_ID", "0"))
API_HASH = os.getenv("TELETHON_API_HASH", "")


async def generate():
    if not API_ID or not API_HASH:
        print("Ошибка: задайте TELETHON_API_ID и TELETHON_API_HASH в .env файле")
        return

    print("Генерация Telethon StringSession...")
    print("Вам потребуется войти в аккаунт Telegram (номер телефона + код)\n")

    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        session_string = client.session.save()
        print("\n" + "=" * 60)
        print("TELETHON_SESSION (скопируйте в переменные окружения Railway):")
        print("=" * 60)
        print(session_string)
        print("=" * 60)
        print("\nСессия сохранена. Используйте эту строку как TELETHON_SESSION.")


if __name__ == "__main__":
    asyncio.run(generate())
