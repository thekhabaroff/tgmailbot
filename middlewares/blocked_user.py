"""Middleware для проверки блокировки пользователя"""
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from database.models import User
from config import settings
from utils.text import MENU_SUPPORT, MENU_CATALOG, MENU_BALANCE, MENU_ORDERS, MENU_REFERRAL, MENU_INFO, MENU_RULES, MENU_ADMIN, MENU_BROADCAST


class BlockedUserMiddleware(BaseMiddleware):
    """Middleware для проверки блокировки пользователя"""
    
    # Обработчики, которые не требуют проверки блокировки (админ-панель)
    ADMIN_PREFIXES = (
        "admin_", "broadcast_"
    )
    
    # Кнопки меню (для проверки, является ли сообщение кнопкой меню)
    MENU_BUTTONS = (
        MENU_CATALOG, MENU_BALANCE, MENU_ORDERS, MENU_REFERRAL, 
        MENU_SUPPORT, MENU_INFO, MENU_RULES, MENU_ADMIN, MENU_BROADCAST
    )
    
    def _is_support_related(self, event: Any) -> bool:
        """Проверяет, относится ли событие к поддержке"""
        if isinstance(event, Message):
            # Разрешаем кнопку поддержки
            if event.text == MENU_SUPPORT:
                return True
            
            # Разрешаем сообщения для поддержки (не команды, не кнопки меню)
            if event.text and not event.text.startswith('/'):
                if event.text not in self.MENU_BUTTONS:
                    return True
            
            # Разрешаем медиа-сообщения (фото, документы и т.д.) для поддержки
            if event.photo or event.document or event.video or event.voice or event.audio:
                return True
        
        return False
    
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        # Получаем user_id и проверяем тип события
        user_id = None
        is_callback = False
        callback_data = None
        
        if isinstance(event, Message):
            if event.from_user:
                user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            if event.from_user:
                user_id = event.from_user.id
            is_callback = True
            callback_data = event.data
        
        if not user_id:
            return await handler(event, data)
        
        # Пропускаем проверку для админских обработчиков
        if callback_data and any(callback_data.startswith(prefix) for prefix in self.ADMIN_PREFIXES):
            return await handler(event, data)
        
        # Пропускаем проверку для админов и разработчиков из .env
        if user_id in settings.admin_ids_list or user_id in settings.developer_ids_list:
            return await handler(event, data)
        
        # Проверяем блокировку в БД
        session = data.get("session")
        if session:
            stmt = select(User).where(User.telegram_id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            
            if user and user.is_blocked:
                # Разрешаем доступ к поддержке для заблокированных пользователей
                if self._is_support_related(event):
                    return await handler(event, data)
                
                blocked_message = (
                    "❌ <b>Вы заблокированы</b>\n\n"
                    "Ваш доступ к боту ограничен администратором.\n"
                    "Если вы считаете, что это ошибка, обратитесь в поддержку."
                )
                
                if is_callback:
                    try:
                        await event.message.edit_text(blocked_message, parse_mode="HTML")
                    except:
                        await event.answer("Вы заблокированы", show_alert=True)
                    return
                else:
                    await event.answer(blocked_message, parse_mode="HTML")
                    return
        
        return await handler(event, data)
