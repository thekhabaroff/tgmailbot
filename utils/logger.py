"""Логирование"""
import logging
import sys
from datetime import datetime
from pathlib import Path

# Создаем директорию для логов
Path("logs").mkdir(exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f"logs/bot_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


async def log_error_to_db(session, level: str, message: str, user_id: int = None, traceback: str = None):
    """Записать ошибку в БД"""
    try:
        from database.models import Log
        log_entry = Log(
            level=level,
            message=message,
            user_id=user_id,
            traceback=traceback
        )
        session.add(log_entry)
        await session.commit()
    except Exception as e:
        logger.error(f"Failed to log to database: {e}")

