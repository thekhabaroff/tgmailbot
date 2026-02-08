"""Middleware для автоматического обновления клавиатуры при изменении роли"""
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message
from sqlalchemy import select
from database.models import User
from config import settings
from utils.keyboards import get_main_menu_keyboard


class KeyboardUpdateMiddleware(BaseMiddleware):
    """Middleware для обновления клавиатуры при изменении роли пользователя"""
    
    # Кнопки, которые не должны обновлять клавиатуру (inline сообщения)
    IGNORE_TEXTS = ()
    
    def __init__(self):
        # Храним последнее известное состояние роли для каждого пользователя
        self._user_roles_cache: Dict[int, bool] = {}
    
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        # Работаем только с обычными сообщениями (не callback)
        if not isinstance(event, Message):
            return await handler(event, data)
        
        # Игнорируем команды /start (там своя логика)
        if event.text and event.text.startswith('/start'):
            return await handler(event, data)
        
        user_id = event.from_user.id if event.from_user else None
        if not user_id:
            return await handler(event, data)
        
        # Получаем сессию БД
        session = data.get("session")
        if not session:
            return await handler(event, data)
        
        # Проверяем текущую роль пользователя
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            return await handler(event, data)
        
        # Определяем, является ли пользователь админом
        is_admin = user_id in settings.admin_ids_list or user_id in settings.developer_ids_list
        if not is_admin and user.role in ("admin", "developer"):
            is_admin = True
        
        # Проверяем, изменилась ли роль
        cached_is_admin = self._user_roles_cache.get(user_id)
        
        # Если роль изменилась или это первое обращение
        if cached_is_admin is None or cached_is_admin != is_admin:
            # Обновляем кеш
            self._user_roles_cache[user_id] = is_admin
            
            # Если роль изменилась (не первое обращение), отправляем обновленную клавиатуру
            if cached_is_admin is not None:
                try:
                    await event.answer(
                        "🔄 <b>Ваши права обновлены!</b>\n\nКлавиатура обновлена в соответствии с новыми правами.",
                        reply_markup=get_main_menu_keyboard(is_admin=is_admin),
                        parse_mode="HTML"
                    )
                except Exception:
                    # Если не получилось отправить сообщение, просто продолжаем
                    pass
        
        # Продолжаем обработку
        return await handler(event, data)
