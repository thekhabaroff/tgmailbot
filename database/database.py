"""Подключение к базе данных"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from config import settings
import logging

logger = logging.getLogger(__name__)

# Создаем движок БД
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True
)

# Создаем фабрику сессий
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()


async def init_db():
    """Инициализация базы данных"""
    # Импортируем все модели, чтобы они зарегистрировались в Base.metadata
    from database import models  # noqa: F401
    try:
        async with engine.begin() as conn:
            # checkfirst=True предотвращает ошибки при повторном создании
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        raise


async def get_session() -> AsyncSession:
    """Получить сессию БД"""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()

