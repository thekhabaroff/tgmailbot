"""HTTP обработчики webhook для платежных систем

Использование:
1. Импортируйте функцию create_webhook_app из этого модуля
2. Создайте aiohttp приложение: app = create_webhook_app(bot)
3. Запустите сервер (например, через aiohttp или gunicorn)

Пример:
    from handlers.webhook import create_webhook_app
    from aiohttp import web
    
    app = create_webhook_app(bot)
    web.run_app(app, host='0.0.0.0', port=8443)

Webhook endpoints:
- POST /webhook/yookassa - обработчик webhook от ЮКасса
- POST /webhook/heleket - обработчик webhook от Heleket
- GET /health - проверка работоспособности

Важно:
- Webhook обработчики проверяют подпись запросов для безопасности
- Все webhook запросы логируются
- Обработка платежей идемпотентна (безопасна при повторных запросах)
"""
import json
import logging
from typing import Dict, Any
from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from database.database import async_session_maker
from database.models import Payment, User, Order, Account
from services.payment import PaymentService
from services.account_service import reserve_accounts, create_accounts_file, get_accounts_for_order
from services.notifications import notify_admins_about_purchase
from config import settings
from datetime import datetime
from aiogram import Bot
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)


async def process_balance_topup(
    session: AsyncSession,
    user_id: int,
    amount: float,
    payment_id: str,
    payment_method: str
) -> bool:
    """Обработать пополнение баланса"""
    try:
        # Проверяем, не обработан ли уже этот платеж
        stmt = select(Payment).where(
            Payment.payment_id == payment_id,
            Payment.payment_method == payment_method
        )
        result = await session.execute(stmt)
        existing_payment = result.scalar_one_or_none()
        
        if existing_payment and existing_payment.status == "SUCCESS":
            logger.info(f"Payment {payment_id} already processed")
            return True
        
        # Получаем пользователя
        stmt_user = select(User).where(User.id == user_id)
        result_user = await session.execute(stmt_user)
        user = result_user.scalar_one_or_none()
        
        if not user:
            logger.error(f"User {user_id} not found")
            return False
        
        # Обновляем или создаем запись платежа
        if existing_payment:
            existing_payment.status = "SUCCESS"
            existing_payment.completed_at = datetime.now()
        else:
            payment = Payment(
                user_id=user_id,
                amount=amount,
                payment_method=payment_method,
                payment_id=payment_id,
                status="SUCCESS",
                completed_at=datetime.now()
            )
            session.add(payment)
        
        # Пополняем баланс
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(balance=User.balance + amount)
        )
        
        await session.commit()
        logger.info(f"Balance topup successful: user {user_id}, amount {amount}, payment {payment_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing balance topup: {e}", exc_info=True)
        await session.rollback()
        return False


async def process_order_payment(
    session: AsyncSession,
    order_id: int,
    payment_id: str,
    payment_method: str,
    bot: Bot = None
) -> bool:
    """Обработать оплату заказа"""
    try:
        # Получаем заказ
        stmt = select(Order).where(Order.id == order_id)
        result = await session.execute(stmt)
        order = result.scalar_one_or_none()
        
        if not order:
            logger.error(f"Order {order_id} not found")
            return False
        
        # Проверяем, не оплачен ли уже заказ
        if order.status != "ОЖИДАЕТ ОПЛАТЫ":
            logger.info(f"Order {order_id} already processed (status: {order.status})")
            return True
        
        # Получаем зарезервированные аккаунты
        accounts = await get_accounts_for_order(session, order.id)
        
        # Если товары не найдены, резервируем
        if not accounts:
            accounts = await reserve_accounts(session, order.product_id, order.quantity, order.id)
        
        if not accounts:
            logger.error(f"No accounts available for order {order_id}")
            return False
        
        # Обновляем заказ
        order.status = "ОПЛАЧЕНО"
        order.payment_method = payment_method
        order.payment_id = payment_id
        order.paid_at = datetime.now()
        order.reserved_until = None
        
        # Создаем запись платежа
        payment = Payment(
            user_id=order.user_id,
            amount=order.total_amount,
            payment_method=payment_method,
            payment_id=payment_id,
            status="SUCCESS",
            order_id=order.id,
            completed_at=datetime.now()
        )
        session.add(payment)
        
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
            
            from database.models import ReferralTransaction
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
        
        # Удаляем аккаунты из базы данных после выдачи
        if accounts:
            account_ids = [acc.id for acc in accounts]
            from sqlalchemy import delete
            await session.execute(
                delete(Account)
                .where(Account.id.in_(account_ids))
            )
        
        await session.commit()
        
        # Отправляем товар пользователю через бота
        if bot:
            try:
                file_obj = await create_accounts_file(accounts)
                
                await bot.send_document(
                    user.telegram_id,
                    BufferedInputFile(
                        file_obj.read(),
                        filename=file_obj.name
                    ),
                    caption=f"✅ Заказ #{order_id} оплачен и выполнен!\n\n📦 Ваш товар:"
                )
                
                # Уведомляем администраторов
                await notify_admins_about_purchase(session, order, bot)
            except Exception as e:
                logger.error(f"Error sending order to user: {e}", exc_info=True)
        
        logger.info(f"Order payment processed successfully: order {order_id}, payment {payment_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing order payment: {e}", exc_info=True)
        await session.rollback()
        return False


class PaymentWebhookData:
    """Класс для хранения данных из webhook"""
    def __init__(self, payment_id: str, user_id: int, amount: float, order_id: int = 0):
        self.payment_id = payment_id
        self.user_id = user_id
        self.amount = amount
        self.order_id = order_id


class PaymentWebhookHandler:
    """Базовый класс для обработки webhook от платежных систем"""
    
    def __init__(self, payment_method: str):
        self.payment_method = payment_method
    
    def get_signature_header_name(self) -> str:
        """Возвращает название заголовка с подписью (должен быть переопределен)"""
        raise NotImplementedError
    
    def verify_signature(self, data: Dict[str, Any], signature: str) -> bool:
        """Проверяет подпись webhook (должен быть переопределен)"""
        raise NotImplementedError
    
    def parse_webhook_data(self, data: Dict[str, Any]) -> PaymentWebhookData:
        """Парсит данные из webhook (должен быть переопределен)"""
        raise NotImplementedError
    
    def get_success_event_name(self) -> str:
        """Возвращает название события успешной оплаты (должен быть переопределен)"""
        raise NotImplementedError
    
    def get_failed_event_name(self) -> str:
        """Возвращает название события неудачной оплаты (должен быть переопределен)"""
        raise NotImplementedError
    
    def is_success_event(self, data: Dict[str, Any], event_type: str) -> bool:
        """Проверяет, является ли событие успешной оплатой (должен быть переопределен)"""
        raise NotImplementedError
    
    async def handle_webhook(self, request: web.Request) -> web.Response:
        """Универсальный обработчик webhook"""
        try:
            # Получаем данные из запроса
            data = await request.json()
            headers = request.headers
            
            # Получаем подпись из заголовка
            signature = headers.get(self.get_signature_header_name(), "")
            
            # Проверяем подпись
            if not self.verify_signature(data, signature):
                logger.warning(f"Invalid {self.payment_method} webhook signature: {signature}")
                return web.Response(status=401, text="Invalid signature")
            
            # Логируем webhook
            logger.info(f"{self.payment_method.capitalize()} webhook received: {json.dumps(data, ensure_ascii=False)}")
            
            # Парсим данные
            try:
                webhook_data = self.parse_webhook_data(data)
            except (KeyError, ValueError, TypeError) as e:
                logger.error(f"Error parsing {self.payment_method} webhook data: {e}")
                return web.Response(status=400, text="Invalid webhook data")
            
            if not webhook_data.payment_id or not webhook_data.user_id:
                logger.error(
                    f"Missing required fields in {self.payment_method} webhook: "
                    f"payment_id={webhook_data.payment_id}, user_id={webhook_data.user_id}"
                )
                return web.Response(status=400, text="Missing required fields")
            
            # Обрабатываем событие
            event_type = data.get("event") or data.get("event_type", "")
            
            async with async_session_maker() as session:
                if self.is_success_event(data, event_type):
                    # Определяем тип платежа: пополнение баланса или оплата заказа
                    bot = getattr(request.app, "bot", None)
                    
                    if webhook_data.order_id and webhook_data.order_id > 0:
                        # Оплата заказа
                        success = await process_order_payment(
                            session, webhook_data.order_id, webhook_data.payment_id, 
                            self.payment_method, bot
                        )
                    else:
                        # Пополнение баланса
                        success = await process_balance_topup(
                            session, webhook_data.user_id, webhook_data.amount, 
                            webhook_data.payment_id, self.payment_method
                        )
                    
                    if success:
                        return web.Response(status=200, text="OK")
                    else:
                        return web.Response(status=500, text="Processing failed")
                
                elif event_type == self.get_failed_event_name():
                    # Обновляем статус платежа на FAILED
                    stmt = select(Payment).where(
                        Payment.payment_id == webhook_data.payment_id,
                        Payment.payment_method == self.payment_method
                    )
                    result = await session.execute(stmt)
                    payment = result.scalar_one_or_none()
                    
                    if payment:
                        payment.status = "FAILED"
                        await session.commit()
                    
                    return web.Response(status=200, text="OK")
                
                else:
                    logger.info(f"Unhandled {self.payment_method} event: {event_type}")
                    return web.Response(status=200, text="OK")
        
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {self.payment_method} webhook: {e}")
            return web.Response(status=400, text="Invalid JSON")
        except Exception as e:
            logger.error(f"Error processing {self.payment_method} webhook: {e}", exc_info=True)
            return web.Response(status=500, text="Internal error")


class YooKassaWebhookHandler(PaymentWebhookHandler):
    """Обработчик webhook от ЮКасса"""
    
    def __init__(self):
        super().__init__("yookassa")
    
    def get_signature_header_name(self) -> str:
        return "X-YooMoney-Signature"
    
    def verify_signature(self, data: Dict[str, Any], signature: str) -> bool:
        return PaymentService.verify_yookassa_webhook(data, signature)
    
    def parse_webhook_data(self, data: Dict[str, Any]) -> PaymentWebhookData:
        payment_obj = data.get("object", {})
        payment_id = payment_obj.get("id")
        metadata = payment_obj.get("metadata", {})
        order_id = metadata.get("order_id", 0)
        user_id = metadata.get("user_id", 0)
        amount_obj = payment_obj.get("amount", {})
        amount = float(amount_obj.get("value", 0))
        
        return PaymentWebhookData(payment_id, user_id, amount, order_id)
    
    def get_success_event_name(self) -> str:
        return "payment.succeeded"
    
    def get_failed_event_name(self) -> str:
        return "payment.canceled"
    
    def is_success_event(self, data: Dict[str, Any], event_type: str) -> bool:
        if event_type != "payment.succeeded":
            return False
        payment_obj = data.get("object", {})
        status = payment_obj.get("status")
        return status == "succeeded"


class HeleketWebhookHandler(PaymentWebhookHandler):
    """Обработчик webhook от Heleket"""
    
    def __init__(self):
        super().__init__("heleket")
    
    def get_signature_header_name(self) -> str:
        return "X-Heleket-Signature"
    
    def verify_signature(self, data: Dict[str, Any], signature: str) -> bool:
        return PaymentService.verify_heleket_webhook(data, signature)
    
    def parse_webhook_data(self, data: Dict[str, Any]) -> PaymentWebhookData:
        payment_id = data.get("payment_id")
        order_id_str = data.get("order_id", "0")
        user_id = data.get("user_id", 0)
        amount = float(data.get("amount", 0))
        
        try:
            order_id = int(order_id_str) if order_id_str and order_id_str != "0" else 0
        except (ValueError, TypeError):
            order_id = 0
        
        return PaymentWebhookData(payment_id, user_id, amount, order_id)
    
    def get_success_event_name(self) -> str:
        return "payment.success"
    
    def get_failed_event_name(self) -> str:
        return "payment.failed"
    
    def is_success_event(self, data: Dict[str, Any], event_type: str) -> bool:
        if event_type != "payment.success":
            return False
        status = data.get("status")
        return status == "success"


# Создаем экземпляры обработчиков
_yookassa_handler = YooKassaWebhookHandler()
_heleket_handler = HeleketWebhookHandler()


async def handle_yookassa_webhook(request: web.Request) -> web.Response:
    """Обработчик webhook от ЮКасса"""
    return await _yookassa_handler.handle_webhook(request)


async def handle_heleket_webhook(request: web.Request) -> web.Response:
    """Обработчик webhook от Heleket"""
    return await _heleket_handler.handle_webhook(request)


def create_webhook_app(bot: Bot = None, dispatcher=None) -> web.Application:
    """Создать aiohttp приложение для webhook обработчиков
    
    Args:
        bot: Экземпляр бота для отправки сообщений
        dispatcher: Диспетчер aiogram для обработки обновлений Telegram
    """
    app = web.Application()
    
    # Сохраняем бота и диспетчер в приложении для доступа в обработчиках
    if bot:
        app["bot"] = bot
    if dispatcher:
        app["dispatcher"] = dispatcher
    
    # Регистрируем маршруты для платежных систем
    app.router.add_post("/webhook/yookassa", handle_yookassa_webhook)
    app.router.add_post("/webhook/heleket", handle_heleket_webhook)
    
    # Обработчик Telegram webhook (если настроен)
    async def handle_telegram_webhook(request: web.Request) -> web.Response:
        """Обработчик webhook от Telegram"""
        try:
            if not dispatcher:
                logger.error("Dispatcher not configured for Telegram webhook")
                return web.Response(status=500, text="Dispatcher not configured")
            
            # Получаем обновление от Telegram
            update_data = await request.json()
            
            # Создаем объект Update из данных
            from aiogram.types import Update
            update = Update(**update_data)
            
            # Обрабатываем обновление через диспетчер
            await dispatcher.feed_update(bot, update)
            
            return web.Response(status=200, text="OK")
        except Exception as e:
            logger.error(f"Error processing Telegram webhook: {e}", exc_info=True)
            return web.Response(status=500, text="Internal error")
    
    # Регистрируем Telegram webhook endpoint
    app.router.add_post("/webhook/telegram", handle_telegram_webhook)
    # Также поддерживаем путь без /telegram для совместимости
    app.router.add_post("/webhook", handle_telegram_webhook)
    
    # Health check endpoint
    async def health_check(request: web.Request) -> web.Response:
        return web.Response(text="OK")
    
    app.router.add_get("/health", health_check)
    
    return app
