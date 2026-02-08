"""Конфигурация бота"""
from typing import List
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # Telegram
    BOT_TOKEN: str
    BOT_NAME: str
    
    # Database (PostgreSQL, async)
    # Пример: postgresql+asyncpg://user:password@localhost:5432/tgmailbot
    DATABASE_URL: str
    
    # Admins (comma-separated IDs)
    ADMIN_IDS: str
    # Developers (comma-separated IDs) - полный доступ, включая настройки
    DEVELOPER_IDS: str = ""
    
    # Payment Systems
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    
    ROBOKASSA_MERCHANT_LOGIN: str = ""
    ROBOKASSA_PASSWORD_1: str = ""
    ROBOKASSA_PASSWORD_2: str = ""
    
    LAVA_PROJECT_ID: str = ""
    LAVA_SECRET_KEY: str = ""
    
    HELEKET_API_KEY: str = ""
    
    # Support
    SUPPORT_CHAT: str = ""
    # Канал/чат для уведомлений администраторам (ID канала или username, например: -1001234567890 или @support_chat)
    # Для получения ID канала: добавьте бота в канал как администратора, затем отправьте любое сообщение в канал
    # Бот получит update с chat.id, который и будет ID канала
    # Если не указан, уведомления отправляются администраторам в личные сообщения
    NOTIFICATIONS_CHAT_ID: str = ""
    
    # Webhook (optional)
    WEBHOOK_HOST: str = ""
    WEBHOOK_PATH: str = "/webhook"
    WEBHOOK_URL: str = ""
    SSL_CERT_PATH: str = ""
    SSL_KEY_PATH: str = ""
    # Порт для webhook обработчиков платежных систем (ЮКасса, Heleket)
    PAYMENT_WEBHOOK_PORT: int = 8443
    # SSL сертификаты для webhook платежных систем
    PAYMENT_WEBHOOK_SSL_CERT_PATH: str = ""
    PAYMENT_WEBHOOK_SSL_KEY_PATH: str = ""
    # Использовать HTTPS для webhook платежных систем (требуется для продакшена)
    PAYMENT_WEBHOOK_USE_HTTPS: bool = False
    
    # Settings
    REFERRAL_COMMISSION: int = 10
    ORDER_RESERVATION_MINUTES: int = 15
    BROADCAST_THROTTLE: int = 25
    
    # ========== ТЕСТОВАЯ ОПЛАТА (для разработки) ==========
    # Установите в False или удалите эту настройку для продакшна
    # В продакшне также закомментируйте обработчик pay_test в handlers/payment.py
    ENABLE_TEST_PAYMENT: bool = True
    # ========================================================
    
    @property
    def admin_ids_list(self) -> List[int]:
        """Список ID администраторов"""
        if not self.ADMIN_IDS:
            return []
        return [int(uid.strip()) for uid in self.ADMIN_IDS.split(",") if uid.strip().isdigit()]
    
    @property
    def developer_ids_list(self) -> List[int]:
        """Список ID разработчиков"""
        if not self.DEVELOPER_IDS:
            return []
        return [int(uid.strip()) for uid in self.DEVELOPER_IDS.split(",") if uid.strip().isdigit()]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Игнорировать дополнительные поля в .env


settings = Settings()

