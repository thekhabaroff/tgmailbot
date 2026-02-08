"""Обработчик каталога"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.models import Category, Product, StockNotification
from utils.keyboards import (
    get_categories_keyboard, get_products_keyboard, get_product_detail_keyboard,
    get_payment_methods_keyboard
)
from utils.text import MENU_CATALOG
from services.discount import calculate_total_price
from services.account_service import reserve_accounts
from database.models import Order, User
from datetime import datetime, timedelta
from config import settings
import logging

logger = logging.getLogger(__name__)

router = Router()


class OrderStates(StatesGroup):
    """Состояния для заказа"""
    waiting_quantity = State()


@router.message(F.text == MENU_CATALOG)
async def show_catalog(message: Message, session: AsyncSession, state: FSMContext):
    """Показать каталог"""
    # Очищаем FSM состояние при переходе в каталог
    await state.clear()
    
    stmt = select(Category).where(Category.is_active == True)
    result = await session.execute(stmt)
    categories = result.scalars().all()
    
    if not categories:
        await message.answer("Каталог пуст. Обратитесь к администратору.")
        return
    
    await message.answer(
        "📂 Выберите категорию:",
        reply_markup=get_categories_keyboard(categories)
    )


@router.callback_query(F.data == "back_to_catalog")
async def back_to_catalog(callback: CallbackQuery, session: AsyncSession):
    """Вернуться в каталог"""
    stmt = select(Category).where(Category.is_active == True)
    result = await session.execute(stmt)
    categories = result.scalars().all()
    
    if not categories:
        await callback.message.edit_text("Каталог пуст. Обратитесь к администратору.")
        await callback.answer()
        return
    
    await callback.message.edit_text(
        "📂 Выберите категорию:",
        reply_markup=get_categories_keyboard(categories)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("category_"))
async def show_category_products(callback: CallbackQuery, session: AsyncSession):
    """Показать товары категории"""
    category_id = int(callback.data.split("_")[1])
    
    stmt = select(Product).where(
        Product.category_id == category_id,
        Product.is_active == True,
    )
    result = await session.execute(stmt)
    products = result.scalars().all()
    
    if not products:
        await callback.answer("В этой категории пока нет товаров", show_alert=True)
        return
    
    try:
        await callback.message.edit_text(
            "🛒 Выберите товар:",
            reply_markup=get_products_keyboard(products, category_id),
        )
    except Exception as e:
        # Игнорируем ошибку "message is not modified"
        if "message is not modified" not in str(e).lower():
            raise

    await callback.answer()


@router.callback_query(F.data.startswith("product_"))
async def show_product_detail(callback: CallbackQuery, session: AsyncSession):
    """Показать детали товара"""
    product_id = int(callback.data.split("_")[1])
    
    stmt = select(Product).where(Product.id == product_id)
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()
    
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    
    has_stock = product.stock_count > 0
    
    text = f"""📦 <b>{product.name}</b>

💰 Цена: {product.price:.2f} ₽ за единицу
📊 В наличии: {product.stock_count if has_stock else 0} шт.

"""
    
    if product.description:
        text += f"📝 Описание:\n{product.description}\n\n"
    
    if product.format_info:
        text += f"📋 Формат: {product.format_info}\n\n"
    
    if product.recommendations:
        text += f"💡 Рекомендации: {product.recommendations}\n\n"
    
    if not has_stock:
        text += "❌ Товар временно отсутствует на складе"
    
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_product_detail_keyboard(product_id, has_stock, product.category_id),
            parse_mode="HTML",
        )
    except Exception as e:
        error_str = str(e).lower()
        # Игнорируем некритичные ошибки
        if "message is not modified" in error_str:
            # Это не критичная ошибка, просто игнорируем
            pass
        elif any(
            phrase in error_str
            for phrase in [
                "timeout",
                "таймаут",
                "семафора",
                "semaphore",
                "connection",
                "соединение",
                "network",
            ]
        ):
            # Сетевые ошибки - не критичны
            logger.warning(f"Network error in show_product_detail (non-critical): {e}")
        else:
            # Другие ошибки пробрасываем дальше
            raise

    await callback.answer()


@router.callback_query(F.data.startswith("buy_"))
async def start_buy_process(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать процесс покупки"""
    product_id = int(callback.data.split("_")[1])
    
    stmt = select(Product).where(Product.id == product_id)
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()
    
    if not product or product.stock_count == 0:
        await callback.answer("Товар недоступен", show_alert=True)
        return
    
    # Проверяем количество неоплаченных заказов
    user_id = callback.from_user.id
    stmt_user = select(User).where(User.telegram_id == user_id)
    result_user = await session.execute(stmt_user)
    user = result_user.scalar_one_or_none()
    
    if user:
        stmt_orders = select(Order).where(
            Order.user_id == user.id,
            Order.status == "ОЖИДАЕТ ОПЛАТЫ"
        )
        result_orders = await session.execute(stmt_orders)
        pending_orders = result_orders.scalars().all()
        
        if len(pending_orders) >= 3:
            await callback.answer(
                "У вас слишком много неоплаченных заказов. Оплатите или отмените существующие заказы.",
                show_alert=True
            )
            return
    
    await state.update_data(product_id=product_id, max_quantity=product.stock_count)
    await state.set_state(OrderStates.waiting_quantity)
    
    await callback.message.edit_text(
        f"📦 <b>{product.name}</b>\n\n"
        f"💰 Цена за единицу: {product.price:.2f} ₽\n"
        f"📊 Доступно: {product.stock_count} шт.\n\n"
        f"Введите количество товара:",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(OrderStates.waiting_quantity)
async def process_quantity(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка введенного количества"""
    # Проверяем, не выбрана ли кнопка меню
    from utils.text import MENU_CATALOG, MENU_BALANCE, MENU_ORDERS, MENU_REFERRAL, MENU_SUPPORT, MENU_INFO, MENU_RULES, MENU_ADMIN, MENU_BROADCAST
    menu_buttons = [MENU_CATALOG, MENU_BALANCE, MENU_ORDERS, MENU_REFERRAL, MENU_SUPPORT, MENU_INFO, MENU_RULES, MENU_ADMIN, MENU_BROADCAST, "📢 Рассылка", "⚙️ Пункт управления"]
    
    if message.text and (message.text in menu_buttons or message.text.startswith('/')):
        await state.clear()
        return
    
    try:
        quantity = int(message.text)
        if quantity <= 0:
            await message.answer("Количество должно быть больше нуля. Попробуйте снова:")
            return
        
        data = await state.get_data()
        product_id = data.get("product_id")
        max_quantity = data.get("max_quantity")
        
        if quantity > max_quantity:
            await message.answer(
                f"Недостаточно товара на складе. Доступно: {max_quantity} шт.\n"
                f"Введите количество снова:"
            )
            return
        
        # Получаем товар
        stmt = select(Product).where(Product.id == product_id)
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()
        
        if not product:
            await message.answer("Товар не найден")
            await state.clear()
            return
        
        # Получаем пользователя
        user_id = message.from_user.id
        stmt_user = select(User).where(User.telegram_id == user_id)
        result_user = await session.execute(stmt_user)
        user = result_user.scalar_one_or_none()
        
        if not user:
            await message.answer("Пользователь не найден. Используйте /start")
            await state.clear()
            return
        
        # Рассчитываем цену со скидкой
        discount_percent, total_amount = calculate_total_price(product.price, quantity)
        
        # Резервируем аккаунты ПЕРЕД созданием заказа
        try:
            reserved_accounts = await reserve_accounts(session, product_id, quantity, None)
        except ValueError as e:
            await message.answer(f"❌ {str(e)}")
            await state.clear()
            return
        
        # Создаем заказ
        order = Order(
            user_id=user.id,
            product_id=product_id,
            quantity=quantity,
            price_per_unit=product.price,
            discount=discount_percent,
            total_amount=total_amount,
            status="ОЖИДАЕТ ОПЛАТЫ",
            reserved_until=datetime.now() + timedelta(minutes=settings.ORDER_RESERVATION_MINUTES)
        )
        session.add(order)
        await session.flush()  # Получаем ID заказа
        
        # Привязываем зарезервированные аккаунты к заказу
        from database.models import Account
        from sqlalchemy import update
        account_ids = [acc.id for acc in reserved_accounts]
        await session.execute(
            update(Account)
            .where(Account.id.in_(account_ids))
            .values(order_id=order.id)
        )
        
        await session.commit()
        await session.refresh(order)
        
        # Уведомляем администраторов о новом заказе
        try:
            from services.notifications import notify_new_order
            await notify_new_order(session, order, message.bot)
        except Exception as e:
            logger.error(f"Error notifying about new order: {e}")
        
        await state.clear()
        
        # Показываем способы оплаты
        text = f"""📦 <b>Заказ #{order.id}</b>

Товар: {product.name}
Количество: {quantity} шт.
Цена за единицу: {product.price:.2f} ₽
"""
        
        if discount_percent > 0:
            text += f"Скидка: {discount_percent}%\n"
        
        text += f"💰 Итого: {total_amount:.2f} ₽\n\nВыберите способ оплаты:"
        
        await message.answer(
            text,
            reply_markup=get_payment_methods_keyboard(order.id),
            parse_mode="HTML"
        )
        
    except ValueError as e:
        error_msg = str(e)
        from utils.keyboards import get_back_keyboard
        if "недостаточно" in error_msg.lower() or "insufficient" in error_msg.lower():
            await message.answer(
                f"❌ {error_msg}",
                reply_markup=get_back_keyboard()
            )
        else:
            await message.answer(
                "Пожалуйста, введите число:",
                reply_markup=get_back_keyboard()
            )
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing quantity: {e}", exc_info=True)
        error_msg = str(e)
        # Более информативное сообщение об ошибке
        if "недостаточно" in error_msg.lower() or "insufficient" in error_msg.lower():
            await message.answer(f"❌ {error_msg}")
        elif "integrity" in error_msg.lower() or "constraint" in error_msg.lower():
            await message.answer("❌ Ошибка при резервировании товара. Попробуйте снова.")
        else:
            await message.answer(f"❌ Произошла ошибка: {error_msg[:100]}")
        await state.clear()


@router.callback_query(F.data == "back_to_products")
async def back_to_products(callback: CallbackQuery, session: AsyncSession):
    """Вернуться к списку товаров"""
    # Возвращаемся в каталог
    stmt = select(Category).where(Category.is_active == True)
    result = await session.execute(stmt)
    categories = result.scalars().all()
    
    if not categories:
        await callback.message.edit_text("Каталог пуст. Обратитесь к администратору.")
        await callback.answer()
        return
    
    await callback.message.edit_text(
        "📂 Выберите категорию:",
        reply_markup=get_categories_keyboard(categories)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("notify_"))
async def subscribe_notification(callback: CallbackQuery, session: AsyncSession):
    """Подписка на уведомление о поступлении товара"""
    product_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    # Получаем пользователя
    stmt_user = select(User).where(User.telegram_id == user_id)
    result_user = await session.execute(stmt_user)
    user = result_user.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    # Проверяем, есть ли уже подписка
    stmt = select(StockNotification).where(
        StockNotification.user_id == user.id,
        StockNotification.product_id == product_id,
        StockNotification.is_notified == False
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    
    if existing:
        await callback.answer("Вы уже подписаны на уведомления", show_alert=True)
        return
    
    # Создаем подписку
    notification = StockNotification(
        user_id=user.id,
        product_id=product_id
    )
    session.add(notification)
    await session.commit()
    
    await callback.answer("✅ Вы подписаны на уведомления о поступлении товара", show_alert=True)

