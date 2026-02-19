"""
Обработка предложений постов от пользователей.
Администратор одобряет или отклоняет предложения.
"""

import logging
import os
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery

from db import database as db

logger = logging.getLogger(__name__)
router = Router()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))


@router.callback_query(F.data.startswith("approve_post:"))
async def approve_post(callback: CallbackQuery, bot: Bot, broadcaster=None):
    """Одобрение предложения администратором и рассылка подписчикам."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    post_id = int(callback.data.split(":")[1])
    post = await db.get_suggested_post(post_id)

    if not post or post["status"] != "pending":
        await callback.answer("Предложение уже обработано.", show_alert=True)
        return

    await db.update_post_status(post_id, "approved")

    # Рассылка подписчикам
    subscribers = await db.get_all_subscribers()
    text = post["text"] or ""
    photo_file_id = post["photo_file_id"]
    notification_text = f"🚃 <b>Уведомление о трамваях Тулы</b>\n\nИсточник: пользователь\n\n{text}"

    sent_count = 0
    for user_id in subscribers:
        try:
            if photo_file_id:
                msg = await bot.send_photo(
                    user_id,
                    photo=photo_file_id,
                    caption=notification_text,
                    parse_mode="HTML"
                )
            else:
                msg = await bot.send_message(
                    user_id,
                    text=notification_text,
                    parse_mode="HTML"
                )
            await db.save_notification(
                user_id=user_id,
                message_id=msg.message_id,
                text=notification_text,
                source_channel=f"user:{post['user_id']}",
                photo_file_id=photo_file_id
            )
            sent_count += 1
        except Exception as e:
            err_str = str(e)
            if "blocked" in err_str.lower() or "user is deactivated" in err_str.lower():
                await db.remove_subscriber(user_id)
                logger.info(f"Удалён заблокировавший бота подписчик: {user_id}")
            else:
                logger.error(f"Ошибка при рассылке пользователю {user_id}: {e}")

    # Уведомляем автора
    try:
        await bot.send_message(post["user_id"], "✅ Ваше сообщение опубликовано!")
    except Exception:
        pass

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(f"Опубликовано {sent_count} подписчикам.", show_alert=True)
    logger.info(f"Пост #{post_id} одобрен, разослан {sent_count} подписчикам")


@router.callback_query(F.data.startswith("reject_post:"))
async def reject_post(callback: CallbackQuery, bot: Bot):
    """Отклонение предложения администратором."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    post_id = int(callback.data.split(":")[1])
    post = await db.get_suggested_post(post_id)

    if not post or post["status"] != "pending":
        await callback.answer("Предложение уже обработано.", show_alert=True)
        return

    await db.update_post_status(post_id, "rejected")

    # Уведомляем автора
    try:
        await bot.send_message(
            post["user_id"],
            "❌ Ваше сообщение не прошло модерацию."
        )
    except Exception:
        pass

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Отклонено.", show_alert=True)
    logger.info(f"Пост #{post_id} отклонён")
