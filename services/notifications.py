"""Сервис уведомлений"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from database.models import StockNotification, Product, User
from config import settings
import logging

logger = logging.getLogger(__name__)


async def send_notification_to_chat(bot, message: str, parse_mode: str = "HTML"):
    """Отправить уведомление в канал/чат поддержки"""
    try:
        chat_id = settings.NOTIFICATIONS_CHAT_ID
        if not chat_id:
            # Если канал не настроен, отправляем администраторам
            for admin_id in settings.admin_ids_list:
                try:
                    await bot.send_message(admin_id, message, parse_mode=parse_mode)
                except Exception as e:
                    logger.error(f"Error sending notification to admin {admin_id}: {e}")
            return
        
        # Пытаемся отправить в канал/чат
        try:
            # Если это числовой ID
            if chat_id.lstrip('-').isdigit():
                await bot.send_message(int(chat_id), message, parse_mode=parse_mode)
            else:
                # Если это username (начинается с @)
                await bot.send_message(chat_id, message, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Error sending notification to chat {chat_id}: {e}")
            # Fallback: отправляем администраторам
            for admin_id in settings.admin_ids_list:
                try:
                    await bot.send_message(admin_id, message, parse_mode=parse_mode)
                except:
                    pass
    except Exception as e:
        logger.error(f"Error in send_notification_to_chat: {e}")


async def notify_stock_available(session: AsyncSession, product_id: int, bot, check_stock_was_zero: bool = False):
    """Уведомить пользователей о поступлении товара
    
    Args:
        session: Сессия БД
        product_id: ID товара
        bot: Экземпляр бота
        check_stock_was_zero: Если True, уведомляет только если stock_count был 0 и стал >0
    """
    try:
        # Получаем товар для проверки текущего количества
        stmt_product = select(Product).where(Product.id == product_id)
        result_product = await session.execute(stmt_product)
        product = result_product.scalar_one_or_none()
        
        if not product:
            return
        
        # Если нужно проверить, что stock_count был 0 и стал >0
        if check_stock_was_zero:
            # Получаем количество аккаунтов на складе из таблицы Account
            from sqlalchemy import func
            from database.models import Account
            stmt_count = select(func.count(Account.id)).where(
                Account.product_id == product_id,
                Account.is_sold == False
            )
            result_count = await session.execute(stmt_count)
            actual_stock_count = result_count.scalar() or 0
            
            # Если stock_count в Product не совпадает с реальным количеством, обновляем
            if product.stock_count != actual_stock_count:
                from sqlalchemy import update
                await session.execute(
                    update(Product)
                    .where(Product.id == product_id)
                    .values(stock_count=actual_stock_count)
                )
                await session.commit()
                # Обновляем объект product
                result_product = await session.execute(stmt_product)
                product = result_product.scalar_one_or_none()
            
            # Уведомляем только если stock_count стал >0 (был 0 или меньше)
            if product.stock_count <= 0:
                return
        
        # Получаем все активные подписки
        stmt = select(StockNotification).where(
            StockNotification.product_id == product_id,
            StockNotification.is_notified == False
        )
        result = await session.execute(stmt)
        notifications = result.scalars().all()
        
        if not notifications:
            return
        
        # Отправляем уведомления
        for notification in notifications:
            try:
                stmt_user = select(User).where(User.id == notification.user_id)
                result_user = await session.execute(stmt_user)
                user = result_user.scalar_one_or_none()
                
                if user and not user.is_blocked:
                    await bot.send_message(
                        user.telegram_id,
                        f"🔔 <b>Товар поступил в продажу!</b>\n\n"
                        f"📦 {product.name}\n"
                        f"💰 Цена: {product.price:.2f} ₽\n"
                        f"📊 В наличии: {product.stock_count} шт.\n\n"
                        f"Используйте меню 'Каталог' для покупки.",
                        parse_mode="HTML"
                    )
                    
                    # Помечаем как уведомленное
                    notification.is_notified = True
            except Exception as e:
                logger.error(f"Error notifying user {notification.user_id}: {e}")
        
        await session.commit()
        
    except Exception as e:
        logger.error(f"Error in notify_stock_available: {e}")


async def notify_admins_about_purchase(session: AsyncSession, order, bot):
    """Уведомить администраторов о покупке"""
    try:
        from database.models import User, Product
        
        stmt_user = select(User).where(User.id == order.user_id)
        result_user = await session.execute(stmt_user)
        user = result_user.scalar_one_or_none()
        
        stmt_product = select(Product).where(Product.id == order.product_id)
        result_product = await session.execute(stmt_product)
        product = result_product.scalar_one_or_none()
        
        if not user or not product:
            return
        
        text = f"""🛒 <b>Новая покупка</b>

👤 Пользователь: @{user.username or user.first_name or 'Без имени'} (ID: {user.telegram_id})
📦 Товар: {product.name}
📊 Количество: {order.quantity} шт.
💰 Сумма: {order.total_amount:.2f} ₽
💳 Способ оплаты: {order.payment_method or 'Не указан'}
📋 Остаток на складе: {product.stock_count} шт.
🆔 Заказ: #{order.id}
"""
        
        await send_notification_to_chat(bot, text)
                
    except Exception as e:
        logger.error(f"Error in notify_admins_about_purchase: {e}")


async def notify_user_registration(session: AsyncSession, user: User, bot):
    """Уведомить о регистрации нового пользователя"""
    try:
        text = f"""👤 <b>Новая регистрация</b>

👤 Пользователь: @{user.username or user.first_name or 'Без имени'} (ID: {user.telegram_id})
📅 Дата: {user.created_at.strftime('%d.%m.%Y %H:%M')}
🔗 Реферальный код: {user.referral_code or 'Нет'}
"""
        
        if user.referred_by:
            stmt_ref = select(User).where(User.id == user.referred_by)
            result_ref = await session.execute(stmt_ref)
            referrer = result_ref.scalar_one_or_none()
            if referrer:
                text += f"👥 Приглашен пользователем: @{referrer.username or referrer.first_name or 'N/A'} (ID: {referrer.telegram_id})\n"
        
        await send_notification_to_chat(bot, text)
    except Exception as e:
        logger.error(f"Error in notify_user_registration: {e}")


async def notify_balance_topup(session: AsyncSession, user: User, amount: float, bot):
    """Уведомить о пополнении баланса"""
    try:
        text = f"""💰 <b>Пополнение баланса</b>

👤 Пользователь: @{user.username or user.first_name or 'Без имени'} (ID: {user.telegram_id})
💵 Сумма: {amount:.2f} ₽
💳 Новый баланс: {user.balance:.2f} ₽
"""
        await send_notification_to_chat(bot, text)
    except Exception as e:
        logger.error(f"Error in notify_balance_topup: {e}")


async def notify_new_order(session: AsyncSession, order, bot):
    """Уведомить о создании нового заказа"""
    try:
        from database.models import User, Product
        
        stmt_user = select(User).where(User.id == order.user_id)
        result_user = await session.execute(stmt_user)
        user = result_user.scalar_one_or_none()
        
        stmt_product = select(Product).where(Product.id == order.product_id)
        result_product = await session.execute(stmt_product)
        product = result_product.scalar_one_or_none()
        
        if not user or not product:
            return
        
        text = f"""📦 <b>Новый заказ</b>

👤 Пользователь: @{user.username or user.first_name or 'Без имени'} (ID: {user.telegram_id})
📦 Товар: {product.name}
📊 Количество: {order.quantity} шт.
💰 Сумма: {order.total_amount:.2f} ₽
⏳ Статус: {order.status}
🆔 Заказ: #{order.id}
"""
        await send_notification_to_chat(bot, text)
    except Exception as e:
        logger.error(f"Error in notify_new_order: {e}")

