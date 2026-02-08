"""Обработчик админ-панели"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from database.models import (
    User, Order, Product, Category, Account, Log, Setting, StockNotification
)
from services.account_service import upload_accounts_from_file
from utils.keyboards import (
    get_admin_menu_keyboard, get_admin_orders_keyboard, get_admin_catalog_keyboard,
    get_confirm_keyboard
)
from config import settings
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

router = Router()


class AdminStates(StatesGroup):
    """Состояния для админ-панели"""
    waiting_product_name = State()
    waiting_product_price = State()
    waiting_product_description = State()
    waiting_product_format = State()
    waiting_product_recommendations = State()
    waiting_product_category = State()
    waiting_product_quantity = State()
    waiting_category_name = State()
    waiting_upload_file = State()
    waiting_order_id = State()
    waiting_user_id = State()
    waiting_setting_key = State()
    waiting_setting_value = State()
    waiting_balance_user_id = State()
    waiting_balance_amount = State()
    
    # Редактирование товаров
    waiting_edit_product_id = State()
    waiting_edit_product_search = State()
    waiting_edit_product_field = State()
    waiting_edit_product_value = State()
    
    # Управление аккаунтами
    waiting_add_account = State()
    waiting_import_accounts_file = State()
    
    # Удаление категории
    waiting_delete_category_id = State()
    waiting_delete_category_name = State()
    waiting_delete_product_name = State()
    waiting_bulk_delete_products = State()
    waiting_bulk_block_users = State()
    
    # Фильтры заказов
    waiting_order_date_from = State()
    waiting_order_date_to = State()
    waiting_order_status_filter = State()
    waiting_order_user_filter = State()
    
    # Настройки
    waiting_setting_edit_key = State()
    waiting_setting_edit_value = State()


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором (только .env, синхронная)"""
    return user_id in settings.admin_ids_list or user_id in settings.developer_ids_list


def is_developer(user_id: int) -> bool:
    """Проверка, является ли пользователь разработчиком (только .env, синхронная)"""
    return user_id in settings.developer_ids_list


async def is_admin_async(user_id: int, session: AsyncSession) -> bool:
    """Проверка, является ли пользователь администратором (гибридная: .env + БД)"""
    # Сначала проверяем .env (суперадмины)
    if user_id in settings.admin_ids_list or user_id in settings.developer_ids_list:
        return True
    
    # Затем проверяем роль в БД
    stmt = select(User).where(User.telegram_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if user and user.role in ("admin", "developer"):
        return True
    
    return False


async def is_developer_async(user_id: int, session: AsyncSession) -> bool:
    """Проверка, является ли пользователь разработчиком (гибридная: .env + БД)"""
    # Сначала проверяем .env
    if user_id in settings.developer_ids_list:
        return True
    
    # Затем проверяем роль в БД
    stmt = select(User).where(User.telegram_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if user and user.role == "developer":
        return True
    
    return False


def get_all_menu_buttons():
    """Получить все кнопки меню"""
    from utils.text import MENU_CATALOG, MENU_BALANCE, MENU_ORDERS, MENU_REFERRAL, MENU_SUPPORT, MENU_INFO, MENU_RULES, MENU_ADMIN, MENU_BROADCAST
    return [MENU_CATALOG, MENU_BALANCE, MENU_ORDERS, MENU_REFERRAL, MENU_SUPPORT, MENU_INFO, MENU_RULES, MENU_ADMIN, MENU_BROADCAST, "📢 Рассылка", "⚙️ Пункт управления"]


async def check_menu_button_and_clear_state(message: Message, state: FSMContext) -> bool:
    """Проверить, является ли сообщение кнопкой меню, и очистить состояние если да"""
    if message.text:
        menu_buttons = get_all_menu_buttons()
        if message.text in menu_buttons or message.text.startswith('/'):
            await state.clear()
            return True
    return False


@router.message(F.text == "⚙️ Пункт управления")
async def admin_menu(message: Message, state: FSMContext, session: AsyncSession):
    """Главное меню админки"""
    if not await is_admin_async(message.from_user.id, session):
        await message.answer("❌ Доступ запрещен")
        return
    
    # Очищаем FSM состояние при переходе в админ-панель
    await state.clear()
    
    await message.answer(
        "⚙️ <b>Пункт управления</b>\n\nВыберите раздел:",
        reply_markup=get_admin_menu_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin_menu")
async def admin_menu_callback(callback: CallbackQuery, session: AsyncSession):
    """Главное меню админки (callback)"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await callback.message.edit_text(
        "⚙️ <b>Пункт управления</b>\n\nВыберите раздел:",
        reply_markup=get_admin_menu_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


# Управление заказами
@router.callback_query(F.data == "admin_orders")
async def admin_orders_menu(callback: CallbackQuery, session: AsyncSession):
    """Меню управления заказами"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📦 <b>Управление заказами</b>\n\nВыберите действие:",
        reply_markup=get_admin_orders_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_orders_all")
async def admin_orders_all(callback: CallbackQuery, session: AsyncSession):
    """Все заказы"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    stmt = select(Order).order_by(Order.created_at.desc()).limit(50)
    result = await session.execute(stmt)
    orders = result.scalars().all()
    
    if not orders:
        await callback.message.edit_text("Заказов нет")
        await callback.answer()
        return
    
    text = "📦 <b>Текущие заказы:</b>\n\n"
    buttons = []
    
    for order in orders:
        # Получаем пользователя
        stmt_user = select(User).where(User.id == order.user_id)
        result_user = await session.execute(stmt_user)
        user = result_user.scalar_one_or_none()
        
        # Получаем товар
        stmt_product = select(Product).where(Product.id == order.product_id)
        result_product = await session.execute(stmt_product)
        product = result_product.scalar_one_or_none()
        
        user_name = f"@{user.username}" if user and user.username else (user.first_name if user else "Неизвестно")
        product_name = product.name if product else f"Товар ID: {order.product_id}"
        
        status_emoji = {
            "ОЖИДАЕТ ОПЛАТЫ": "⏳",
            "ОПЛАЧЕНО": "✅",
            "ВЫПОЛНЕНО": "✔️",
            "ОТМЕНЕНО": "❌"
        }.get(order.status, "❓")
        
        text += f"{status_emoji} <b>Заказ #{order.id}</b>\n"
        text += f"👤 Покупатель: {user_name}\n"
        text += f"📦 Товар: {product_name}\n"
        text += f"📊 Количество: {order.quantity} шт.\n"
        text += f"💰 Сумма: {order.total_amount:.2f} ₽\n"
        text += f"📋 Статус: {order.status}\n\n"
        
        # Добавляем кнопку для просмотра деталей и отмены
        if order.status in ["ОЖИДАЕТ ОПЛАТЫ", "ОПЛАЧЕНО"]:
            buttons.append([InlineKeyboardButton(
                text=f"📋 Заказ #{order.id} - {user_name}",
                callback_data=f"admin_order_detail_{order.id}"
            )])
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_orders")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_orders_search")
async def admin_orders_search_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать поиск заказа по ID"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_order_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_orders")]
    ])
    await callback.message.edit_text("Введите ID заказа:", reply_markup=keyboard)
    await callback.answer()


@router.message(AdminStates.waiting_order_id)
async def admin_orders_search_result(message: Message, state: FSMContext, session: AsyncSession):
    """Результат поиска заказа"""
    # Проверяем, не выбрана ли кнопка меню
    from utils.text import MENU_CATALOG, MENU_BALANCE, MENU_ORDERS, MENU_REFERRAL, MENU_SUPPORT, MENU_INFO, MENU_RULES, MENU_ADMIN, MENU_BROADCAST
    menu_buttons = [MENU_CATALOG, MENU_BALANCE, MENU_ORDERS, MENU_REFERRAL, MENU_SUPPORT, MENU_INFO, MENU_RULES, MENU_ADMIN, MENU_BROADCAST, "📢 Рассылка", "⚙️ Пункт управления", "🛒 Корзина"]
    
    if message.text and (message.text in menu_buttons or message.text.startswith('/')):
        await state.clear()
        return
    
    try:
        order_id = int(message.text)
        
        stmt = select(Order).where(Order.id == order_id)
        result = await session.execute(stmt)
        order = result.scalar_one_or_none()
        
        if not order:
            await message.answer("Заказ не найден")
            await state.clear()
            return
        
        stmt_user = select(User).where(User.id == order.user_id)
        result_user = await session.execute(stmt_user)
        user = result_user.scalar_one_or_none()
        
        text = f"""📦 <b>Заказ #{order.id}</b>

👤 Пользователь: @{user.username if user else 'N/A'} (ID: {user.telegram_id if user else 'N/A'})
📦 Товар ID: {order.product_id}
📊 Количество: {order.quantity} шт.
💰 Сумма: {order.total_amount:.2f} ₽
📋 Статус: {order.status}
💳 Способ оплаты: {order.payment_method or 'N/A'}
📅 Создан: {order.created_at.strftime('%d.%m.%Y %H:%M')}
"""
        
        if order.paid_at:
            text += f"✅ Оплачен: {order.paid_at.strftime('%d.%m.%Y %H:%M')}\n"
        
        await message.answer(text, parse_mode="HTML")
        await state.clear()
        
    except ValueError:
        await message.answer("Введите корректный ID заказа (число):")
    except Exception as e:
        logger.error(f"Error searching order: {e}")
        await message.answer("Ошибка при поиске заказа")
        await state.clear()


@router.callback_query(F.data.startswith("admin_order_detail_"))
async def admin_order_detail(callback: CallbackQuery, session: AsyncSession):
    """Детали заказа для администратора"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    order_id = int(callback.data.split("_")[3])
    
    stmt = select(Order).where(Order.id == order_id)
    result = await session.execute(stmt)
    order = result.scalar_one_or_none()
    
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    
    # Получаем пользователя
    stmt_user = select(User).where(User.id == order.user_id)
    result_user = await session.execute(stmt_user)
    user = result_user.scalar_one_or_none()
    
    # Получаем товар
    stmt_product = select(Product).where(Product.id == order.product_id)
    result_product = await session.execute(stmt_product)
    product = result_product.scalar_one_or_none()
    
    user_name = f"@{user.username}" if user and user.username else (user.first_name if user else "Неизвестно")
    user_id_display = user.telegram_id if user else "N/A"
    product_name = product.name if product else f"Товар ID: {order.product_id}"
    
    text = f"""📦 <b>Заказ #{order.id}</b>

👤 Покупатель: {user_name}
🆔 ID пользователя: {user_id_display}
📦 Товар: {product_name}
📊 Количество: {order.quantity} шт.
💰 Цена за единицу: {order.price_per_unit:.2f} ₽
"""
    
    if order.discount > 0:
        text += f"🎁 Скидка: {order.discount}%\n"
    
    text += f"💰 Сумма: {order.total_amount:.2f} ₽\n"
    text += f"📋 Статус: {order.status}\n"
    
    if order.payment_method:
        text += f"💳 Способ оплаты: {order.payment_method}\n"
    
    text += f"📅 Создан: {order.created_at.strftime('%d.%m.%Y %H:%M')}\n"
    
    if order.paid_at:
        text += f"✅ Оплачен: {order.paid_at.strftime('%d.%m.%Y %H:%M')}\n"
    
    if order.completed_at:
        text += f"✔️ Выполнен: {order.completed_at.strftime('%d.%m.%Y %H:%M')}\n"
    
    # Кнопки управления
    buttons = []
    if order.status in ["ОЖИДАЕТ ОПЛАТЫ", "ОПЛАЧЕНО"]:
        buttons.append([InlineKeyboardButton(
            text="❌ Отменить заказ",
            callback_data=f"admin_order_cancel_{order.id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_orders_all")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_order_cancel_"))
async def admin_cancel_order(callback: CallbackQuery, session: AsyncSession):
    """Отменить заказ (администратор)"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    order_id = int(callback.data.split("_")[3])
    
    stmt = select(Order).where(Order.id == order_id)
    result = await session.execute(stmt)
    order = result.scalar_one_or_none()
    
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    
    if order.status == "ОТМЕНЕНО":
        await callback.answer("Заказ уже отменен", show_alert=True)
        return
    
    if order.status == "ВЫПОЛНЕНО":
        await callback.answer("Нельзя отменить выполненный заказ", show_alert=True)
        return
    
    # Отменяем заказ
    order.status = "ОТМЕНЕНО"
    order.reserved_until = None
    await session.commit()
    
    # Уведомляем пользователя
    stmt_user = select(User).where(User.id == order.user_id)
    result_user = await session.execute(stmt_user)
    user = result_user.scalar_one_or_none()
    
    if user:
        try:
            await callback.bot.send_message(
                user.telegram_id,
                f"❌ <b>Заказ отменен</b>\n\n"
                f"Заказ #{order.id} был отменен администратором.\n"
                f"Если заказ был оплачен, средства будут возвращены.",
                parse_mode="HTML"
            )
        except:
            pass
    
    await callback.answer("✅ Заказ отменен", show_alert=True)
    await callback.message.edit_text(f"✅ Заказ #{order_id} отменен")


@router.callback_query(F.data.startswith("admin_order_status_"))
async def admin_change_order_status(callback: CallbackQuery, session: AsyncSession):
    """Изменить статус заказа"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    order_id = int(callback.data.split("_")[3])
    new_status = callback.data.split("_")[4]
    
    stmt = select(Order).where(Order.id == order_id)
    result = await session.execute(stmt)
    order = result.scalar_one_or_none()
    
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    
    order.status = new_status
    if new_status == "ВЫПОЛНЕНО":
        order.completed_at = datetime.now()
    
    await session.commit()
    
    await callback.answer(f"Статус заказа изменен на: {new_status}", show_alert=True)


# Управление каталогом
@router.callback_query(F.data == "admin_catalog")
async def admin_catalog_menu(callback: CallbackQuery, session: AsyncSession):
    """Меню управления каталогом"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📂 <b>Управление каталогом</b>\n\nВыберите действие:",
        reply_markup=get_admin_catalog_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()




@router.callback_query(F.data == "admin_add_category")
async def admin_add_category_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать добавление категории"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_category_name)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_catalog")]
    ])
    await callback.message.edit_text("Введите название категории:", reply_markup=keyboard)
    await callback.answer()


@router.message(AdminStates.waiting_category_name)
async def admin_add_category_finish(message: Message, state: FSMContext, session: AsyncSession):
    """Завершить добавление категории"""
    category_name = message.text.strip()
    
    if not category_name:
        await message.answer("Название не может быть пустым. Попробуйте снова:")
        return
    
    # Проверяем на дубликаты
    stmt = select(Category).where(Category.name == category_name)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    
    if existing:
        await message.answer("Категория с таким названием уже существует. Введите другое название:")
        return
    
    category = Category(name=category_name)
    session.add(category)
    await session.commit()
    
    await message.answer(f"✅ Категория '{category_name}' добавлена")
    await state.clear()


@router.callback_query(F.data == "admin_delete_category")
async def admin_delete_category_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать удаление категории - показываем список"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Получаем все категории
    stmt = select(Category).order_by(Category.name)
    result = await session.execute(stmt)
    categories = result.scalars().all()
    
    if not categories:
        await callback.message.edit_text(
            "❌ Категории не найдены",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_catalog")]
            ])
        )
        await callback.answer()
        return
    
    # Формируем список категорий с кнопками
    buttons = []
    text = "🗑️ <b>Удаление категории</b>\n\nВыберите категорию для удаления:\n\n"
    
    for category in categories:
        # Проверяем количество товаров
        stmt_products = select(func.count(Product.id)).where(Product.category_id == category.id)
        result_products = await session.execute(stmt_products)
        products_count = result_products.scalar()
        
        status = "✅" if category.is_active else "❌"
        text += f"{status} <b>{category.name}</b> (ID: {category.id}, товаров: {products_count})\n"
        buttons.append([InlineKeyboardButton(
            text=f"🗑️ {category.name}",
            callback_data=f"delete_category_{category.id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_catalog")])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delete_category_"))
async def admin_delete_category_confirm(callback: CallbackQuery, session: AsyncSession):
    """Подтверждение удаления категории"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    category_id = int(callback.data.split("_")[2])
    
    stmt = select(Category).where(Category.id == category_id)
    result = await session.execute(stmt)
    category = result.scalar_one_or_none()
    
    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    
    # Проверяем, есть ли товары в категории
    stmt_products = select(func.count(Product.id)).where(Product.category_id == category_id)
    result_products = await session.execute(stmt_products)
    products_count = result_products.scalar()
    
    if products_count > 0:
        keyboard = get_confirm_keyboard("delete_category", category_id)
        await callback.message.edit_text(
            f"⚠️ <b>Внимание!</b>\n\n"
            f"Категория: <b>{category.name}</b>\n"
            f"В категории находится <b>{products_count}</b> товар(ов).\n\n"
            f"При удалении категории все товары будут деактивированы.\n\n"
            f"Вы уверены, что хотите удалить категорию?",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        keyboard = get_confirm_keyboard("delete_category", category_id)
        await callback.message.edit_text(
            f"⚠️ <b>Подтвердите удаление</b>\n\n"
            f"Категория: <b>{category.name}</b>\n"
            f"Товаров в категории: 0\n\n"
            f"Вы уверены?",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_delete_category_"))
async def admin_delete_category_execute(callback: CallbackQuery, session: AsyncSession):
    """Выполнить удаление категории"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    category_id = int(callback.data.split("_")[3])
    
    stmt = select(Category).where(Category.id == category_id)
    result = await session.execute(stmt)
    category = result.scalar_one_or_none()
    
    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    
    # Проверяем, есть ли товары в категории
    stmt_products = select(Product).where(Product.category_id == category_id)
    result_products = await session.execute(stmt_products)
    products = result_products.scalars().all()
    
    if products:
        # Деактивируем все товары в категории
        for product in products:
            product.is_active = False
        
        # Деактивируем категорию вместо удаления
        category.is_active = False
        await session.commit()
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_catalog")]
        ])
        await callback.message.edit_text(
            f"✅ Категория <b>{category.name}</b> деактивирована\n\n"
            f"Деактивировано товаров: {len(products)}\n\n"
            f"Категория и товары скрыты из каталога, но сохранены в базе данных.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        # Удаляем категорию полностью, если нет товаров
        await session.delete(category)
        await session.commit()
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_catalog")]
        ])
        await callback.message.edit_text(
            f"✅ Категория <b>{category.name}</b> удалена",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_delete_category_"))
async def admin_delete_category_cancel(callback: CallbackQuery, session: AsyncSession):
    """Отмена удаления категории"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await callback.message.edit_text(
        "❌ Удаление категории отменено",
        reply_markup=get_admin_catalog_keyboard()
    )
    await callback.answer("Удаление отменено")


@router.callback_query(F.data == "admin_add_product")
async def admin_add_product_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать добавление товара"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_product_name)
    await callback.message.edit_text("Введите название товара:")
    await callback.answer()


@router.message(AdminStates.waiting_product_name)
async def admin_add_product_name(message: Message, state: FSMContext):
    """Обработка названия товара"""
    if await check_menu_button_and_clear_state(message, state):
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(AdminStates.waiting_product_price)
    await message.answer("Введите цену за единицу (число):")


@router.message(AdminStates.waiting_product_price)
async def admin_add_product_price(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка цены товара"""
    if await check_menu_button_and_clear_state(message, state):
        return
    try:
        price = float(message.text)
        if price <= 0:
            await message.answer("Цена должна быть больше нуля. Попробуйте снова:")
            return
        
        await state.update_data(price=price)
        await state.set_state(AdminStates.waiting_product_category)
        
        # Получаем список категорий и показываем их как кнопки
        stmt = select(Category).where(Category.is_active == True)
        result = await session.execute(stmt)
        categories = result.scalars().all()
        
        if not categories:
            await message.answer(
                "❌ Нет активных категорий. Сначала создайте категорию.\n"
                "Или введите ID категории вручную (или /cancel для отмены):"
            )
            return
        
        # Создаем клавиатуру с категориями
        buttons = []
        for category in categories:
            buttons.append([InlineKeyboardButton(
                text=f"📂 {category.name}",
                callback_data=f"admin_select_category_{category.id}"
            )])
        buttons.append([InlineKeyboardButton(
            text="❌ Отменить",
            callback_data="admin_cancel_add_product"
        )])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await message.answer(
            "📂 <b>Выберите категорию для товара:</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    except ValueError:
        await message.answer("Введите корректную цену (число):")


@router.callback_query(F.data.startswith("admin_select_category_"))
async def admin_select_category(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Обработка выбора категории при добавлении товара"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Проверяем, что пользователь в правильном состоянии
    current_state = await state.get_state()
    if current_state != AdminStates.waiting_product_category:
        await callback.answer("Ошибка: неверное состояние", show_alert=True)
        return
    
    # Извлекаем ID категории
    category_id = int(callback.data.split("_")[-1])
    
    # Проверяем существование категории
    stmt = select(Category).where(Category.id == category_id)
    result = await session.execute(stmt)
    category = result.scalar_one_or_none()
    
    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    
    # Получаем данные из состояния
    data = await state.get_data()
    product_name = data.get("name")
    product_price = data.get("price")
    
    if not product_name or not product_price:
        await callback.answer("Ошибка: данные товара не найдены", show_alert=True)
        await state.clear()
        return
    
    # Сохраняем category_id и переходим к опциональным полям
    await state.update_data(category_id=category_id)
    await state.set_state(AdminStates.waiting_product_description)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="admin_skip_description")]
    ])
    
    await callback.message.edit_text(
        f"📂 Категория выбрана: <b>{category.name}</b>\n\n"
        f"Теперь можно добавить опциональные поля:\n\n"
        f"1️⃣ <b>Описание</b>\n\n"
        f"Введите описание товара или нажмите кнопку для пропуска:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_cancel_add_product")
async def admin_cancel_add_product(callback: CallbackQuery, state: FSMContext):
    """Отмена добавления товара"""
    await state.clear()
    await callback.message.edit_text("❌ Добавление товара отменено")
    await callback.answer()


@router.message(AdminStates.waiting_product_category)
async def admin_add_product_category(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка категории товара (резервный метод через ввод ID)"""
    if await check_menu_button_and_clear_state(message, state):
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено")
        return
    
    try:
        category_id = int(message.text)
        
        stmt = select(Category).where(Category.id == category_id)
        result = await session.execute(stmt)
        category = result.scalar_one_or_none()
        
        if not category:
            await message.answer("Категория не найдена. Введите корректный ID:")
            return
        
        data = await state.get_data()
        
        # Сохраняем category_id и переходим к опциональным полям
        await state.update_data(category_id=category_id)
        await state.set_state(AdminStates.waiting_product_description)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="admin_skip_description")]
        ])
        
        await message.answer(
            f"📂 Категория выбрана: <b>{category.name}</b>\n\n"
            f"Теперь можно добавить опциональные поля:\n\n"
            f"1️⃣ <b>Описание</b>\n\n"
            f"Введите описание товара или нажмите кнопку для пропуска:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    except ValueError:
        await message.answer("Введите корректный ID категории (число) или выберите категорию из списка выше:")


@router.message(AdminStates.waiting_product_description)
async def admin_add_product_description(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка описания товара"""
    if await check_menu_button_and_clear_state(message, state):
        return
    
    description = None
    if message.text and message.text.strip().lower() != "/skip":
        description = message.text.strip()
    
    await state.update_data(description=description)
    await state.set_state(AdminStates.waiting_product_format)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="admin_skip_format")]
    ])
    
    await message.answer(
        f"2️⃣ <b>Формат</b>\n\n"
        f"Введите формат выдаваемых аккаунтов (например: 'login:password') или нажмите кнопку для пропуска:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin_skip_description")
async def admin_skip_description(callback: CallbackQuery, state: FSMContext):
    """Пропустить описание товара"""
    await state.update_data(description=None)
    await state.set_state(AdminStates.waiting_product_format)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="admin_skip_format")]
    ])
    
    await callback.message.edit_text(
        f"2️⃣ <b>Формат</b>\n\n"
        f"Введите формат выдаваемых аккаунтов (например: 'login:password') или нажмите кнопку для пропуска:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer("Описание пропущено")


@router.message(AdminStates.waiting_product_format)
async def admin_add_product_format(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка формата товара"""
    if await check_menu_button_and_clear_state(message, state):
        return
    
    format_info = None
    if message.text and message.text.strip().lower() != "/skip":
        format_info = message.text.strip()
    
    await state.update_data(format_info=format_info)
    await state.set_state(AdminStates.waiting_product_recommendations)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="admin_skip_recommendations")]
    ])
    
    await message.answer(
        f"3️⃣ <b>Рекомендации</b>\n\n"
        f"Введите рекомендации к покупке или нажмите кнопку для пропуска:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin_skip_format")
async def admin_skip_format(callback: CallbackQuery, state: FSMContext):
    """Пропустить формат товара"""
    await state.update_data(format_info=None)
    await state.set_state(AdminStates.waiting_product_recommendations)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="admin_skip_recommendations")]
    ])
    
    await callback.message.edit_text(
        f"3️⃣ <b>Рекомендации</b>\n\n"
        f"Введите рекомендации к покупке или нажмите кнопку для пропуска:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer("Формат пропущен")


@router.message(AdminStates.waiting_product_recommendations)
async def admin_add_product_recommendations(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка рекомендаций и создание товара"""
    if await check_menu_button_and_clear_state(message, state):
        return
    
    recommendations = None
    if message.text and message.text.strip().lower() != "/skip":
        recommendations = message.text.strip()
    
    # Создаем товар
    await _create_product_from_state(state, session, message, recommendations)


@router.callback_query(F.data == "admin_skip_recommendations")
async def admin_skip_recommendations(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Пропустить рекомендации и создать товар"""
    await _create_product_from_state(state, session, callback.message, None)
    await callback.answer("Рекомендации пропущены")


async def _create_product_from_state(state: FSMContext, session: AsyncSession, message_obj, recommendations=None):
    """Вспомогательная функция для создания товара из состояния"""
    from aiogram.types import Message
    
    # Получаем все данные из состояния
    data = await state.get_data()
    product_name = data.get("name")
    product_price = data.get("price")
    category_id = data.get("category_id")
    description = data.get("description")
    format_info = data.get("format_info")
    
    if recommendations is None:
        recommendations = data.get("recommendations")
    
    if not product_name or not product_price or not category_id:
        error_text = "❌ Ошибка: данные товара не найдены"
        if isinstance(message_obj, Message):
            await message_obj.answer(error_text)
        else:
            await message_obj.edit_text(error_text)
        await state.clear()
        return
    
    # Получаем категорию для отображения
    stmt = select(Category).where(Category.id == category_id)
    result = await session.execute(stmt)
    category = result.scalar_one_or_none()
    
    if not category:
        error_text = "❌ Категория не найдена"
        if isinstance(message_obj, Message):
            await message_obj.answer(error_text)
        else:
            await message_obj.edit_text(error_text)
        await state.clear()
        return
    
    # Создаем товар
    product = Product(
        name=product_name,
        price=product_price,
        category_id=category_id,
        stock_count=0,
        description=description,
        format_info=format_info,
        recommendations=recommendations
    )
    session.add(product)
    await session.commit()
    await session.refresh(product)
    
    # Формируем сообщение с информацией о товаре
    text = f"✅ <b>Товар успешно добавлен!</b>\n\n"
    text += f"📦 Название: {product_name}\n"
    text += f"💰 Цена: {product_price:.2f} ₽\n"
    text += f"📂 Категория: {category.name}\n"
    if description:
        text += f"📝 Описание: {description}\n"
    if format_info:
        text += f"📋 Формат: {format_info}\n"
    if recommendations:
        text += f"💡 Рекомендации: {recommendations}\n"
    text += f"\n🆔 ID товара: {product.id}\n\n"
    text += f"Теперь загрузите аккаунты для этого товара через пункт управления."
    
    if isinstance(message_obj, Message):
        await message_obj.answer(text, parse_mode="HTML")
    else:
        await message_obj.edit_text(text, parse_mode="HTML")
    
    await state.clear()


@router.callback_query(F.data == "admin_upload_accounts")
async def admin_upload_accounts_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать загрузку аккаунтов"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_upload_file)
    await callback.message.edit_text(
        "📦 <b>Загрузка аккаунтов</b>\n\n"
        "1. Введите ID товара\n"
        "2. Отправьте файл с аккаунтами (TXT или CSV)\n\n"
        "⚙️ <b>Поддерживаемые форматы:</b>\n"
        "• TXT: каждая строка = один аккаунт (например: <code>login:password</code>)\n"
        "• CSV (из Excel / Google Sheets): каждая строка = один аккаунт,\n"
        "  колонки: <code>login;password;комментарий...</code>\n"
        "  все непустые колонки будут объединены через ':' и сохранены как один аккаунт.",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AdminStates.waiting_upload_file)
async def admin_upload_accounts_process(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка загрузки аккаунтов"""
    if await check_menu_button_and_clear_state(message, state):
        return
    if message.document:
        # Получаем файл
        file = await message.bot.get_file(message.document.file_id)
        file_content = await message.bot.download_file(file.file_path)
        if isinstance(file_content, (bytes, bytearray)):
            content_bytes = file_content
        elif hasattr(file_content, "read"):
            content_bytes = file_content.read()
        else:
            content_bytes = bytes(file_content)
        text_content = content_bytes.decode('utf-8', errors='ignore')
        
        # Нужно получить product_id из состояния или запросить
        data = await state.get_data()
        product_id = data.get("product_id")
        
        if not product_id:
            # Просим ввести ID товара
            try:
                product_id = int(message.text)
                await state.update_data(product_id=product_id)
                await message.answer("Теперь отправьте файл с аккаунтами")
                return
            except:
                await message.answer("Сначала введите ID товара (число):")
                return
        
        # Получаем текущее количество на складе перед загрузкой
        # Проверяем реальное количество аккаунтов из таблицы Account
        stmt_count_before = select(func.count(Account.id)).where(
            Account.product_id == product_id,
            Account.is_sold == False
        )
        result_count_before = await session.execute(stmt_count_before)
        actual_stock_before = result_count_before.scalar() or 0
        stock_was_zero = actual_stock_before == 0
        
        # Загружаем аккаунты
        loaded, duplicates = await upload_accounts_from_file(session, product_id, text_content)
        
        # Коммитим изменения в базе данных
        await session.commit()
        
        # Уведомляем пользователей о поступлении товара, если stock_count был 0 и стал >0
        if loaded > 0 and stock_was_zero:
            from services.notifications import notify_stock_available
            await notify_stock_available(session, product_id, message.bot, check_stock_was_zero=False)
        
        await message.answer(
            f"✅ Загрузка завершена!\n"
            f"Загружено: {loaded} аккаунтов\n"
            f"Пропущено дублей: {duplicates}\n\n"
            f"📦 Товар доступен в каталоге",
            reply_markup=get_admin_catalog_keyboard()
        )
        await state.clear()
    else:
        # Пытаемся получить product_id
        try:
            product_id = int(message.text)
            await state.update_data(product_id=product_id)
            await message.answer("Теперь отправьте файл с аккаунтами")
        except:
            await message.answer("Введите ID товара (число) или отправьте файл:")


# Статистика
@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery, session: AsyncSession):
    """Статистика"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Общее количество пользователей
    stmt_users = select(func.count(User.id))
    result_users = await session.execute(stmt_users)
    total_users = result_users.scalar()
    
    # Общее количество заказов
    stmt_orders = select(func.count(Order.id))
    result_orders = await session.execute(stmt_orders)
    total_orders = result_orders.scalar()
    
    # Заказы по статусам
    stmt_pending = select(func.count(Order.id)).where(Order.status == "ОЖИДАЕТ ОПЛАТЫ")
    result_pending = await session.execute(stmt_pending)
    pending_orders = result_pending.scalar()
    
    stmt_completed = select(func.count(Order.id)).where(Order.status == "ВЫПОЛНЕНО")
    result_completed = await session.execute(stmt_completed)
    completed_orders = result_completed.scalar()
    
    # Общая сумма продаж
    stmt_revenue = select(func.sum(Order.total_amount)).where(Order.status == "ВЫПОЛНЕНО")
    result_revenue = await session.execute(stmt_revenue)
    total_revenue = result_revenue.scalar() or 0
    
    text = f"""📊 <b>Статистика</b>

👥 Всего пользователей: {total_users}
📦 Всего заказов: {total_orders}
⏳ Ожидают оплаты: {pending_orders}
✅ Выполнено: {completed_orders}
💰 Общая выручка: {total_revenue:.2f} ₽
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# Логи
@router.callback_query(F.data == "admin_logs")
async def admin_logs(callback: CallbackQuery, session: AsyncSession):
    """Просмотр логов ошибок"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    stmt = select(Log).where(Log.level == "ERROR").order_by(Log.created_at.desc()).limit(10)
    result = await session.execute(stmt)
    logs = result.scalars().all()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
    ])
    
    if not logs:
        await callback.message.edit_text("Логов ошибок нет", reply_markup=keyboard)
        await callback.answer()
        return
    
    text = "📝 <b>Последние 10 ошибок:</b>\n\n"
    for log in logs:
        text += f"[{log.created_at.strftime('%d.%m %H:%M')}] {log.message[:100]}\n"
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# Управление пользователями
@router.callback_query(F.data == "admin_users")
async def admin_users_menu(callback: CallbackQuery, session: AsyncSession):
    """Меню управления пользователями - показываем список"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Получаем всех пользователей
    stmt = select(User).order_by(User.created_at.desc()).limit(100)
    result = await session.execute(stmt)
    users = result.scalars().all()
    
    if not users:
        await callback.message.edit_text(
            "❌ Пользователи не найдены",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
            ])
        )
        await callback.answer()
        return
    
    # Формируем список пользователей с кнопками
    buttons = []
    text = "👥 <b>Управление пользователями</b>\n\nВыберите пользователя:\n\n"
    
    for user in users[:50]:  # Ограничиваем 50 пользователями
        status = "🔒" if user.is_blocked else "✅"
        username = f"@{user.username}" if user.username else "без username"
        
        # Определяем роль
        role_icon = "👤"
        if user.role == "admin":
            role_icon = "👑"
        elif user.role == "developer":
            role_icon = "⚙️"
        
        # Проверяем, является ли суперадмином из .env
        is_superadmin = user.telegram_id in settings.admin_ids_list or user.telegram_id in settings.developer_ids_list
        superadmin_mark = " ⭐" if is_superadmin else ""
        
        text += f"{status} {role_icon} <b>{user.first_name or 'N/A'}</b> ({username}){superadmin_mark}\n"
        text += f"   ID: {user.telegram_id} | Баланс: {user.balance:.2f} ₽\n\n"
        buttons.append([InlineKeyboardButton(
            text=f"{status} {user.first_name or user.telegram_id}",
            callback_data=f"user_action_{user.telegram_id}"
        )])
    
    if len(users) > 50:
        text += f"\n... и еще {len(users) - 50} пользователей"
    
    buttons.append([InlineKeyboardButton(text="🔒 Массовая блокировка", callback_data="admin_bulk_block_users")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("user_action_"))
async def admin_user_action(callback: CallbackQuery, session: AsyncSession):
    """Действие с пользователем"""
    try:
        logger.debug(f"admin_user_action called with callback.data: {callback.data}")
        if not await is_admin_async(callback.from_user.id, session):
            await callback.answer("Доступ запрещен", show_alert=True)
            return
        
        user_id = int(callback.data.split("_")[2])
        logger.debug(f"Looking for user with telegram_id: {user_id}")

        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        # Определяем текущую роль
        role_text = "👤 Пользователь"
        if user.role == "admin":
            role_text = "👑 Администратор"
        elif user.role == "developer":
            role_text = "⚙️ Разработчик"
        
        # Проверяем, является ли пользователь суперадмином из .env
        is_superadmin = user.telegram_id in settings.admin_ids_list or user.telegram_id in settings.developer_ids_list
        
        # Предлагаем действия с пользователем
        keyboard_buttons = [
            [InlineKeyboardButton(text="🔒 Заблокировать/Разблокировать", callback_data=f"admin_user_block_{user.id}")],
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data=f"admin_user_balance_{user.id}")],
        ]
        
        # Добавляем управление ролями только если пользователь не суперадмин из .env
        if not is_superadmin:
            keyboard_buttons.append([InlineKeyboardButton(text="👑 Управление ролями", callback_data=f"admin_user_role_{user.id}")])
        
        keyboard_buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_users")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

        await callback.message.edit_text(
            f"👤 <b>Пользователь</b>\n\n"
            f"ID: {user.telegram_id}\n"
            f"Username: @{user.username or 'N/A'}\n"
            f"Имя: {user.first_name or 'N/A'}\n"
            f"Роль: {role_text}\n"
            f"Баланс: {user.balance:.2f} ₽\n"
            f"Статус: {'🔒 Заблокирован' if user.is_blocked else '✅ Активен'}\n"
            f"{'⚠️ Суперадмин из .env' if is_superadmin else ''}\n\n"
            f"Выберите действие:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in admin_user_action: {e}", exc_info=True)
        await callback.answer(f"Ошибка: {str(e)[:100]}", show_alert=True)


@router.callback_query(F.data.startswith("admin_user_block_"))
async def admin_user_block(callback: CallbackQuery, session: AsyncSession):
    """Блокировка/разблокировка пользователя"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[3])
    
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    user.is_blocked = not user.is_blocked
    await session.commit()
    
    status = "заблокирован" if user.is_blocked else "разблокирован"
    
    # Отправляем уведомление пользователю
    try:
        if user.is_blocked:
            notification_text = (
                "❌ <b>Вы были заблокированы</b>\n\n"
                "Ваш доступ к боту ограничен администратором.\n"
                "Если вы считаете, что это ошибка, обратитесь в поддержку."
            )
        else:
            notification_text = (
                "✅ <b>Вы были разблокированы</b>\n\n"
                "Ваш доступ к боту восстановлен. Вы можете продолжать пользоваться всеми функциями."
            )
        
        await callback.bot.send_message(
            user.telegram_id,
            notification_text,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send block/unblock notification to user {user.telegram_id}: {e}")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_users")]
    ])
    await callback.message.edit_text(
        f"✅ Пользователь {status}",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "admin_bulk_block_users")
async def admin_bulk_block_users_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать массовую блокировку пользователей"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_bulk_block_users)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_users")]
    ])
    await callback.message.edit_text(
        "🔒 <b>Массовая блокировка пользователей</b>\n\n"
        "Введите ID пользователей через запятую (например: 123456, 789012, 345678):",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AdminStates.waiting_bulk_block_users)
async def admin_bulk_block_users_process(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка массовой блокировки"""
    if await check_menu_button_and_clear_state(message, state):
        return
    
    try:
        user_ids = [int(uid.strip()) for uid in message.text.split(",")]
        blocked = 0
        not_found = 0
        notified = 0
        
        for user_id in user_ids:
            stmt = select(User).where(User.telegram_id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            
            if user:
                user.is_blocked = True
                blocked += 1
                
                # Отправляем уведомление пользователю
                try:
                    notification_text = (
                        "❌ <b>Вы были заблокированы</b>\n\n"
                        "Ваш доступ к боту ограничен администратором.\n"
                        "Если вы считаете, что это ошибка, обратитесь в поддержку."
                    )
                    await message.bot.send_message(
                        user.telegram_id,
                        notification_text,
                        parse_mode="HTML"
                    )
                    notified += 1
                except Exception as e:
                    logger.error(f"Failed to send block notification to user {user.telegram_id}: {e}")
            else:
                not_found += 1
        
        await session.commit()
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_users")]
        ])
        
        await message.answer(
            f"✅ Массовая блокировка завершена!\n\n"
            f"Заблокировано: {blocked}\n"
            f"Уведомлений отправлено: {notified}\n"
            f"Не найдено: {not_found}",
            reply_markup=keyboard
        )
        await state.clear()
        
    except ValueError:
        from utils.keyboards import get_back_keyboard
        await message.answer(
            "Неверный формат. Введите ID через запятую (числа):",
            reply_markup=get_back_keyboard("admin_users")
        )


@router.callback_query(F.data.startswith("admin_user_balance_"))
async def admin_user_balance_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать пополнение баланса пользователя"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[3])
    await state.update_data(user_id=user_id, is_admin_self=False)
    await state.set_state(AdminStates.waiting_balance_amount)
    
    await callback.message.edit_text(
        "💰 <b>Пополнение баланса пользователя</b>\n\n"
        "Введите сумму пополнения (число, можно с точкой, например: 100 или 100.50):"
    )
    await callback.answer()


@router.message(AdminStates.waiting_balance_amount)
async def admin_user_balance_finish(message: Message, state: FSMContext, session: AsyncSession):
    """Завершить пополнение баланса (для пользователя или администратора)"""
    if await check_menu_button_and_clear_state(message, state):
        return
    try:
        amount = float(message.text)
        if amount <= 0:
            await message.answer("Сумма должна быть больше нуля. Попробуйте снова:")
            return
        
        data = await state.get_data()
        is_admin_self = data.get("is_admin_self", False)
        
        if is_admin_self:
            # Пополнение баланса администратора
            user_id = message.from_user.id
            stmt = select(User).where(User.telegram_id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            
            if not user:
                await message.answer("Пользователь не найден. Используйте /start")
                await state.clear()
                return
        else:
            # Пополнение баланса другого пользователя
            user_id = data.get("user_id")
            
            if not user_id:
                await message.answer("Ошибка: не указан пользователь")
                await state.clear()
                return
            
            stmt = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            
            if not user:
                from utils.keyboards import get_back_keyboard
                await message.answer(
                    "Пользователь не найден",
                    reply_markup=get_back_keyboard("admin_users")
                )
                await state.clear()
                return
        
        from sqlalchemy import update
        # Обновляем баланс
        new_balance = user.balance + amount
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(balance=new_balance)
        )
        await session.commit()
        
        # Обновляем объект пользователя для получения нового баланса
        await session.refresh(user)
        
        # Уведомляем пользователя (если это не сам админ пополняет свой баланс)
        if not is_admin_self:
            try:
                await message.bot.send_message(
                    user.telegram_id,
                    f"💰 <b>Баланс пополнен</b>\n\n"
                    f"На ваш баланс зачислено: {amount:.2f} ₽\n"
                    f"Текущий баланс: {user.balance:.2f} ₽",
                    parse_mode="HTML"
                )
            except:
                pass  # Если не удалось отправить сообщение пользователю
        
        # Уведомляем администраторов о пополнении баланса
        try:
            from services.notifications import notify_balance_topup
            await notify_balance_topup(session, user, amount, message.bot)
        except Exception as e:
            logger.error(f"Error notifying about balance topup: {e}")
        
        from utils.keyboards import get_back_keyboard
        if is_admin_self:
            await message.answer(
                f"✅ Ваш баланс пополнен!\n\n"
                f"Сумма: {amount:.2f} ₽\n"
                f"Новый баланс: {user.balance:.2f} ₽",
                reply_markup=get_back_keyboard("admin_menu")
            )
        else:
            await message.answer(
                f"✅ Баланс пользователя пополнен!\n\n"
                f"Пользователь: @{user.username or user.first_name or 'N/A'} (ID: {user.telegram_id})\n"
                f"Сумма: {amount:.2f} ₽\n"
                f"Новый баланс: {user.balance:.2f} ₽",
                reply_markup=get_back_keyboard("admin_users")
            )
        await state.clear()
        
    except ValueError:
        await message.answer("Введите корректную сумму (число, можно с точкой):")


@router.callback_query(F.data == "admin_topup_self")
async def admin_topup_self_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать пополнение баланса администратора"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_balance_amount)
    await state.update_data(is_admin_self=True)  # Флаг, что это пополнение своего баланса
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
    ])
    
    await callback.message.edit_text(
        "💰 <b>Пополнение своего баланса</b>\n\n"
        "Введите сумму пополнения (число, можно с точкой, например: 1000 или 1000.50):",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()





# ========== Р¤РР›Р¬РўР Р« Р—РђРљРђР—РћР’ ==========



@router.callback_query(F.data == "admin_orders_date")
async def admin_orders_date_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Фильтр заказов по дате"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_order_date_from)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_orders")]
    ])
    await callback.message.edit_text(
        "📅 <b>Фильтр заказов по дате</b>\n\n"
        "Введите дату начала (формат: ДД.ММ.ГГГГ, например: 01.01.2024):",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AdminStates.waiting_order_date_from)
async def admin_orders_date_from(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка даты начала"""
    if await check_menu_button_and_clear_state(message, state):
        return
    try:
        date_from = datetime.strptime(message.text, "%d.%m.%Y")
        await state.update_data(date_from=date_from)
        await state.set_state(AdminStates.waiting_order_date_to)
        await message.answer("Введите дату окончания (формат: ДД.ММ.ГГГГ):")
    except ValueError:
        await message.answer("Неверный формат даты. Используйте ДД.ММ.ГГГГ (например: 01.01.2024):")


@router.message(AdminStates.waiting_order_date_to)
async def admin_orders_date_to(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка даты окончания и показ результатов"""
    if await check_menu_button_and_clear_state(message, state):
        return
    try:
        date_to = datetime.strptime(message.text, "%d.%m.%Y")
        data = await state.get_data()
        date_from = data.get("date_from")
        
        stmt = select(Order).where(
            Order.created_at >= date_from,
            Order.created_at <= date_to
        ).order_by(Order.created_at.desc()).limit(50)
        result = await session.execute(stmt)
        orders = result.scalars().all()
        
        if not orders:
            await message.answer("Заказов за указанный период не найдено")
            await state.clear()
            return
        
        text = f"📅 <b>Заказы с {date_from.strftime('%d.%m.%Y')} по {date_to.strftime('%d.%m.%Y')}</b>\n\n"
        for order in orders:
            text += f"#{order.id} - {order.status} - {order.total_amount:.2f} ₽ - {order.created_at.strftime('%d.%m.%Y')}\n"
        
        await message.answer(text, parse_mode="HTML")
        await state.clear()
    except ValueError:
        await message.answer("Неверный формат даты. Используйте ДД.ММ.ГГГГ:")


@router.callback_query(F.data == "admin_orders_status")
async def admin_orders_status_filter(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Фильтр заказов по статусу"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ожидает оплаты", callback_data="filter_status_ОЖИДАЕТ ОПЛАТЫ")],
        [InlineKeyboardButton(text="✅ Оплачено", callback_data="filter_status_ОПЛАЧЕНО")],
        [InlineKeyboardButton(text="✔️ Выполнено", callback_data="filter_status_ВЫПОЛНЕНО")],
        [InlineKeyboardButton(text="❌ Отменено", callback_data="filter_status_ОТМЕНЕНО")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_orders")]
    ])
    
    await callback.message.edit_text("📊 Выберите статус:", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("filter_status_"))
async def admin_orders_status_result(callback: CallbackQuery, session: AsyncSession):
    """Результаты фильтра по статусу"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    status = callback.data.replace("filter_status_", "")
    
    stmt = select(Order).where(Order.status == status).order_by(Order.created_at.desc()).limit(50)
    result = await session.execute(stmt)
    orders = result.scalars().all()
    
    if not orders:
        await callback.message.edit_text(f"Заказов со статусом '{status}' не найдено")
        await callback.answer()
        return
    
    text = f"📊 <b>Заказы со статусом: {status}</b>\n\n"
    for order in orders:
        text += f"#{order.id} - {order.total_amount:.2f} ₽ - {order.created_at.strftime('%d.%m.%Y %H:%M')}\n"
    
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_orders_user")
async def admin_orders_user_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Фильтр заказов по пользователю"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_order_user_filter)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_orders")]
    ])
    await callback.message.edit_text("👤 Введите Telegram ID пользователя:", reply_markup=keyboard)
    await callback.answer()


@router.message(AdminStates.waiting_order_user_filter)
async def admin_orders_user_result(message: Message, state: FSMContext, session: AsyncSession):
    """Результаты фильтра по пользователю"""
    if await check_menu_button_and_clear_state(message, state):
        return
    try:
        telegram_id = int(message.text)
        
        stmt_user = select(User).where(User.telegram_id == telegram_id)
        result_user = await session.execute(stmt_user)
        user = result_user.scalar_one_or_none()
        
        if not user:
            await message.answer("Пользователь не найден")
            await state.clear()
            return
        
        stmt = select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc()).limit(50)
        result = await session.execute(stmt)
        orders = result.scalars().all()
        
        if not orders:
            await message.answer(f"Заказов у пользователя @{user.username or 'N/A'} не найдено")
            await state.clear()
            return
        
        text = f"👤 <b>Заказы пользователя @{user.username or user.first_name or 'N/A'}</b>\n\n"
        for order in orders:
            text += f"#{order.id} - {order.status} - {order.total_amount:.2f} ₽ - {order.created_at.strftime('%d.%m.%Y')}\n"
        
        await message.answer(text, parse_mode="HTML")
        await state.clear()
    except ValueError:
        await message.answer("Введите корректный Telegram ID (число):")

# ========== РЕДАКТИРОВАНИЕ ТОВАРОВ ==========

EDIT_PRODUCTS_PAGE_SIZE = 10


async def render_edit_products_list(
    target_message,
    state: FSMContext,
    session: AsyncSession,
    page: int = 1
):
    """Отрисовка списка товаров с пагинацией, поиском и сортировкой"""
    data = await state.get_data()
    query_text = data.get("edit_products_query")
    category_id = data.get("edit_products_category_id")
    sort_mode = data.get("edit_products_sort", "recent")

    stmt = select(Product)
    count_stmt = select(func.count(Product.id))

    if sort_mode == "category":
        stmt = stmt.join(Category)
        count_stmt = count_stmt.join(Category)

    if query_text:
        stmt = stmt.where(Product.name.ilike(f"%{query_text}%"))
        count_stmt = count_stmt.where(Product.name.ilike(f"%{query_text}%"))

    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
        count_stmt = count_stmt.where(Product.category_id == category_id)

    if sort_mode == "category":
        stmt = stmt.order_by(Category.name.asc(), Product.name.asc())
    else:
        stmt = stmt.order_by(Product.id.desc())

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one() or 0

    total_pages = max(1, (total + EDIT_PRODUCTS_PAGE_SIZE - 1) // EDIT_PRODUCTS_PAGE_SIZE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * EDIT_PRODUCTS_PAGE_SIZE

    result = await session.execute(stmt.limit(EDIT_PRODUCTS_PAGE_SIZE).offset(offset))
    products = result.scalars().all()

    if not products:
        await target_message.edit_text(
            "❌ Нет товаров для редактирования по заданным фильтрам.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔎 Сбросить фильтры", callback_data="admin_edit_products_reset")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_catalog")]
            ])
        )
        return

    # Подгружаем категории для отображения
    category_map = {}
    if sort_mode == "category" or category_id:
        stmt_cat = select(Category)
        result_cat = await session.execute(stmt_cat)
        categories = result_cat.scalars().all()
        category_map = {c.id: c.name for c in categories}

    buttons = []
    for product in products:
        category_label = category_map.get(product.category_id, "")
        if category_label:
            text = f"#{product.id} · {product.name} · {category_label}"
        else:
            text = f"#{product.id} · {product.name}"
        buttons.append([InlineKeyboardButton(
            text=text,
            callback_data=f"admin_edit_product_select_{product.id}"
        )])

    # Навигация
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"admin_edit_products_page_{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="admin_edit_products_page_info"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"admin_edit_products_page_{page + 1}"))
    buttons.append(nav_buttons)

    # Фильтры и поиск
    sort_label = "категория" if sort_mode == "category" else "последние"
    filter_row = [
        InlineKeyboardButton(text="🔍 Поиск", callback_data="admin_edit_products_search"),
        InlineKeyboardButton(text="📂 Категория", callback_data="admin_edit_products_filter_category"),
        InlineKeyboardButton(text=f"↕️ Сортировка: {sort_label}", callback_data="admin_edit_products_toggle_sort")
    ]
    buttons.append(filter_row)
    buttons.append([InlineKeyboardButton(text="🔎 Сбросить фильтры", callback_data="admin_edit_products_reset")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_catalog")])

    await state.update_data(edit_products_page=page)

    await target_message.edit_text(
        "✏️ <b>Выберите товар для редактирования:</b>\n"
        f"Всего товаров: {total}\n"
        f"Фильтр: {query_text or '—'} | Категория: {category_id or '—'} | Сорт: {sort_label}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "admin_edit_product")
async def admin_edit_product_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать редактирование товара"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_edit_product_id)
    await state.update_data(
        edit_products_page=1,
        edit_products_query=None,
        edit_products_category_id=None,
        edit_products_sort="recent"
    )
    await render_edit_products_list(callback.message, state, session, page=1)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_edit_products_page_"))
async def admin_edit_products_page(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Пагинация списка товаров"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    # Проверяем, что это не кнопка "info" (показывает текущую страницу)
    last_part = callback.data.split("_")[-1]
    if last_part == "info":
        # Это кнопка с информацией о странице, просто отвечаем без действий
        await callback.answer()
        return
    
    try:
        page = int(last_part)
    except ValueError:
        await callback.answer("Ошибка: некорректный номер страницы", show_alert=True)
        return
    
    await render_edit_products_list(callback.message, state, session, page=page)
    await callback.answer()


@router.callback_query(F.data == "admin_edit_products_search")
async def admin_edit_products_search(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Запрос поискового текста"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_edit_product_search)
    await callback.message.edit_text(
        "🔍 Введите часть названия товара для поиска:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_edit_product")]
        ])
    )
    await callback.answer()


@router.message(AdminStates.waiting_edit_product_search)
async def admin_edit_products_search_apply(message: Message, state: FSMContext, session: AsyncSession):
    """Применение поиска по названию"""
    if await check_menu_button_and_clear_state(message, state):
        return

    query_text = (message.text or "").strip()
    if not query_text:
        await message.answer("Введите текст для поиска.")
        return

    await state.update_data(edit_products_query=query_text, edit_products_page=1)
    await state.set_state(AdminStates.waiting_edit_product_id)
    await render_edit_products_list(message, state, session, page=1)


@router.callback_query(F.data == "admin_edit_products_filter_category")
async def admin_edit_products_filter_category(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Выбор категории для фильтра"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    stmt = select(Category).where(Category.is_active == True)
    result = await session.execute(stmt)
    categories = result.scalars().all()

    if not categories:
        await callback.answer("Нет активных категорий", show_alert=True)
        return

    buttons = []
    for cat in categories:
        buttons.append([InlineKeyboardButton(
            text=f"📂 {cat.name}",
            callback_data=f"admin_edit_products_set_category_{cat.id}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_edit_product")])

    await callback.message.edit_text(
        "📂 Выберите категорию для фильтра:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_edit_products_set_category_"))
async def admin_edit_products_set_category(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Установка фильтра по категории"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    category_id = int(callback.data.split("_")[-1])
    await state.update_data(edit_products_category_id=category_id, edit_products_page=1)
    await state.set_state(AdminStates.waiting_edit_product_id)
    await render_edit_products_list(callback.message, state, session, page=1)
    await callback.answer()


@router.callback_query(F.data == "admin_edit_products_toggle_sort")
async def admin_edit_products_toggle_sort(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Переключение сортировки"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    data = await state.get_data()
    current = data.get("edit_products_sort", "recent")
    new_sort = "category" if current == "recent" else "recent"
    await state.update_data(edit_products_sort=new_sort, edit_products_page=1)
    await render_edit_products_list(callback.message, state, session, page=1)
    await callback.answer()


@router.callback_query(F.data == "admin_edit_products_reset")
async def admin_edit_products_reset(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Сброс фильтров"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    await state.update_data(
        edit_products_page=1,
        edit_products_query=None,
        edit_products_category_id=None,
        edit_products_sort="recent"
    )
    await state.set_state(AdminStates.waiting_edit_product_id)
    await render_edit_products_list(callback.message, state, session, page=1)
    await callback.answer()

@router.callback_query(F.data.startswith("admin_edit_product_select_"))
async def admin_edit_product_select_callback(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Выбор товара для редактирования через кнопки"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    product_id = int(callback.data.split("_")[-1])
    stmt = select(Product).where(Product.id == product_id)
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    await state.update_data(product_id=product_id)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Название", callback_data="edit_field_name")],
        [InlineKeyboardButton(text="💰 Цена", callback_data="edit_field_price")],
        [InlineKeyboardButton(text="📄 Описание", callback_data="edit_field_description")],
        [InlineKeyboardButton(text="📂 Категория", callback_data="edit_field_category")],
        [InlineKeyboardButton(text="✅ Активность", callback_data="edit_field_active")],
        [InlineKeyboardButton(text="ℹ️ Формат", callback_data="edit_field_format")],
        [InlineKeyboardButton(text="💡 Рекомендации", callback_data="edit_field_recommendations")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_catalog")]
    ])

    await callback.message.edit_text(
        f"✏️ <b>Редактирование товара</b>\n\n"
        f"ID: {product.id}\n"
        f"Название: {product.name}\n"
        f"Цена: {product.price:.2f} ₽\n"
        f"Остаток: {product.stock_count} шт.\n"
        f"Активен: {'Да' if product.is_active else 'Нет'}\n\n"
        f"Выберите поле для редактирования:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_edit_product_field)
    await callback.answer()


@router.message(AdminStates.waiting_edit_product_id)
async def admin_edit_product_select(message: Message, state: FSMContext, session: AsyncSession):
    """Выбор поля для редактирования"""
    if await check_menu_button_and_clear_state(message, state):
        return
    try:
        product_id = int(message.text)
        
        stmt = select(Product).where(Product.id == product_id)
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()
        
        if not product:
            await message.answer("Товар не найден. Введите корректный ID:")
            return
        
        await state.update_data(product_id=product_id)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Название", callback_data="edit_field_name")],
            [InlineKeyboardButton(text="💰 Цена", callback_data="edit_field_price")],
            [InlineKeyboardButton(text="📄 Описание", callback_data="edit_field_description")],
            [InlineKeyboardButton(text="📂 Категория", callback_data="edit_field_category")],
            [InlineKeyboardButton(text="✅ Активность", callback_data="edit_field_active")],
            [InlineKeyboardButton(text="ℹ️ Формат", callback_data="edit_field_format")],
            [InlineKeyboardButton(text="💡 Рекомендации", callback_data="edit_field_recommendations")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_catalog")]
        ])
        
        await message.answer(
            f"✏️ <b>Редактирование товара</b>\n\n"
            f"ID: {product.id}\n"
            f"Название: {product.name}\n"
            f"Цена: {product.price:.2f} ₽\n"
            f"Остаток: {product.stock_count} шт.\n"
            f"Активен: {'Да' if product.is_active else 'Нет'}\n\n"
            f"Выберите поле для редактирования:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.set_state(AdminStates.waiting_edit_product_field)
        
    except ValueError:
        await message.answer("Введите корректный ID товара (число):")


@router.callback_query(F.data.startswith("edit_field_"))
async def admin_edit_product_field(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Обработка выбора поля"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    field = callback.data.replace("edit_field_", "")
    data = await state.get_data()
    product_id = data.get("product_id")
    
    if not product_id:
        await callback.answer("Ошибка: товар не выбран", show_alert=True)
        return
    
    # Для активности - сразу переключаем
    if field == "active":
        stmt = select(Product).where(Product.id == product_id)
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()
        
        if product:
            product.is_active = not product.is_active
            await session.commit()
            await callback.answer(f"Активность изменена на: {'Да' if product.is_active else 'Нет'}", show_alert=True)
            await callback.message.edit_text(f"✅ Товар {'активирован' if product.is_active else 'деактивирован'}")
        return
    
    # Для категории - показываем список
    if field == "category":
        stmt = select(Category)
        result = await session.execute(stmt)
        categories = result.scalars().all()
        
        buttons = []
        for cat in categories:
            buttons.append([InlineKeyboardButton(
                text=cat.name,
                callback_data=f"set_category_{cat.id}"
            )])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_edit_product")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("📂 Выберите категорию:", reply_markup=keyboard)
        await callback.answer()
        return
    
    # Для остальных полей - запрашиваем новое значение
    field_names = {
        "name": "название",
        "price": "цену (число)",
        "description": "описание",
        "format": "формат",
        "recommendations": "рекомендации"
    }
    
    await state.update_data(edit_field=field)
    await state.set_state(AdminStates.waiting_edit_product_value)
    await callback.message.edit_text(f"Введите новое значение для поля '{field_names.get(field, field)}':")
    await callback.answer()


@router.callback_query(F.data.startswith("set_category_"))
async def admin_edit_product_set_category(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Установка категории"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    category_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    product_id = data.get("product_id")
    
    stmt = select(Product).where(Product.id == product_id)
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()
    
    if product:
        product.category_id = category_id
        await session.commit()
        await callback.answer("Категория изменена", show_alert=True)
        await callback.message.edit_text("✅ Категория товара обновлена")
    else:
        await callback.answer("Товар не найден", show_alert=True)
    
    await state.clear()


@router.message(AdminStates.waiting_edit_product_value)
async def admin_edit_product_value(message: Message, state: FSMContext, session: AsyncSession):
    """Сохранение нового значения"""
    if await check_menu_button_and_clear_state(message, state):
        return
    data = await state.get_data()
    product_id = data.get("product_id")
    field = data.get("edit_field")
    
    if not product_id or not field:
        await message.answer("Ошибка. Начните редактирование заново.")
        await state.clear()
        return
    
    stmt = select(Product).where(Product.id == product_id)
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()
    
    if not product:
        await message.answer("Товар не найден")
        await state.clear()
        return
    
    try:
        if field == "price":
            value = float(message.text)
            if value <= 0:
                await message.answer("Цена должна быть больше нуля. Попробуйте снова:")
                return
            product.price = value
        elif field == "name":
            product.name = message.text.strip()
        elif field == "description":
            product.description = message.text.strip()
        elif field == "format":
            product.format_info = message.text.strip()
        elif field == "recommendations":
            product.recommendations = message.text.strip()
        
        await session.commit()
        await message.answer(f"✅ Поле '{field}' обновлено!")
        await state.clear()
        
    except ValueError:
        await message.answer("Неверный формат. Попробуйте снова:")


# ========== УДАЛЕНИЕ ТОВАРОВ ==========

@router.callback_query(F.data == "admin_delete_product")
async def admin_delete_product_start(callback: CallbackQuery, session: AsyncSession):
    """Начать удаление товара - показываем список"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Получаем все товары
    stmt = select(Product).order_by(Product.name)
    result = await session.execute(stmt)
    products = result.scalars().all()
    
    if not products:
        await callback.message.edit_text(
            "❌ Товары не найдены",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_catalog")]
            ])
        )
        await callback.answer()
        return
    
    # Формируем список товаров с кнопками
    buttons = []
    text = "🗑️ <b>Удаление товара</b>\n\nВыберите товар для удаления:\n\n"
    
    for product in products[:50]:  # Ограничиваем 50 товарами
        status = "✅" if product.is_active else "❌"
        text += f"{status} <b>{product.name}</b> (ID: {product.id}, цена: {product.price:.2f} ₽, остаток: {product.stock_count})\n"
        buttons.append([InlineKeyboardButton(
            text=f"🗑️ {product.name}",
            callback_data=f"delete_product_{product.id}"
        )])
    
    if len(products) > 50:
        text += f"\n... и еще {len(products) - 50} товаров"
    
    buttons.append([InlineKeyboardButton(text="🗑️ Массовое удаление", callback_data="admin_bulk_delete_products")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_catalog")])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delete_product_"))
async def admin_delete_product_confirm(callback: CallbackQuery, session: AsyncSession):
    """Подтверждение удаления товара"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[2])

    stmt = select(Product).where(Product.id == product_id)
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    # Проверяем, есть ли заказы с этим товаром
    stmt_orders = select(func.count(Order.id)).where(Order.product_id == product_id)
    result_orders = await session.execute(stmt_orders)
    orders_count = result_orders.scalar()

    keyboard = get_confirm_keyboard("delete_product", product_id)
    text = f"⚠️ <b>Подтвердите удаление</b>\n\n"
    text += f"Товар: <b>{product.name}</b>\n"
    text += f"Цена: {product.price:.2f} ₽\n"
    text += f"Остаток: {product.stock_count} шт.\n"
    if orders_count > 0:
        text += f"Заказов с этим товаром: {orders_count}\n"
    text += f"\nВы уверены?"
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_delete_product_"))
async def admin_delete_product_execute(callback: CallbackQuery, session: AsyncSession):
    """Выполнить удаление товара"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[3])
    
    stmt = select(Product).where(Product.id == product_id)
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()
    
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    
    # Проверяем, есть ли заказы с этим товаром
    stmt_orders = select(func.count(Order.id)).where(Order.product_id == product_id)
    result_orders = await session.execute(stmt_orders)
    orders_count = result_orders.scalar()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_catalog")]
    ])
    
    if orders_count > 0:
        # Не удаляем, а деактивируем
        product.is_active = False
        await session.commit()
        await callback.message.edit_text(
            f"✅ Товар деактивирован (есть {orders_count} заказов)",
            reply_markup=keyboard
        )
    else:
        # Удаляем полностью
        await session.delete(product)
        await session.commit()
        await callback.message.edit_text(
            "✅ Товар удален",
            reply_markup=keyboard
        )
    
    await callback.answer()


# ========== НАСТРОЙКИ ==========

@router.callback_query(F.data == "admin_settings")
async def admin_settings_menu(callback: CallbackQuery, session: AsyncSession):
    """Меню настроек"""
    if not is_developer(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен. Требуются права разработчика.", show_alert=True)
        return
    
    # Получаем текущие настройки
    stmt = select(Setting)
    result = await session.execute(stmt)
    settings_list = result.scalars().all()
    
    text = "⚙️ <b>Настройки бота</b>\n\n"
    text += "Доступные настройки:\n"
    text += "• welcome_text - Приветственное сообщение\n"
    text += "• support_chat - Контакт поддержки\n"
    text += "• faq_text - Текст FAQ\n"
    text += "• rules_text - Текст правил\n\n"
    
    if settings_list:
        text += "Текущие значения:\n"
        for s in settings_list:
            value_preview = s.value[:50] + "..." if s.value and len(s.value) > 50 else (s.value or "не установлено")
            text += f"• {s.key}: {value_preview}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать настройку", callback_data="admin_setting_edit")],
        [InlineKeyboardButton(text="📋 Список настроек", callback_data="admin_setting_list")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_setting_edit")
async def admin_setting_edit_start(callback: CallbackQuery, state: FSMContext):
    """Начать редактирование настройки"""
    if not is_developer(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👋 Приветствие", callback_data="setting_key_welcome_text")],
        [InlineKeyboardButton(text="💬 Поддержка", callback_data="setting_key_support_chat")],
        [InlineKeyboardButton(text="❓ FAQ", callback_data="setting_key_faq_text")],
        [InlineKeyboardButton(text="📜 Правила", callback_data="setting_key_rules_text")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_settings")]
    ])
    
    await callback.message.edit_text("Выберите настройку для редактирования:", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("setting_key_"))
async def admin_setting_edit_key(callback: CallbackQuery, state: FSMContext):
    """Выбор ключа настройки"""
    if not is_developer(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    key = callback.data.replace("setting_key_", "")
    await state.update_data(setting_key=key)
    await state.set_state(AdminStates.waiting_setting_edit_value)
    
    await callback.message.edit_text(f"Введите новое значение для '{key}':")
    await callback.answer()


@router.message(AdminStates.waiting_setting_edit_value)
async def admin_setting_edit_value(message: Message, state: FSMContext, session: AsyncSession):
    """Сохранение настройки"""
    if await check_menu_button_and_clear_state(message, state):
        return
    data = await state.get_data()
    key = data.get("setting_key")
    
    if not key:
        await message.answer("Ошибка. Начните редактирование заново.")
        await state.clear()
        return
    
    # Ищем существующую настройку
    stmt = select(Setting).where(Setting.key == key)
    result = await session.execute(stmt)
    setting = result.scalar_one_or_none()
    
    if setting:
        setting.value = message.text
    else:
        setting = Setting(key=key, value=message.text)
        session.add(setting)
    
    await session.commit()
    await message.answer(f"✅ Настройка '{key}' обновлена!")
    await state.clear()


@router.callback_query(F.data == "admin_setting_list")
async def admin_setting_list(callback: CallbackQuery, session: AsyncSession):
    """Список всех настроек"""
    if not is_developer(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    stmt = select(Setting)
    result = await session.execute(stmt)
    settings_list = result.scalars().all()
    
    if not settings_list:
        await callback.message.edit_text("Настроек пока нет")
        await callback.answer()
        return
    
    text = "📋 <b>Все настройки:</b>\n\n"
    for s in settings_list:
        text += f"<b>{s.key}</b>\n{s.value or 'не установлено'}\n\n"
    
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


# ========== УПРАВЛЕНИЕ АККАУНТАМИ ==========

@router.callback_query(F.data == "admin_manage_accounts")
async def admin_manage_accounts_menu(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Меню управления аккаунтами - выбор товара"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Получаем все товары
    stmt = select(Product).where(Product.is_active == True).order_by(Product.name)
    result = await session.execute(stmt)
    products = result.scalars().all()
    
    if not products:
        await callback.message.edit_text(
            "❌ Нет активных товаров. Сначала создайте товар.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_catalog")]
            ])
        )
        await callback.answer()
        return
    
    buttons = []
    for product in products:
        # Получаем количество аккаунтов на складе
        stmt_count = select(func.count(Account.id)).where(
            Account.product_id == product.id,
            Account.is_sold == False
        )
        result_count = await session.execute(stmt_count)
        stock_count = result_count.scalar() or 0
        
        buttons.append([InlineKeyboardButton(
            text=f"📦 {product.name} (остаток: {stock_count})",
            callback_data=f"admin_accounts_product_{product.id}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_catalog")])
    
    await callback.message.edit_text(
        "📦 <b>Управление аккаунтами</b>\n\n"
        "Выберите товар для управления аккаунтами:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_accounts_product_"))
async def admin_accounts_product_menu(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Меню действий с аккаунтами для выбранного товара"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[3])
    
    stmt = select(Product).where(Product.id == product_id)
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()
    
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    
    # Получаем статистику аккаунтов
    stmt_total = select(func.count(Account.id)).where(Account.product_id == product_id)
    result_total = await session.execute(stmt_total)
    total_accounts = result_total.scalar() or 0
    
    stmt_available = select(func.count(Account.id)).where(
        Account.product_id == product_id,
        Account.is_sold == False
    )
    result_available = await session.execute(stmt_available)
    available_accounts = result_available.scalar() or 0
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data=f"admin_account_add_{product_id}")],
        [InlineKeyboardButton(text="📥 Импорт из файла", callback_data=f"admin_account_import_{product_id}")],
        [InlineKeyboardButton(text="🗑️ Удалить аккаунт", callback_data=f"admin_account_delete_{product_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_manage_accounts")]
    ])
    
    await callback.message.edit_text(
        f"📦 <b>Управление аккаунтами</b>\n\n"
        f"Товар: <b>{product.name}</b>\n"
        f"Всего аккаунтов: {total_accounts}\n"
        f"Доступно на складе: {available_accounts}\n\n"
        f"Выберите действие:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_account_add_"))
async def admin_account_add_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать добавление аккаунта"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[3])
    
    stmt = select(Product).where(Product.id == product_id)
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()
    
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    
    await state.update_data(account_product_id=product_id)
    await state.set_state(AdminStates.waiting_add_account)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_accounts_product_{product_id}")]
    ])
    
    await callback.message.edit_text(
        f"➕ <b>Добавление аккаунта</b>\n\n"
        f"Товар: <b>{product.name}</b>\n\n"
        f"Введите данные аккаунта (например: <code>login:password</code>):",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AdminStates.waiting_add_account)
async def admin_account_add_process(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка добавления аккаунта"""
    if await check_menu_button_and_clear_state(message, state):
        return
    
    data = await state.get_data()
    product_id = data.get("account_product_id")
    
    if not product_id:
        await message.answer("Ошибка: товар не выбран. Начните заново.")
        await state.clear()
        return
    
    account_data = message.text.strip()
    
    if not account_data:
        await message.answer("Введите данные аккаунта:")
        return
    
    # Проверяем на дубликаты
    stmt = select(Account).where(
        Account.product_id == product_id,
        Account.account_data == account_data
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    
    if existing:
        await message.answer("❌ Такой аккаунт уже существует. Введите другой:")
        return
    
    # Создаем аккаунт
    account = Account(
        product_id=product_id,
        account_data=account_data,
        is_sold=False
    )
    session.add(account)
    
    # Получаем текущее количество на складе перед обновлением
    # Проверяем реальное количество аккаунтов из таблицы Account
    stmt_count_before = select(func.count(Account.id)).where(
        Account.product_id == product_id,
        Account.is_sold == False
    )
    result_count_before = await session.execute(stmt_count_before)
    actual_stock_before = result_count_before.scalar() or 0
    stock_was_zero = actual_stock_before == 0
    
    # Обновляем количество на складе
    await session.execute(
        update(Product)
        .where(Product.id == product_id)
        .values(stock_count=Product.stock_count + 1)
    )
    
    await session.commit()
    
    stmt_product = select(Product).where(Product.id == product_id)
    result_product = await session.execute(stmt_product)
    product = result_product.scalar_one_or_none()
    
    # Уведомляем пользователей о поступлении товара, если stock_count был 0 и стал >0
    if stock_was_zero:
        from services.notifications import notify_stock_available
        await notify_stock_available(session, product_id, message.bot, check_stock_was_zero=False)
    
    await message.answer(
        f"✅ Аккаунт успешно добавлен к товару <b>{product.name if product else 'N/A'}</b>!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_accounts_product_{product_id}")]
        ])
    )
    await state.clear()


@router.callback_query(F.data.startswith("admin_account_import_"))
async def admin_account_import_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать импорт аккаунтов из файла"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[3])
    
    stmt = select(Product).where(Product.id == product_id)
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()
    
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    
    await state.update_data(account_import_product_id=product_id)
    await state.set_state(AdminStates.waiting_import_accounts_file)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_accounts_product_{product_id}")]
    ])
    
    await callback.message.edit_text(
        f"📥 <b>Импорт аккаунтов</b>\n\n"
        f"Товар: <b>{product.name}</b>\n\n"
        f"Отправьте текстовый файл с аккаунтами.\n\n"
        f"<b>Формат:</b> каждая строка = один аккаунт\n"
        f"Пример:\n"
        f"<code>login1:password1</code>\n"
        f"<code>login2:password2</code>\n"
        f"<code>login3:password3</code>\n\n"
        f"Поддерживаются форматы TXT и CSV.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AdminStates.waiting_import_accounts_file)
async def admin_account_import_process(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка импорта аккаунтов из файла"""
    if await check_menu_button_and_clear_state(message, state):
        return
    
    if not message.document:
        await message.answer("Пожалуйста, отправьте текстовый файл с аккаунтами.")
        return
    
    data = await state.get_data()
    product_id = data.get("account_import_product_id")
    
    if not product_id:
        await message.answer("Ошибка: товар не выбран. Начните заново.")
        await state.clear()
        return
    
    try:
        # Получаем файл
        file = await message.bot.get_file(message.document.file_id)
        file_content = await message.bot.download_file(file.file_path)
        
        if isinstance(file_content, (bytes, bytearray)):
            content_bytes = file_content
        elif hasattr(file_content, "read"):
            content_bytes = file_content.read()
        else:
            content_bytes = bytes(file_content)
        
        text_content = content_bytes.decode('utf-8', errors='ignore')
        
        # Получаем текущее количество на складе перед импортом
        # Проверяем реальное количество аккаунтов из таблицы Account
        stmt_count_before = select(func.count(Account.id)).where(
            Account.product_id == product_id,
            Account.is_sold == False
        )
        result_count_before = await session.execute(stmt_count_before)
        actual_stock_before = result_count_before.scalar() or 0
        stock_was_zero = actual_stock_before == 0
        
        # Используем существующую функцию импорта
        loaded, duplicates = await upload_accounts_from_file(session, product_id, text_content)
        
        # Коммитим изменения в базе данных
        await session.commit()
        
        stmt_product = select(Product).where(Product.id == product_id)
        result_product = await session.execute(stmt_product)
        product = result_product.scalar_one_or_none()
        
        # Уведомляем пользователей о поступлении товара, если stock_count был 0 и стал >0
        if loaded > 0 and stock_was_zero:
            from services.notifications import notify_stock_available
            await notify_stock_available(session, product_id, message.bot, check_stock_was_zero=False)
        
        await message.answer(
            f"✅ <b>Импорт завершен!</b>\n\n"
            f"Товар: <b>{product.name if product else 'N/A'}</b>\n"
            f"Загружено аккаунтов: {loaded}\n"
            f"Пропущено дублей: {duplicates}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_accounts_product_{product_id}")]
            ])
        )
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error importing accounts: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка при импорте: {str(e)}")
        await state.clear()


@router.callback_query(F.data.startswith("admin_account_delete_"))
async def admin_account_delete_start(callback: CallbackQuery, session: AsyncSession):
    """Начать удаление аккаунта - показываем список"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[3])
    
    stmt = select(Product).where(Product.id == product_id)
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()
    
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    
    # Получаем все доступные аккаунты (не проданные)
    stmt_accounts = select(Account).where(
        Account.product_id == product_id,
        Account.is_sold == False
    ).order_by(Account.id.desc()).limit(50)
    result_accounts = await session.execute(stmt_accounts)
    accounts = result_accounts.scalars().all()
    
    if not accounts:
        await callback.message.edit_text(
            f"❌ Нет доступных аккаунтов для удаления\n\n"
            f"Товар: <b>{product.name}</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_accounts_product_{product_id}")]
            ]),
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    # Формируем список аккаунтов с кнопками
    buttons = []
    text = f"🗑️ <b>Удаление аккаунта</b>\n\n"
    text += f"Товар: <b>{product.name}</b>\n"
    text += f"Доступно для удаления: {len(accounts)}\n\n"
    text += f"Выберите аккаунт для удаления:\n\n"
    
    for account in accounts:
        # Показываем первые 20 символов данных аккаунта
        account_preview = account.account_data[:20] + "..." if len(account.account_data) > 20 else account.account_data
        text += f"ID: {account.id} - {account_preview}\n"
        buttons.append([InlineKeyboardButton(
            text=f"🗑️ ID: {account.id}",
            callback_data=f"delete_account_{account.id}"
        )])
    
    if len(accounts) == 50:
        text += f"\n... показано 50 из доступных аккаунтов"
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_accounts_product_{product_id}")])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delete_account_"))
async def admin_delete_account_confirm(callback: CallbackQuery, session: AsyncSession):
    """Подтверждение удаления аккаунта"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    account_id = int(callback.data.split("_")[2])
    
    stmt = select(Account).where(Account.id == account_id)
    result = await session.execute(stmt)
    account = result.scalar_one_or_none()
    
    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    if account.is_sold:
        await callback.answer("Нельзя удалить проданный аккаунт", show_alert=True)
        return
    
    # Получаем информацию о товаре
    stmt_product = select(Product).where(Product.id == account.product_id)
    result_product = await session.execute(stmt_product)
    product = result_product.scalar_one_or_none()
    
    # Показываем превью данных аккаунта (первые 50 символов)
    account_preview = account.account_data[:50] + "..." if len(account.account_data) > 50 else account.account_data
    
    keyboard = get_confirm_keyboard("delete_account", account_id)
    text = f"⚠️ <b>Подтвердите удаление</b>\n\n"
    text += f"Товар: <b>{product.name if product else 'N/A'}</b>\n"
    text += f"ID аккаунта: {account.id}\n"
    text += f"Данные: <code>{account_preview}</code>\n\n"
    text += f"Вы уверены?"
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_delete_account_"))
async def admin_delete_account_execute(callback: CallbackQuery, session: AsyncSession):
    """Выполнить удаление аккаунта"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    account_id = int(callback.data.split("_")[3])
    
    stmt = select(Account).where(Account.id == account_id)
    result = await session.execute(stmt)
    account = result.scalar_one_or_none()
    
    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    if account.is_sold:
        await callback.answer("Нельзя удалить проданный аккаунт", show_alert=True)
        return
    
    product_id = account.product_id
    
    # Получаем информацию о товаре
    stmt_product = select(Product).where(Product.id == product_id)
    result_product = await session.execute(stmt_product)
    product = result_product.scalar_one_or_none()
    
    # Удаляем аккаунт
    await session.delete(account)
    
    # Обновляем количество на складе
    await session.execute(
        update(Product)
        .where(Product.id == product_id)
        .values(stock_count=Product.stock_count - 1)
    )
    
    await session.commit()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_accounts_product_{product_id}")]
    ])
    
    await callback.message.edit_text(
        f"✅ Аккаунт удален\n\n"
        f"Товар: <b>{product.name if product else 'N/A'}</b>\n"
        f"ID аккаунта: {account_id}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_delete_account_"))
async def admin_delete_account_cancel(callback: CallbackQuery, session: AsyncSession):
    """Отмена удаления аккаунта"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    account_id = int(callback.data.split("_")[3])
    
    stmt = select(Account).where(Account.id == account_id)
    result = await session.execute(stmt)
    account = result.scalar_one_or_none()
    
    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    product_id = account.product_id
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_accounts_product_{product_id}")]
    ])
    
    await callback.message.edit_text(
        "❌ Удаление отменено",
        reply_markup=keyboard
    )
    await callback.answer()


# Управление ролями пользователей
@router.callback_query(F.data.startswith("admin_user_role_"))
async def admin_user_role_menu(callback: CallbackQuery, session: AsyncSession):
    """Меню управления ролью пользователя"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Только разработчики могут управлять ролями
    if not await is_developer_async(callback.from_user.id, session):
        await callback.answer("Только разработчики могут управлять ролями", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[3])
    
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    # Проверяем, является ли пользователь суперадмином из .env
    is_superadmin = user.telegram_id in settings.admin_ids_list or user.telegram_id in settings.developer_ids_list
    if is_superadmin:
        await callback.answer("Нельзя изменить роль суперадмина из .env", show_alert=True)
        return
    
    # Определяем текущую роль
    current_role = user.role or "user"
    
    # Создаем кнопки для выбора роли
    keyboard_buttons = []
    
    if current_role != "user":
        keyboard_buttons.append([InlineKeyboardButton(text="👤 Установить роль: Пользователь", callback_data=f"admin_set_role_{user.id}_user")])
    if current_role != "admin":
        keyboard_buttons.append([InlineKeyboardButton(text="👑 Установить роль: Администратор", callback_data=f"admin_set_role_{user.id}_admin")])
    if current_role != "developer":
        keyboard_buttons.append([InlineKeyboardButton(text="⚙️ Установить роль: Разработчик", callback_data=f"admin_set_role_{user.id}_developer")])
    
    keyboard_buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"user_action_{user.telegram_id}")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    role_text = "👤 Пользователь"
    if current_role == "admin":
        role_text = "👑 Администратор"
    elif current_role == "developer":
        role_text = "⚙️ Разработчик"
    
    await callback.message.edit_text(
        f"👑 <b>Управление ролью пользователя</b>\n\n"
        f"Пользователь: {user.first_name or 'N/A'} (@{user.username or 'N/A'})\n"
        f"Текущая роль: {role_text}\n\n"
        f"Выберите новую роль:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_set_role_"))
async def admin_set_role(callback: CallbackQuery, session: AsyncSession):
    """Установка роли пользователя"""
    if not await is_admin_async(callback.from_user.id, session):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Только разработчики могут управлять ролями
    if not await is_developer_async(callback.from_user.id, session):
        await callback.answer("Только разработчики могут управлять ролями", show_alert=True)
        return
    
    parts = callback.data.split("_")
    user_id = int(parts[3])
    new_role = parts[4]
    
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    # Проверяем, является ли пользователь суперадмином из .env
    is_superadmin = user.telegram_id in settings.admin_ids_list or user.telegram_id in settings.developer_ids_list
    if is_superadmin:
        await callback.answer("Нельзя изменить роль суперадмина из .env", show_alert=True)
        return
    
    # Устанавливаем новую роль
    old_role = user.role or "user"
    user.role = new_role
    await session.commit()
    
    # Отправляем уведомление пользователю об изменении роли
    try:
        role_names = {
            "user": "Пользователь",
            "admin": "Администратор",
            "developer": "Разработчик"
        }
        
        from utils.keyboards import get_main_menu_keyboard
        is_admin = new_role in ("admin", "developer")
        
        await callback.bot.send_message(
            user.telegram_id,
            f"🔄 <b>Ваша роль изменена!</b>\n\n"
            f"Новая роль: <b>{role_names.get(new_role, new_role)}</b>\n\n"
            f"Ваша клавиатура была обновлена.",
            reply_markup=get_main_menu_keyboard(is_admin=is_admin),
            parse_mode="HTML"
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to notify user about role change: {e}")
    
    role_names_display = {
        "user": "Пользователь",
        "admin": "Администратор",
        "developer": "Разработчик"
    }
    
    callback_data_back = f"user_action_{user.telegram_id}"
    logger.debug(f"Setting callback_data for back button: {callback_data_back}")
    
    await callback.message.edit_text(
        f"✅ <b>Роль изменена</b>\n\n"
        f"Пользователь: {user.first_name or 'N/A'} (@{user.username or 'N/A'})\n"
        f"Старая роль: {role_names_display.get(old_role, old_role)}\n"
        f"Новая роль: {role_names_display.get(new_role, new_role)}\n\n"
        f"Пользователю отправлено уведомление с обновленной клавиатурой.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к пользователю", callback_data=callback_data_back)]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()
