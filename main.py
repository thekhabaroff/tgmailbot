"""Главный файл бота"""
import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import FSInputFile

from config import settings
from database.database import init_db, get_session
from handlers import (
    start, catalog, orders, balance, referral, info, payment, admin, broadcast
)
from handlers.webhook import create_webhook_app
from utils.logger import logger

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/bot.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)


async def cancel_expired_orders(bot: Bot):
    """Автоматическая отмена просроченных заказов"""
    from database.database import async_session_maker
    from database.models import Order, Product
    from sqlalchemy import select, update
    from datetime import datetime
    
    while True:
        try:
            async with async_session_maker() as session:
                # Находим заказы, которые просрочены (reserved_until < now и статус ОЖИДАЕТ ОПЛАТЫ)
                now = datetime.now()
                stmt = select(Order).where(
                    Order.status == "ОЖИДАЕТ ОПЛАТЫ",
                    Order.reserved_until < now
                )
                result = await session.execute(stmt)
                expired_orders = result.scalars().all()
                
                for order in expired_orders:
                    # Освобождаем зарезервированные аккаунты
                    from database.models import Account
                    
                    # Получаем аккаунты заказа
                    stmt_accounts = select(Account).where(Account.order_id == order.id)
                    result_accounts = await session.execute(stmt_accounts)
                    accounts = result_accounts.scalars().all()
                    
                    if accounts:
                        account_ids = [acc.id for acc in accounts]
                        # Освобождаем аккаунты (возвращаем в каталог)
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
                    
                    # Уведомляем пользователя
                    try:
                        from database.models import User
                        stmt_user = select(User).where(User.id == order.user_id)
                        result_user = await session.execute(stmt_user)
                        user = result_user.scalar_one_or_none()
                        
                        if user:
                            await bot.send_message(
                                user.telegram_id,
                                f"⏰ <b>Заказ отменен</b>\n\n"
                                f"Заказ #{order.id} был отменен из-за истечения времени ожидания оплаты (15 минут).\n\n"
                                f"✅ Товар возвращен в каталог.\n\n"
                                f"Вы можете создать новый заказ.",
                                parse_mode="HTML"
                            )
                    except Exception as e:
                        logger.error(f"Error notifying user about expired order: {e}")
                
                if expired_orders:
                    await session.commit()
                    logger.info(f"Cancelled {len(expired_orders)} expired orders")
                
        except Exception as e:
            logger.error(f"Error in cancel_expired_orders: {e}")
        
        # Проверяем каждые 5 минут
        await asyncio.sleep(300)


async def sync_roles_from_env(bot: Bot):
    """Синхронизация ролей пользователей из .env в БД"""
    from database.database import async_session_maker
    from database.models import User
    from sqlalchemy import select
    
    async with async_session_maker() as session:
        # Обновляем роли для всех пользователей из .env
        all_admin_ids = set(settings.admin_ids_list + settings.developer_ids_list)
        
        for user_id in all_admin_ids:
            try:
                stmt = select(User).where(User.telegram_id == user_id)
                result = await session.execute(stmt)
                user = result.scalar_one_or_none()
                
                if user:
                    # Устанавливаем роль на основе .env
                    if user_id in settings.developer_ids_list:
                        if user.role != "developer":
                            user.role = "developer"
                            logger.info(f"Updated role to 'developer' for user {user_id}")
                    elif user_id in settings.admin_ids_list:
                        if user.role != "admin":
                            user.role = "admin"
                            logger.info(f"Updated role to 'admin' for user {user_id}")
                else:
                    # Пользователь еще не зарегистрирован - роль будет установлена при регистрации
                    logger.debug(f"User {user_id} from .env not yet registered")
                
            except Exception as e:
                logger.error(f"Error syncing role for user {user_id}: {e}")
        
        await session.commit()


async def setup_support_chat(bot: Bot):
    """Настройка чата поддержки"""
    from database.database import async_session_maker
    from database.models import Setting
    from sqlalchemy import select, update
    
    async with async_session_maker() as session:
        # Проверяем, есть ли уже настройка для support_chat_id
        stmt = select(Setting).where(Setting.key == "support_chat_id")
        result = await session.execute(stmt)
        setting = result.scalar_one_or_none()
        
        support_chat_id = None
        if setting and setting.value:
            try:
                support_chat_id = int(setting.value)
            except:
                pass
        
        # Если ID чата не указан, отправляем инструкцию администратору
        if not support_chat_id and settings.admin_ids_list:
            instruction_text = """📋 <b>Настройка чата поддержки</b>

Для настройки системы поддержки выполните следующие шаги:

1. Создайте группу в Telegram (или используйте существующую)
2. Добавьте бота в группу как администратора
3. Отправьте любое сообщение в группу (например: "/start")
4. Бот автоматически сохранит ID группы

Или вы можете указать ID чата вручную:
• Для групп: -1001234567890 (отрицательное число)
• Для каналов: -1001234567890 (отрицательное число)
• Для супергрупп: -1001234567890 (отрицательное число)

Чтобы получить ID чата:
1. Добавьте @userinfobot в группу
2. Отправьте любое сообщение
3. @userinfobot покажет ID чата

После настройки, сообщения от пользователей будут автоматически пересылаться в этот чат."""
            
            # Отправляем инструкцию всем администраторам
            for admin_id in settings.admin_ids_list:
                try:
                    await bot.send_message(
                        admin_id,
                        instruction_text,
                        parse_mode="HTML"
                    )
                    logger.info(f"Sent support chat setup instruction to admin {admin_id}")
                except Exception as e:
                    # Игнорируем ошибку, если пользователь не начал диалог с ботом
                    error_str = str(e).lower()
                    if "unauthorized" in error_str or "chat not found" in error_str or "bot was blocked" in error_str:
                        logger.warning(f"Admin {admin_id} has not started a conversation with the bot or blocked it. Skipping instruction.")
                    else:
                        logger.error(f"Failed to send instruction to admin {admin_id}: {e}")
        else:
            # Проверяем доступность чата
            if support_chat_id:
                try:
                    chat = await bot.get_chat(support_chat_id)
                    logger.info(f"Support chat configured: {chat.title} (ID: {support_chat_id})")
                except Exception as e:
                    logger.warning(f"Support chat ID {support_chat_id} is not accessible: {e}")
                    # Сбрасываем неверный ID
                    if setting:
                        setting.value = ""
                        await session.commit()


async def start_payment_webhook_server(bot: Bot, dispatcher: Dispatcher = None):
    """Запуск HTTP/HTTPS сервера для обработки webhook от платежных систем и Telegram"""
    from aiohttp import web
    import ssl
    
    try:
        app = create_webhook_app(bot, dispatcher)
        runner = web.AppRunner(app)
        await runner.setup()
        
        # Определяем протокол и настройки SSL
        use_https = settings.PAYMENT_WEBHOOK_USE_HTTPS
        ssl_context = None
        
        if use_https:
            if not settings.PAYMENT_WEBHOOK_SSL_CERT_PATH or not settings.PAYMENT_WEBHOOK_SSL_KEY_PATH:
                logger.warning(
                    "PAYMENT_WEBHOOK_USE_HTTPS=True, but SSL certificates not configured. "
                    "Falling back to HTTP. Set PAYMENT_WEBHOOK_SSL_CERT_PATH and PAYMENT_WEBHOOK_SSL_KEY_PATH in .env"
                )
                use_https = False
            else:
                try:
                    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    ssl_context.load_cert_chain(
                        settings.PAYMENT_WEBHOOK_SSL_CERT_PATH,
                        settings.PAYMENT_WEBHOOK_SSL_KEY_PATH
                    )
                    logger.info("SSL certificates loaded successfully")
                except Exception as e:
                    logger.error(f"Failed to load SSL certificates: {e}. Falling back to HTTP.")
                    use_https = False
                    ssl_context = None
        
        # Создаем сайт с SSL или без
        if use_https and ssl_context:
            site = web.TCPSite(runner, '0.0.0.0', settings.PAYMENT_WEBHOOK_PORT, ssl_context=ssl_context)
            protocol = "https"
        else:
            site = web.TCPSite(runner, '0.0.0.0', settings.PAYMENT_WEBHOOK_PORT)
            protocol = "http"
        
        await site.start()
        
        logger.info(f"Webhook server started on port {settings.PAYMENT_WEBHOOK_PORT} ({protocol.upper()})")
        if dispatcher:
            logger.info(f"  - Telegram webhook: {protocol}://0.0.0.0:{settings.PAYMENT_WEBHOOK_PORT}/webhook/telegram")
        logger.info(f"  - YooKassa webhook: {protocol}://0.0.0.0:{settings.PAYMENT_WEBHOOK_PORT}/webhook/yookassa")
        logger.info(f"  - Heleket webhook: {protocol}://0.0.0.0:{settings.PAYMENT_WEBHOOK_PORT}/webhook/heleket")
        logger.info(f"  - Health check: {protocol}://0.0.0.0:{settings.PAYMENT_WEBHOOK_PORT}/health")
        
        if not use_https:
            logger.warning(
                "⚠️  Webhook server is running on HTTP. For production, enable HTTPS by setting:\n"
                "   PAYMENT_WEBHOOK_USE_HTTPS=True\n"
                "   PAYMENT_WEBHOOK_SSL_CERT_PATH=/path/to/cert.pem\n"
                "   PAYMENT_WEBHOOK_SSL_KEY_PATH=/path/to/key.pem"
            )
        
        # Сохраняем runner для корректного завершения
        return runner
    except Exception as e:
        logger.error(f"Failed to start payment webhook server: {e}", exc_info=True)
        return None


async def on_startup(bot: Bot):
    """Действия при запуске бота"""
    logger.info("Bot starting up...")
    logger.info(f'{settings.BOT_TOKEN=}')
    
    # Проверяем токен бота через get_me()
    try:
        bot_info = await bot.get_me()
        logger.info(f"Bot token verified. Bot: @{bot_info.username} (ID: {bot_info.id})")
    except Exception as e:
        error_str = str(e).lower()
        if "unauthorized" in error_str:
            logger.error(f"Bot token is invalid or expired! Please check your BOT_TOKEN in .env file.")
            raise Exception(f"Invalid bot token: {e}")
        else:
            logger.error(f"Failed to verify bot token: {e}")
            raise
    
    # Инициализация БД
    await init_db()
    logger.info("Database initialized")
    
    # Синхронизация ролей из .env в БД
    await sync_roles_from_env(bot)
    logger.info("Roles synchronized from .env")
    
    # Настройка чата поддержки
    await setup_support_chat(bot)
    logger.info("Support chat setup completed")
    
    # Запускаем задачу автоматической отмены заказов
    asyncio.create_task(cancel_expired_orders(bot))
    logger.info("Expired orders cancellation task started")
    
    # Запускаем HTTP сервер для webhook платежных систем
    # Для Telegram webhook сервер будет перезапущен в main() с dispatcher
    webhook_runner = await start_payment_webhook_server(bot, None)
    if webhook_runner:
        # Сохраняем runner в bot для доступа при завершении
        bot._webhook_runner = webhook_runner
    
    # Удаляем webhook, если используется polling режим (webhook будет установлен в main() для webhook режима)
    if not settings.WEBHOOK_URL:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Polling mode: webhook deleted")
        except Exception as e:
            # Игнорируем ошибку, если webhook не был установлен или токен неверный
            error_str = str(e).lower()
            if "unauthorized" in error_str:
                logger.error(f"Bot token is invalid! Cannot delete webhook. Error: {e}")
                raise
            else:
                logger.warning(f"Could not delete webhook (non-critical): {e}")


async def on_shutdown(bot: Bot):
    """Действия при остановке бота"""
    logger.info("Bot shutting down...")
    
    # Останавливаем webhook сервер для платежных систем
    if hasattr(bot, '_webhook_runner'):
        try:
            await bot._webhook_runner.cleanup()
            logger.info("Payment webhook server stopped")
        except Exception as e:
            logger.warning(f"Error stopping payment webhook server: {e}")
    
    try:
        await bot.delete_webhook()
    except Exception as e:
        logger.warning(f"Error deleting webhook on shutdown: {e}")
    finally:
        # Закрываем сессию бота для предотвращения предупреждений о незакрытых сессиях
        try:
            await bot.session.close()
        except Exception as e:
            logger.warning(f"Error closing bot session: {e}")


async def main():
    """Главная функция"""
    # Проверка токена
    if not settings.BOT_TOKEN:
        logger.error("BOT_TOKEN not set in environment variables!")
        sys.exit(1)
    
    # Создание бота и диспетчера
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Регистрация роутеров (порядок важен!)
    # Сначала регистрируем специфичные обработчики (кнопки меню, команды)
    dp.include_router(start.router)
    dp.include_router(admin.router)  # Админ-панель раньше общего обработчика сообщений
    dp.include_router(broadcast.router)  # Рассылка раньше общего обработчика сообщений
    dp.include_router(catalog.router)
    dp.include_router(orders.router)
    dp.include_router(balance.router)
    dp.include_router(referral.router)
    dp.include_router(payment.router)
    # Общий обработчик сообщений (поддержка) должен быть последним
    dp.include_router(info.router)
    
    # Регистрация middleware
    from middlewares import (
        DatabaseMiddleware, 
        BlockedUserMiddleware, 
        ErrorHandlerMiddleware,
        KeyboardUpdateMiddleware
    )
    
    # Middleware для получения сессии БД
    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())
    
    # Middleware для проверки блокировки (после DatabaseMiddleware, чтобы session был доступен)
    dp.message.middleware(BlockedUserMiddleware())
    dp.callback_query.middleware(BlockedUserMiddleware())
    
    # Middleware для автоматического обновления клавиатуры при изменении роли
    dp.message.middleware(KeyboardUpdateMiddleware())
    
    # Middleware для обработки ошибок
    dp.update.outer_middleware(ErrorHandlerMiddleware())
    
    # Обработчик ошибок через декоратор (резервный)
    # В aiogram 3.x обработчик получает ErrorEvent
    @dp.errors()
    async def error_handler(event, data):
        """Обработчик ошибок для aiogram 3.x (резервный)"""
        import traceback
        from aiogram.types import Update, ErrorEvent
        
        # В aiogram 3.x event может быть ErrorEvent или просто exception
        if isinstance(event, ErrorEvent):
            exception = event.exception
            update = event.update
        elif hasattr(event, 'exception'):
            exception = event.exception
            update = getattr(event, 'update', None)
        else:
            # Если это просто exception
            exception = event
            update = None
        
        # Игнорируем некритичные сетевые ошибки
        error_str = str(exception).lower()
        if any(phrase in error_str for phrase in [
            "timeout", "таймаут", "семафора", "semaphore", 
            "connection", "соединение", "network"
        ]):
            # Сетевые ошибки - не критичны, просто логируем
            logger.warning(f"Network error (non-critical): {exception}")
            return
        
        # Игнорируем ошибку "message is not modified"
        if "message is not modified" in error_str:
            return
        
        logger.error(f"Error handler called: {type(exception).__name__}: {exception}", exc_info=exception)
        
        try:
            from utils.logger import log_error_to_db
            from database.database import async_session_maker
            
            async with async_session_maker() as session:
                user_id = None
                
                # update уже извлечен выше, если это ErrorEvent
                # Если update не был извлечен, пытаемся получить его из data
                if not update and data:
                    update = data.get('update')
                
                # Получаем user_id из update
                if update:
                    if update.message and update.message.from_user:
                        user_id = update.message.from_user.id
                    elif update.callback_query and update.callback_query.from_user:
                        user_id = update.callback_query.from_user.id
                    elif update.edited_message and update.edited_message.from_user:
                        user_id = update.edited_message.from_user.id
                    elif update.channel_post and update.channel_post.sender_chat:
                        user_id = update.channel_post.sender_chat.id
                
                tb_str = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
                await log_error_to_db(
                    session,
                    "ERROR",
                    str(exception),
                    user_id=user_id,
                    traceback=tb_str
                )
        except Exception as e:
            logger.error(f"Error logging to DB: {e}")
    
    # Запуск бота
    # Автоматический выбор режима: webhook (если WEBHOOK_URL установлен) или polling
    
    if settings.WEBHOOK_URL:
        # ========== WEBHOOK РЕЖИМ (для production) ==========
        logger.info("Starting bot in WEBHOOK mode")
        
        try:
            # Выполняем startup действия
            await on_startup(bot)
            
            # Перезапускаем webhook сервер с dispatcher для обработки Telegram обновлений
            if hasattr(bot, '_webhook_runner'):
                await bot._webhook_runner.cleanup()
            
            # Запускаем webhook сервер с dispatcher
            webhook_runner = await start_payment_webhook_server(bot, dp)
            if webhook_runner:
                bot._webhook_runner = webhook_runner
            
            # Устанавливаем webhook URL в Telegram
            try:
                await bot.set_webhook(
                    url=settings.WEBHOOK_URL,
                    certificate=FSInputFile(settings.SSL_CERT_PATH) if settings.SSL_CERT_PATH else None,
                    allowed_updates=dp.resolve_used_update_types()
                )
                logger.info(f"Webhook set to {settings.WEBHOOK_URL}")
            except Exception as e:
                logger.error(f"Failed to set webhook: {e}")
                raise
            
            # Ожидаем бесконечно (сервер работает в фоне)
            logger.info("Bot is running in webhook mode. Press Ctrl+C to stop.")
            try:
                await asyncio.Event().wait()  # Ожидаем бесконечно
            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
            finally:
                await on_shutdown(bot)
                
        except Exception as e:
            logger.error(f"Error in webhook mode: {e}", exc_info=True)
            await on_shutdown(bot)
            raise
    else:
        # ========== POLLING РЕЖИМ (для разработки) ==========
        logger.info("Starting bot in POLLING mode")
        logger.warning("⚠️  Polling mode is for development only. For production, set WEBHOOK_URL in .env")
        
        await on_startup(bot)
        
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            await on_shutdown(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

