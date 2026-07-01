# ─── Меню маршрутов для пользователей ────────────────────────────────────────

def route_sort_key(route: dict) -> tuple:
    """
    Ключ сортировки для номеров маршрутов:
    1. Сначала идут числовые (включая со слэшем '/') по первому числу.
    2. В самом конце идут чисто текстовые маршруты (например, 'Челнок').
    """
    num_str = route['route_number'].strip()
    
    # Если маршрут содержит слэш (например, 1/12, 9/10)
    if '/' in num_str:
        first_part = num_str.split('/')[0].strip()
        if first_part.isdigit():
            return (0, int(first_part), num_str)
            
    # Если это просто чистое число (например, 3, 6, 11)
    if num_str.isdigit():
        return (0, int(num_str), num_str)
        
    # Если это текст (например, 'Челнок') — отправляем в самый конец
    return (1, 0, num_str)


async def build_user_routes_keyboard() -> InlineKeyboardMarkup:
    routes = await db.get_all_routes()
    
    # Сортируем список маршрутов по созданному правилу
    sorted_routes = sorted(routes, key=route_sort_key)
    
    buttons = []
    row = []
    for r in sorted_routes:
        # Убрали слово "Трамвай", оставляем только чистый номер (например, "1/12" или "Челнок")
        button_text = f"№ {r['route_number']}"
        row.append(InlineKeyboardButton(text=button_text, callback_data=f"user:route_info:{r['route_number']}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("routes"))
async def cmd_user_routes(message: Message, bot: Bot):
    if not await check_channel_subscription(bot, message.from_user.id):
        await send_subscribe_prompt(message)
        return
    
    keyboard = await build_user_routes_keyboard()
    if not keyboard.inline_keyboard:
        await message.answer("🚧 На данный момент список маршрутов пуст.")
        return

    # Изменили текст заголовка на требуемый
    await message.answer(
        "🚧 <b>Список трамвайных маршрутов Тулы</b>\n\n"
        "Выберите интересующий вас номер ниже, чтобы узнать его актуальный путь следования:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.callback_query(F.data == "user:routes:back")
async def user_routes_back(callback, bot: Bot):
    try:
        await callback.message.delete()
    except Exception:
        pass
        
    keyboard = await build_user_routes_keyboard()
    # Здесь текст заголовка тоже обновили для единообразия при возврате назад
    await bot.send_message(
        chat_id=callback.from_user.id,
        text="🚧 <b>Список трамвайных маршрутов Тулы</b>\n\nВыберите номер:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()