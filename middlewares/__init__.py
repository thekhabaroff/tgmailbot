"""Middlewares для бота"""
from middlewares.database import DatabaseMiddleware
from middlewares.blocked_user import BlockedUserMiddleware
from middlewares.error_handler import ErrorHandlerMiddleware
from middlewares.keyboard_update import KeyboardUpdateMiddleware

__all__ = [
    "DatabaseMiddleware",
    "BlockedUserMiddleware",
    "ErrorHandlerMiddleware",
    "KeyboardUpdateMiddleware",
]
