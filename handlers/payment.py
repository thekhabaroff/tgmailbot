"""Обработчик платежей"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from database.models import Order, User, Payment as PaymentModel, Account, ReferralTransaction, Product
from services.payment import PaymentService
from services.account_service import reserve_accounts, create_accounts_file, get_accounts_for_order
from services.discount import calculate_total_price
from utils.keyboards import get_main_menu_keyboard
from config import settings
from datetime import datetime
from aiogram.types import BufferedInputFile
import logging

logger = logging.getLogger(__name__)

router = Router()


async def process_payment_success(
    session: AsyncSession,
    order_id: int,
    payment_method: str,
    payment_id: str = None
):
    """Обработка успешной оплаты"""
    try:
        # Получаем заказ
        stmt = select(Order).where(Order.id == order_id)
        result = await session.execute(stmt)
        order = result.scalar_one_or_none()

        if not order or order.status != "ОЖИДАЕТ ОПЛАТЫ":
            return (False, None, None)

        # Получаем уже зарезервированные товары (они были зарезервированы при создании заказа)
        accounts = await get_accounts_for_order(session, order.id)

        # Если товары не найдены  резервируем
        if not accounts:
            accounts = await reserve_accounts(session, order.product_id, order.quantity, order.id)

        # Обновляем заказ
        order.status = "ОПЛАЧЕНО"
        order.payment_method = payment_method
        order.payment_id = payment_id
        order.paid_at = datetime.now()
        order.reserved_until = None

        # Создаем запись платежа
        payment = PaymentModel(
            user_id=order.user_id,
            amount=order.total_amount,
            payment_method=payment_method,
            payment_id=payment_id,
            status="SUCCESS",
            order_id=order.id,
            completed_at=datetime.now()
        )
        session.add(payment)

        # Если оплата с баланса, списываем средства
        if payment_method == "balance":
            await session.execute(
                update(User)
                .where(User.id == order.user_id)
                .values(balance=User.balance - order.total_amount)
            )

        # Обработка реферальной системы
        stmt_user = select(User).where(User.id == order.user_id)
        result_user = await session.execute(stmt_user)
        user = result_user.scalar_one_or_none()

        if user and user.referred_by:
            commission = order.total_amount * (settings.REFERRAL_COMMISSION / 100)
            await session.execute(
                update(User)
                .where(User.id == user.referred_by)
                .values(balance=User.balance + commission)
            )

            # Создаем запись реферальной транзакции
            ref_transaction = ReferralTransaction(
                referrer_id=user.referred_by,
                referred_id=user.id,
                order_id=order.id,
                amount=order.total_amount,
                commission=commission
            )
            session.add(ref_transaction)

        # Выдаем товар
        order.status = "ВЫПОЛНЕНО"
        order.completed_at = datetime.now()

        # Удаляем аккаунты из базы данных после выдачи (физическое удаление)
        if accounts:
            account_ids = [acc.id for acc in accounts]
            from sqlalchemy import delete
            await session.execute(
                delete(Account)
                .where(Account.id.in_(account_ids))
            )
            # stock_count уже был уменьшен при резервировании аккаунтов,
            # поэтому здесь не нужно уменьшать его повторно

        # Коммитим изменения
        await session.commit()

        return (True, accounts, order)

    except Exception as e:
        logger.error(f"Error processing payment: {e}", exc_info=True)
        await session.rollback()
        return (False, None, None)


@router.callback_query(F.data.startswith("pay_balance_"))
async def pay_from_balance(callback: CallbackQuery, session: AsyncSession):
    """Оплата с баланса"""
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
    
    if user.balance < order.total_amount:
        await callback.answer(
            f"Недостаточно средств на балансе. Требуется: {order.total_amount:.2f} ₽",
            show_alert=True
        )
        return
    
    # Обрабатываем оплату
    success, accounts, order_obj = await process_payment_success(
        session, order_id, "balance"
    )
    
    if success:
        # Отправляем товар
        file_obj = await create_accounts_file(accounts)
        
        await callback.message.answer_document(
            BufferedInputFile(
                file_obj.read(),
                filename=file_obj.name
            ),
            caption=f"✅ Заказ #{order_id} оплачен и выполнен!\n\n📦 Ваш товар:"
        )
        
        # Уведомляем администраторов
        from services.notifications import notify_admins_about_purchase
        await notify_admins_about_purchase(session, order_obj, callback.bot)
        
        await callback.message.edit_text(
            f"✅ Заказ #{order_id} успешно оплачен с баланса!\n\n"
            f"Товар отправлен в сообщении выше."
        )
    else:
        await callback.answer("Ошибка при обработке платежа", show_alert=True)
    
    await callback.answer()


# ========== ТЕСТОВАЯ ОПЛАТА (для разработки) ==========
# Раскомментируйте блок ниже для включения тестовой оплаты
# В продакшн закомментируйте этот блок полностью
# TODO
@router.callback_query(F.data.startswith("pay_test_"))
async def pay_test(callback: CallbackQuery, session: AsyncSession):
    """Тестовая оплата (для разработки)"""
    from config import settings
    
    # Дополнительная проверка настройки
    if not settings.ENABLE_TEST_PAYMENT:
        await callback.answer("Тестовая оплата отключена", show_alert=True)
        return
    
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
    
    # Тестовая оплата - сразу обрабатываем как успешную
    try:
        success, accounts, order_obj = await process_payment_success(
            session, order_id, "test"
        )

        if success and accounts:
            # Отправляем товар
            file_obj = await create_accounts_file(accounts)

            await callback.message.answer_document(
                BufferedInputFile(
                    file_obj.read(),
                    filename=file_obj.name
                ),
                caption=f"✅ Заказ #{order_id} оплачен (тестовая оплата)!\n\n📦 Ваш товар:"
            )

            # Уведомляем администраторов
            from services.notifications import notify_admins_about_purchase
            await notify_admins_about_purchase(session, order_obj, callback.bot)

            await callback.message.edit_text(
                f"✅ Заказ #{order_id} успешно оплачен (тестовая оплата)!\n\n"
                f"Товар отправлен в сообщении выше."
            )
            await callback.answer("✅ Оплата успешна")
        elif success:
            # Заказ оплачен, но аккаунты не найдены
            from utils.keyboards import get_back_keyboard
            await callback.message.edit_text(
                f"✅ Заказ #{order_id} успешно оплачен (тестовая оплата)!\n\n"
                f"⚠️ Товар не найден. Обратитесь в поддержку.",
                reply_markup=get_back_keyboard("my_orders")
            )
            await callback.answer("⚠️ Товар не найден")
        else:
            logger.error(f"Test payment failed for order {order_id}, user {user_id}")
            await callback.answer("Ошибка при обработке платежа", show_alert=True)
    except Exception as e:
        logger.error(f"Error in test payment for order {order_id}, user {user_id}: {e}", exc_info=True)
        await callback.answer(f"Ошибка: {str(e)[:100]}", show_alert=True)
# ========================================================


# ========== ОБРАБОТЧИКИ ПЛАТЕЖНЫХ СИСТЕМ ==========

@router.callback_query(F.data.startswith("pay_yookassa_"))
async def pay_yookassa(callback: CallbackQuery, session: AsyncSession):
    """Оплата через ЮКасса"""
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
    
    payment_data = await PaymentService.create_yookassa_payment(
        order.total_amount, order_id, user.id
    )
    
    if payment_data:
        # Сохраняем payment_id в заказе
        order.payment_id = payment_data.get("payment_id")
        await session.commit()
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_data.get("payment_url"))],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
        
        await callback.message.edit_text(
            f"💳 <b>Оплата через ЮКасса</b>\n\n"
            f"Сумма: {order.total_amount:.2f} ₽\n\n"
            f"Перейдите по ссылке для оплаты.\n"
            f"После оплаты товар будет выдан автоматически.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.answer("Ошибка создания платежа. Обратитесь в поддержку.", show_alert=True)
    
    await callback.answer()


@router.callback_query(F.data.startswith("pay_heleket_"))
async def pay_heleket(callback: CallbackQuery, session: AsyncSession):
    """Оплата через Heleket"""
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
    
    payment_data = await PaymentService.create_heleket_payment(
        order.total_amount, order_id, user.id
    )
    
    if payment_data:
        order.payment_id = payment_data.get("payment_id")
        await session.commit()
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_data.get("payment_url"))],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
        
        await callback.message.edit_text(
            f"💳 <b>Оплата через Heleket</b>\n\n"
            f"Сумма: {order.total_amount:.2f} ₽\n\n"
            f"Перейдите по ссылке для оплаты.\n"
            f"После оплаты товар будет выдан автоматически.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.answer("Ошибка создания платежа. Обратитесь в поддержку.", show_alert=True)
    
    await callback.answer()


@router.callback_query(F.data.startswith("pay_stars_"))
async def pay_stars(callback: CallbackQuery, session: AsyncSession):
    """Оплата через Telegram Stars"""
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
    
    # Telegram Stars оплата через встроенную кнопку
    # Конвертируем рубли в Stars (2.3 RUB = 1 Stars)
    stars_amount = int(order.total_amount / 2.3)  # Примерная конвертация
    
    try:
        # Отправляем инвойс через sendInvoice (stars / digital goods)
        await callback.message.answer_invoice(
            title=f"Заказ #{order_id}",
            description=f"Оплата заказа #{order_id} на сумму {order.total_amount:.2f} ₽",
            payload=f"order_{order_id}",
            provider_token="",  # Для Stars не нужен
            currency="XTR",
            prices=[LabeledPrice(label=f"Заказ #{order_id}", amount=stars_amount)]
        )

        await callback.message.edit_text(
            f"⭐ <b>Оплата через Telegram Stars</b>\n\n"
            f"Сумма: {order.total_amount:.2f} ₽ ({stars_amount} Stars)\n\n"
            f"Счет отправлен отдельным сообщением.\n"
            f"После оплаты товар будет выдан автоматически.",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Error creating Telegram Stars invoice: {e}")
        await callback.answer("Ошибка создания платежа. Обратитесь в поддержку.", show_alert=True)
    
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_order_"))
async def cancel_order(callback: CallbackQuery, session: AsyncSession):
    """Отмена заказа"""
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
        await callback.answer("Заказ нельзя отменить", show_alert=True)
        return
    
    # Освобождаем зарезервированные аккаунты
    from database.models import Account
    from sqlalchemy import update
    
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


@router.callback_query(F.data.startswith("pay_all_orders_"))
async def pay_all_orders(callback: CallbackQuery, session: AsyncSession):
    """Оплатить все заказы из корзины"""
    user_id = callback.from_user.id
    
    stmt_user = select(User).where(User.telegram_id == user_id)
    result_user = await session.execute(stmt_user)
    user = result_user.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    # Получаем ID заказов из callback_data
    order_ids_str = callback.data.split("_", 3)[3] if len(callback.data.split("_")) > 3 else ""
    if not order_ids_str:
        await callback.answer("Ошибка: не указаны заказы", show_alert=True)
        return
    
    order_ids = [int(oid) for oid in order_ids_str.split("_") if oid.isdigit()]
    
    if not order_ids:
        await callback.answer("Заказы не найдены", show_alert=True)
        return
    
    # Получаем все заказы пользователя
    stmt = select(Order).where(
        Order.id.in_(order_ids),
        Order.user_id == user.id,
        Order.status == "ОЖИДАЕТ ОПЛАТЫ"
    )
    result = await session.execute(stmt)
    orders = result.scalars().all()
    
    if not orders:
        await callback.answer("Не найдено неоплаченных заказов", show_alert=True)
        return
    
    # Рассчитываем общую сумму
    total_amount = sum(order.total_amount for order in orders)
    
    # Проверяем баланс (если оплата с баланса)
    if user.balance < total_amount:
        await callback.answer(
            f"Недостаточно средств на балансе. Требуется: {total_amount:.2f} ₽, доступно: {user.balance:.2f} ₽",
            show_alert=True
        )
        return
    
    # Показываем способы оплаты для всех заказов
    from utils.keyboards import get_payment_methods_keyboard
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    text = f"""💳 <b>Оплата всех заказов</b>\n\n"""
    for order in orders:
        stmt_product = select(Product).where(Product.id == order.product_id)
        result_product = await session.execute(stmt_product)
        product = result_product.scalar_one_or_none()
        text += f"Заказ #{order.id}: {product.name if product else 'Неизвестно'} × {order.quantity} шт. - {order.total_amount:.2f} ₽\n"
    
    text += f"\n💰 <b>Общая сумма: {total_amount:.2f} ₽</b>\n\n"
    text += "Выберите способ оплаты:"
    
    # Создаем специальную клавиатуру для оплаты всех заказов
    buttons = []
    buttons.append([InlineKeyboardButton(text="💳 С баланса", callback_data=f"pay_all_balance_{order_ids_str}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pay_all_balance_"))
async def pay_all_orders_balance(callback: CallbackQuery, session: AsyncSession):
    """Оплатить все заказы с баланса"""
    user_id = callback.from_user.id
    
    stmt_user = select(User).where(User.telegram_id == user_id)
    result_user = await session.execute(stmt_user)
    user = result_user.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    # Получаем ID заказов из callback_data
    order_ids_str = callback.data.split("_", 3)[3] if len(callback.data.split("_")) > 3 else ""
    if not order_ids_str:
        await callback.answer("Ошибка: не указаны заказы", show_alert=True)
        return
    
    order_ids = [int(oid) for oid in order_ids_str.split("_") if oid.isdigit()]
    
    if not order_ids:
        await callback.answer("Заказы не найдены", show_alert=True)
        return
    
    # Получаем все заказы пользователя
    stmt = select(Order).where(
        Order.id.in_(order_ids),
        Order.user_id == user.id,
        Order.status == "ОЖИДАЕТ ОПЛАТЫ"
    )
    result = await session.execute(stmt)
    orders = result.scalars().all()
    
    if not orders:
        await callback.answer("Не найдено неоплаченных заказов", show_alert=True)
        return
    
    # Рассчитываем общую сумму
    total_amount = sum(order.total_amount for order in orders)
    
    # Проверяем баланс
    if user.balance < total_amount:
        await callback.answer(
            f"Недостаточно средств на балансе. Требуется: {total_amount:.2f} ₽",
            show_alert=True
        )
        return
    
    # Оплачиваем все заказы
    successful_orders = []
    failed_orders = []
    
    for order in orders:
        success, accounts, order_obj = await process_payment_success(
            session, order.id, "balance"
        )
        
        if success:
            successful_orders.append((order_obj, accounts))
        else:
            failed_orders.append(order.id)
    
    # Обновляем баланс пользователя
    if successful_orders:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(balance=User.balance - total_amount)
        )
        await session.commit()
    
    # Отправляем товары
    from services.notifications import notify_admins_about_purchase
    
    for order_obj, accounts in successful_orders:
        file_obj = await create_accounts_file(accounts)
        
        await callback.message.answer_document(
            BufferedInputFile(
                file_obj.read(),
                filename=file_obj.name
            ),
            caption=f"✅ Заказ #{order_obj.id} оплачен и выполнен!\n\n📦 Ваш товар:"
        )
        
        await notify_admins_about_purchase(session, order_obj, callback.bot)
    
    # Формируем итоговое сообщение
    if successful_orders and not failed_orders:
        text = f"✅ Все заказы успешно оплачены и выполнены!\n\nОплачено заказов: {len(successful_orders)}\n💰 Сумма: {total_amount:.2f} ₽"
    elif successful_orders:
        text = f"✅ Оплачено заказов: {len(successful_orders)}\n❌ Не удалось оплатить: {len(failed_orders)}"
    else:
        text = "❌ Не удалось оплатить заказы"
    
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


# ========== WEBHOOK ОБРАБОТЧИКИ ДЛЯ ПЛАТЕЖНЫХ СИСТЕМ ==========

@router.message(F.successful_payment)
async def handle_successful_payment(message, session: AsyncSession):
    """Обработка успешной оплаты через Telegram Stars"""
    payment = message.successful_payment
    payload = payment.invoice_payload
    
    if payload.startswith("order_"):
        order_id = int(payload.split("_")[1])
        user_id = message.from_user.id
        
        stmt_user = select(User).where(User.telegram_id == user_id)
        result_user = await session.execute(stmt_user)
        user = result_user.scalar_one_or_none()
        
        if user:
            stmt = select(Order).where(Order.id == order_id, Order.user_id == user.id)
            result = await session.execute(stmt)
            order = result.scalar_one_or_none()
            
            if order and order.status == "ОЖИДАЕТ ОПЛАТЫ":
                success, accounts, order_obj = await process_payment_success(
                    session, order_id, "stars", payment.telegram_payment_charge_id
                )
                
                if success:
                    file_obj = await create_accounts_file(accounts)
                    
                    await message.answer_document(
                        BufferedInputFile(
                            file_obj.read(),
                            filename=file_obj.name
                        ),
                        caption=f"✅ Заказ #{order_id} оплачен и выполнен!\n\n📦 Ваш товар:"
                    )
                    
                    from services.notifications import notify_admins_about_purchase
                    await notify_admins_about_purchase(session, order_obj, message.bot)


@router.pre_checkout_query()
async def handle_pre_checkout_query(pre_checkout_query: PreCheckoutQuery, session: AsyncSession):
    """Подтверждение оплаты через Telegram Stars"""
    payload = pre_checkout_query.invoice_payload or ""

    if not payload.startswith("order_"):
        await pre_checkout_query.answer(ok=False, error_message="Некорректный платеж")
        return

    try:
        order_id = int(payload.split("_")[1])
    except (ValueError, IndexError):
        await pre_checkout_query.answer(ok=False, error_message="Некорректный платеж")
        return

    stmt_user = select(User).where(User.telegram_id == pre_checkout_query.from_user.id)
    result_user = await session.execute(stmt_user)
    user = result_user.scalar_one_or_none()

    if not user:
        await pre_checkout_query.answer(ok=False, error_message="Пользователь не найден")
        return

    stmt = select(Order).where(Order.id == order_id, Order.user_id == user.id)
    result = await session.execute(stmt)
    order = result.scalar_one_or_none()

    if not order or order.status != "ОЖИДАЕТ ОПЛАТЫ":
        await pre_checkout_query.answer(ok=False, error_message="Заказ недоступен для оплаты")
        return

    # Валидация валюты
    if pre_checkout_query.currency != "XTR":
        await pre_checkout_query.answer(ok=False, error_message="Некорректная валюта. Требуется XTR (Telegram Stars)")
        return

    # Валидация суммы (конвертируем рубли в Stars: 2.3 RUB = 1 Stars)
    expected_stars = int(order.total_amount / 2.3)
    if pre_checkout_query.total_amount != expected_stars:
        await pre_checkout_query.answer(
            ok=False, 
            error_message=f"Неверная сумма. Ожидается {expected_stars} Stars"
        )
        return

    await pre_checkout_query.answer(ok=True)
