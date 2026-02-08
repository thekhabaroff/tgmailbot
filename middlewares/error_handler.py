"""Middleware для обработки ошибок"""
import traceback
import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Update

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseMiddleware):
    """Middleware для обработки ошибок"""
    
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as exception:
            # Игнорируем некритичные ошибки
            error_str = str(exception).lower()
            if "message is not modified" in error_str:
                # Это не критичная ошибка, просто игнорируем
                return None
            
            # Игнорируем сетевые ошибки (таймауты, проблемы с соединением)
            if any(phrase in error_str for phrase in [
                "timeout", "таймаут", "семафора", "semaphore",
                "connection", "соединение", "network"
            ]):
                logger.warning(f"Network error in handler (non-critical): {exception}")
                return None
            
            logger.error(f"Error in handler: {exception}", exc_info=exception)
            try:
                from utils.logger import log_error_to_db
                from database.database import async_session_maker
                
                async with async_session_maker() as session:
                    user_id = None
                    update = None
                    
                    # Получаем update из event
                    if isinstance(event, Update):
                        update = event
                    elif hasattr(event, 'update'):
                        update = event.update
                    elif hasattr(event, 'event') and isinstance(event.event, Update):
                        update = event.event
                    
                    if update and isinstance(update, Update):
                        if update.message and update.message.from_user:
                            user_id = update.message.from_user.id
                        elif update.callback_query and update.callback_query.from_user:
                            user_id = update.callback_query.from_user.id
                        elif update.edited_message and update.edited_message.from_user:
                            user_id = update.edited_message.from_user.id
                    
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
            # Пробрасываем исключение дальше для обработки через @dp.errors()
            raise
