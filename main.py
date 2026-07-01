# Устанавливаем команды бота в меню Telegram
    from aiogram.types import BotCommand
    await bot.set_my_commands([
        BotCommand(command="start", description="Подписаться на уведомления"),
        BotCommand(command="stop", description="Отписаться от уведомлений"),
        BotCommand(command="routes", description="Список маршрутов Тулы"),
        BotCommand(command="suggest", description="Предложить сообщение для публикации"),
    ])