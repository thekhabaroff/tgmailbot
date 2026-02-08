"""Клавиатуры"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from typing import List, Optional


def get_back_keyboard(callback_data: str = "back_to_menu") -> InlineKeyboardMarkup:
    """Получить клавиатуру только с кнопкой 'назад'"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=callback_data)]
    ])


def get_main_menu_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Главное меню"""
    keyboard = [
        [KeyboardButton(text="📂 Каталог")],
        [KeyboardButton(text="💰 Баланс"), KeyboardButton(text="📦 Мои заказы")],
        [KeyboardButton(text="👥 Пригласить друга"), KeyboardButton(text="💬 Поддержка")],
        [KeyboardButton(text="ℹ️ Информация"), KeyboardButton(text="📜 Правила")]
    ]
    
    if is_admin:
        keyboard.append([KeyboardButton(text="⚙️ Пункт управления")])
        keyboard.append([KeyboardButton(text="📢 Рассылка")])
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_categories_keyboard(categories: List) -> InlineKeyboardMarkup:
    """Клавиатура категорий"""
    buttons = []
    for category in categories:
        buttons.append([InlineKeyboardButton(
            text=category.name,
            callback_data=f"category_{category.id}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_products_keyboard(products: List, category_id: int) -> InlineKeyboardMarkup:
    """Клавиатура товаров"""
    buttons = []
    for product in products:
        status = "✅" if product.stock_count > 0 else "❌ НЕТ В НАЛИЧИИ"
        buttons.append([InlineKeyboardButton(
            text=f"{product.name} - {product.price:.2f} ₽ {status}",
            callback_data=f"product_{product.id}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_catalog")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_product_detail_keyboard(product_id: int, has_stock: bool, category_id: int) -> InlineKeyboardMarkup:
    """Клавиатура деталей товара"""
    buttons = []
    if has_stock:
        buttons.append([InlineKeyboardButton(text="💳 Купить", callback_data=f"buy_{product_id}")])
    else:
        buttons.append([InlineKeyboardButton(
            text="🔔 Уведомить о поступлении",
            callback_data=f"notify_{product_id}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад к товарам", callback_data=f"category_{category_id}")])
    buttons.append([InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_payment_methods_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Способы оплаты"""
    from config import settings
    
    buttons = [
        [InlineKeyboardButton(text="💳 С баланса", callback_data=f"pay_balance_{order_id}")]
    ]
    
    # Добавляем внешние платежные системы, если они настроены
    if settings.YOOKASSA_SHOP_ID and settings.YOOKASSA_SECRET_KEY:
        buttons.append([InlineKeyboardButton(text="💳 ЮКасса", callback_data=f"pay_yookassa_{order_id}")])
    
    if settings.ROBOKASSA_MERCHANT_LOGIN and settings.ROBOKASSA_PASSWORD_1:
        buttons.append([InlineKeyboardButton(text="💳 Robokassa", callback_data=f"pay_robokassa_{order_id}")])
    
    if settings.LAVA_PROJECT_ID and settings.LAVA_SECRET_KEY:
        buttons.append([InlineKeyboardButton(text="💳 Lava", callback_data=f"pay_lava_{order_id}")])
    
    if settings.HELEKET_API_KEY:
        buttons.append([InlineKeyboardButton(text="💳 Heleket", callback_data=f"pay_heleket_{order_id}")])
    
    # Telegram Stars всегда доступен (если бот настроен)
    buttons.append([InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"pay_stars_{order_id}")])
    
    # ========== ТЕСТОВАЯ ОПЛАТА (для разработки) ==========
    # Раскомментируйте блок ниже для включения тестовой оплаты
    # В продакшн закомментируйте этот блок полностью
    if settings.ENABLE_TEST_PAYMENT:
        buttons.append([InlineKeyboardButton(text="🧪 Тестовая оплата", callback_data=f"pay_test_{order_id}")])
    # ========================================================
    
    buttons.append([InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_order_{order_id}")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_balance_topup_keyboard() -> InlineKeyboardMarkup:
    """Пополнение баланса"""
    from config import settings
    
    buttons = []
    
    # ЮКасса
    if settings.YOOKASSA_SHOP_ID and settings.YOOKASSA_SECRET_KEY:
        buttons.append([InlineKeyboardButton(text="💳 ЮКасса", callback_data="topup_yookassa")])
    
    # Heleket
    if settings.HELEKET_API_KEY:
        buttons.append([InlineKeyboardButton(text="💳 Heleket", callback_data="topup_heleket")])
    
    # Если нет настроенных платежных систем, показываем сообщение
    if not buttons:
        buttons.append([InlineKeyboardButton(text="ℹ️ Через администратора", callback_data="topup_admin")])
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_orders_keyboard(orders: List) -> InlineKeyboardMarkup:
    """Клавиатура заказов"""
    buttons = []
    for order in orders:
        status_emoji = {
            "ОЖИДАЕТ ОПЛАТЫ": "⏳",
            "ОПЛАЧЕНО": "✅",
            "ВЫПОЛНЕНО": "✔️",
            "ОТМЕНЕНО": "❌"
        }.get(order.status, "❓")
        
        buttons.append([InlineKeyboardButton(
            text=f"{status_emoji} Заказ #{order.id} - {order.total_amount:.2f} ₽",
            callback_data=f"order_{order.id}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_order_detail_keyboard(order_id: int, status: str) -> InlineKeyboardMarkup:
    """Клавиатура деталей заказа"""
    buttons = []
    if status == "ОЖИДАЕТ ОПЛАТЫ":
        buttons.append([InlineKeyboardButton(
            text="💳 Оплатить заказ",
            callback_data=f"pay_order_{order_id}"
        )])
        buttons.append([InlineKeyboardButton(
            text="❌ Отменить заказ",
            callback_data=f"cancel_order_{order_id}"
        )])
    elif status == "ВЫПОЛНЕНО":
        buttons.append([InlineKeyboardButton(
            text="📥 Скачать товар",
            callback_data=f"download_{order_id}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="my_orders")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_menu_keyboard() -> InlineKeyboardMarkup:
    """Админ меню"""
    buttons = [
        [InlineKeyboardButton(text="📦 Заказы", callback_data="admin_orders")],
        [InlineKeyboardButton(text="📂 Каталог", callback_data="admin_catalog")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="💰 Пополнить свой баланс", callback_data="admin_topup_self")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📝 Логи ошибок", callback_data="admin_logs")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_orders_keyboard() -> InlineKeyboardMarkup:
    """Админ - заказы"""
    buttons = [
        [InlineKeyboardButton(text="📋 Все заказы", callback_data="admin_orders_all")],
        [InlineKeyboardButton(text="🔍 Поиск по ID", callback_data="admin_orders_search")],
        [InlineKeyboardButton(text="📅 По дате", callback_data="admin_orders_date")],
        [InlineKeyboardButton(text="📊 По статусу", callback_data="admin_orders_status")],
        [InlineKeyboardButton(text="👤 По пользователю", callback_data="admin_orders_user")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_catalog_keyboard() -> InlineKeyboardMarkup:
    """Админ - каталог"""
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить категорию", callback_data="admin_add_category")],
        [InlineKeyboardButton(text="🗑️ Удалить категорию", callback_data="admin_delete_category")],
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin_add_product")],
        [InlineKeyboardButton(text="🗑️ Удалить товар", callback_data="admin_delete_product")],
        [InlineKeyboardButton(text="✏️ Редактировать товар", callback_data="admin_edit_product")],
        [InlineKeyboardButton(text="📦 Управление аккаунтами", callback_data="admin_manage_accounts")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_confirm_keyboard(action: str, item_id: int) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения"""
    buttons = [
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_{action}_{item_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_{action}_{item_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

