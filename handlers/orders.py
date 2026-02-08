"""Обработчик заказов"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.models import Order, User, Product
from services.account_service import get_accounts_for_order, create_accounts_file
from utils.keyboards import get_orders_keyboard, get_order_detail_keyboard
from utils.text import MENU_ORDERS
from aiogram.types import BufferedInputFile
import logging

logger = logging.getLogger(__name__)

router = Router()


@router.message(F.text == MENU_ORDERS)
async def show_orders(message: Message, session: AsyncSession, state: FSMContext):
    """Показать заказы пользователя"""
    # Очищаем FSM состояние при переходе в заказы
    await state.clear()
    
    user_id = message.from_user.id
    
    stmt_user = select(User).where(User.telegram_id == user_id)
    result_user = await session.execute(stmt_user)
    user = result_user.scalar_one_or_none()
    
    if not user:
        await message.answer("Пользователь не найден. Используйте /start")
        return
    
    stmt = select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc())
    result = await session.execute(stmt)
    orders = result.scalars().all()
    
    if not orders:
        await message.answer("У вас пока нет заказов")
        return
    
    await message.answer(
        "📦 Ваши заказы:",
        reply_markup=get_orders_keyboard(orders)
    )


@router.callback_query(F.data == "my_orders")
async def show_orders_callback(callback: CallbackQuery, session: AsyncSession):
    """Показать заказы (callback)"""
    user_id = callback.from_user.id
    
    stmt_user = select(User).where(User.telegram_id == user_id)
    result_user = await session.execute(stmt_user)
    user = result_user.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    stmt = select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc())
    result = await session.execute(stmt)
    orders = result.scalars().all()
    
    if not orders:
        await callback.message.edit_text("У вас пока нет заказов")
        await callback.answer()
        return
    
    await callback.message.edit_text(
        "📦 Ваши заказы:",
        reply_markup=get_orders_keyboard(orders)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("order_"))
async def show_order_detail(callback: CallbackQuery, session: AsyncSession):
    """Показать детали заказа"""
    order_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    stmt_user = select(User).where(User.telegram_id == user_id)
    result_user = await session.execute(stmt_user)
    user = result_user.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    stmt = select(Order).where(Order.id == order_id, Order.user_id == user.id)
    result = await session.execute(stmt)
    order = result.scalar_one_or_none()
    
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    
    # Получаем товар
    stmt_product = select(Product).where(Product.id == order.product_id)
    result_product = await session.execute(stmt_product)
    product = result_product.scalar_one_or_none()
    
    status_emoji = {
        "ОЖИДАЕТ ОПЛАТЫ": "⏳",
        "ОПЛАЧЕНО": "✅",
        "ВЫПОЛНЕНО": "✔️",
        "ОТМЕНЕНО": "❌"
    }.get(order.status, "❓")
    
    text = f"""📦 <b>Заказ #{order.id}</b>

{status_emoji} Статус: {order.status}
📦 Товар: {product.name if product else 'Неизвестно'}
📊 Количество: {order.quantity} шт.
💰 Цена за единицу: {order.price_per_unit:.2f} ₽
"""
    
    if order.discount > 0:
        text += f"🎁 Скидка: {order.discount}%\n"
    
    text += f"💰 Итого: {order.total_amount:.2f} ₽\n"
    
    if order.payment_method:
        text += f"💳 Способ оплаты: {order.payment_method}\n"
    
    text += f"📅 Дата создания: {order.created_at.strftime('%d.%m.%Y %H:%M')}\n"
    
    if order.paid_at:
        text += f"✅ Оплачен: {order.paid_at.strftime('%d.%m.%Y %H:%M')}\n"
    
    if order.completed_at:
        text += f"✔️ Выполнен: {order.completed_at.strftime('%d.%m.%Y %H:%M')}\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_order_detail_keyboard(order_id, order.status),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pay_order_"))
async def pay_order(callback: CallbackQuery, session: AsyncSession):
    """Оплатить неоплаченный заказ"""
    order_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    stmt_user = select(User).where(User.telegram_id == user_id)
    result_user = await session.execute(stmt_user)
    user = result_user.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    stmt = select(Order).where(Order.id == order_id, Order.user_id == user.id)
    result = await session.execute(stmt)
    order = result.scalar_one_or_none()
    
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    
    if order.status != "ОЖИДАЕТ ОПЛАТЫ":
        await callback.answer("Заказ уже оплачен или отменен", show_alert=True)
        return
    
    # Получаем товар
    stmt_product = select(Product).where(Product.id == order.product_id)
    result_product = await session.execute(stmt_product)
    product = result_product.scalar_one_or_none()
    
    # Показываем способы оплаты
    from utils.keyboards import get_payment_methods_keyboard
    
    text = f"""📦 <b>Заказ #{order.id}</b>

Товар: {product.name if product else 'Неизвестно'}
Количество: {order.quantity} шт.
💰 Итого: {order.total_amount:.2f} ₽

Выберите способ оплаты:"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_payment_methods_keyboard(order.id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_order_"))
async def cancel_order_from_detail(callback: CallbackQuery, session: AsyncSession):
    """Отменить заказ из деталей"""
    order_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    stmt_user = select(User).where(User.telegram_id == user_id)
    result_user = await session.execute(stmt_user)
    user = result_user.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    stmt = select(Order).where(Order.id == order_id, Order.user_id == user.id)
    result = await session.execute(stmt)
    order = result.scalar_one_or_none()
    
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    
    if order.status != "ОЖИДАЕТ ОПЛАТЫ":
        await callback.answer("Можно отменить только неоплаченные заказы", show_alert=True)
        return
    
    # Освобождаем зарезервированные аккаунты
    from database.models import Account
    from sqlalchemy import update
    from datetime import datetime
    
    # Получаем аккаунты заказа
    stmt_accounts = select(Account).where(Account.order_id == order_id)
    result_accounts = await session.execute(stmt_accounts)
    accounts = result_accounts.scalars().all()
    
    if accounts:
        account_ids = [acc.id for acc in accounts]
        # Освобождаем аккаунты
        await session.execute(
            update(Account)
            .where(Account.id.in_(account_ids))
            .values(
                is_sold=False,
                sold_at=None,
                order_id=None
            )
        )
        
        # Возвращаем товар на склад
        await session.execute(
            update(Product)
            .where(Product.id == order.product_id)
            .values(stock_count=Product.stock_count + order.quantity)
        )
    
    # Отменяем заказ
    order.status = "ОТМЕНЕНО"
    order.reserved_until = None
    await session.commit()
    
    from utils.keyboards import get_back_keyboard
    await callback.message.edit_text(
        "❌ Заказ отменен\n\n"
        "✅ Товар возвращен в каталог",
        reply_markup=get_back_keyboard("my_orders")
    )
    await callback.answer("Заказ отменен, товар возвращен на склад")


@router.callback_query(F.data.startswith("download_"))
async def download_order(callback: CallbackQuery, session: AsyncSession):
    """Скачать товар из заказа"""
    order_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    stmt_user = select(User).where(User.telegram_id == user_id)
    result_user = await session.execute(stmt_user)
    user = result_user.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    stmt = select(Order).where(Order.id == order_id, Order.user_id == user.id)
    result = await session.execute(stmt)
    order = result.scalar_one_or_none()
    
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    
    if order.status != "ВЫПОЛНЕНО":
        await callback.answer("Заказ еще не выполнен", show_alert=True)
        return
    
    try:
        # Получаем аккаунты
        accounts = await get_accounts_for_order(session, order_id)
        
        if not accounts:
            await callback.answer("Товар не найден", show_alert=True)
            return
        
        # Создаем файл
        file_obj = await create_accounts_file(accounts)
        
        await callback.message.answer_document(
            BufferedInputFile(
                file_obj.read(),
                filename=file_obj.name
            ),
            caption=f"📦 Товар по заказу #{order_id}"
        )
        await callback.answer("✅ Файл отправлен")
        
    except Exception as e:
        logger.error(f"Error downloading order {order_id}: {e}")
        await callback.answer("Ошибка при загрузке товара", show_alert=True)

