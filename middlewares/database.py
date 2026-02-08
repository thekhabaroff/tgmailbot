"""Middleware для работы с базой данных"""
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from database.database import async_session_maker


class DatabaseMiddleware(BaseMiddleware):
    """Middleware для получения сессии БД"""
    
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        async with async_session_maker() as session:
            data["session"] = session
            return await handler(event, data)
