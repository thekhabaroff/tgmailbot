"""Интеграция платежных систем"""
import hashlib
import hmac
import json
from typing import Optional, Dict, Any
from aiohttp import ClientSession
from config import settings
import logging

logger = logging.getLogger(__name__)


class PaymentService:
    """Сервис для работы с платежными системами"""
    
    @staticmethod
    async def create_yookassa_payment(amount: float, order_id: int, user_id: int) -> Optional[Dict]:
        """Создать платеж в ЮКасса"""
        if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
            return None
        
        try:
            import base64
            auth_string = f"{settings.YOOKASSA_SHOP_ID}:{settings.YOOKASSA_SECRET_KEY}"
            auth_header = base64.b64encode(auth_string.encode()).decode()
            
            async with ClientSession() as session:
                payload = {
                    "amount": {
                        "value": f"{amount:.2f}",
                        "currency": "RUB"
                    },
                    "confirmation": {
                        "type": "redirect",
                        "return_url": f"https://t.me/{settings.BOT_NAME}"
                    },
                    "description": f"Заказ #{order_id}" if order_id else f"Пополнение баланса",
                    "metadata": {
                        "order_id": order_id if order_id else 0,
                        "user_id": user_id
                    }
                }
                
                headers = {
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/json"
                }
                
                async with session.post(
                    "https://api.yookassa.ru/v3/payments",
                    json=payload,
                    headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "payment_id": data.get("id"),
                            "payment_url": data.get("confirmation", {}).get("confirmation_url")
                        }
        except Exception as e:
            logger.error(f"YooKassa payment creation error: {e}")
        
        return None
    
    
    @staticmethod
    async def create_heleket_payment(amount: float, order_id: int, user_id: int) -> Optional[Dict]:
        """Создать платеж в Heleket"""
        if not settings.HELEKET_API_KEY:
            return None
        
        try:
            async with ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {settings.HELEKET_API_KEY}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "amount": amount,
                    "order_id": str(order_id) if order_id else "0",
                    "user_id": user_id
                }
                
                async with session.post(
                    "https://api.heleket.com/v1/payments/create",
                    json=payload,
                    headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "payment_id": data.get("payment_id"),
                            "payment_url": data.get("payment_url")
                        }
        except Exception as e:
            logger.error(f"Heleket payment creation error: {e}")
        
        return None
    
    @staticmethod
    def verify_yookassa_webhook(data: Dict[str, Any], signature: str) -> bool:
        """Проверка подписи webhook от ЮКасса"""
        if not settings.YOOKASSA_SECRET_KEY:
            return False
        
        try:
            # ЮКасса использует SHA-256 HMAC для подписи
            # Формируем строку для подписи из данных
            event_type = data.get("event")
            payment_id = data.get("object", {}).get("id", "")
            
            # Создаем строку для проверки
            message = f"{event_type}#{payment_id}"
            
            # Вычисляем HMAC
            expected_signature = hmac.new(
                settings.YOOKASSA_SECRET_KEY.encode(),
                message.encode(),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(expected_signature, signature)
        except Exception as e:
            logger.error(f"YooKassa webhook verification error: {e}")
            return False
    
    @staticmethod
    def verify_heleket_webhook(data: Dict[str, Any], signature: str) -> bool:
        """Проверка подписи webhook от Heleket"""
        if not settings.HELEKET_API_KEY:
            return False
        
        try:
            # Heleket использует HMAC-SHA256 для подписи
            # Формируем строку из данных
            payload_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
            
            # Вычисляем HMAC
            expected_signature = hmac.new(
                settings.HELEKET_API_KEY.encode(),
                payload_str.encode(),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(expected_signature, signature)
        except Exception as e:
            logger.error(f"Heleket webhook verification error: {e}")
            return False
    
    @staticmethod
    async def get_yookassa_payment_status(payment_id: str) -> Optional[Dict]:
        """Получить статус платежа в ЮКасса"""
        if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
            return None
        
        try:
            import base64
            auth_string = f"{settings.YOOKASSA_SHOP_ID}:{settings.YOOKASSA_SECRET_KEY}"
            auth_header = base64.b64encode(auth_string.encode()).decode()
            
            async with ClientSession() as session:
                headers = {
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/json"
                }
                
                async with session.get(
                    f"https://api.yookassa.ru/v3/payments/{payment_id}",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        return await response.json()
        except Exception as e:
            logger.error(f"YooKassa payment status error: {e}")
        
        return None
    
    @staticmethod
    async def get_heleket_payment_status(payment_id: str) -> Optional[Dict]:
        """Получить статус платежа в Heleket"""
        if not settings.HELEKET_API_KEY:
            return None
        
        try:
            async with ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {settings.HELEKET_API_KEY}",
                    "Content-Type": "application/json"
                }
                
                async with session.get(
                    f"https://api.heleket.com/v1/payments/{payment_id}",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        return await response.json()
        except Exception as e:
            logger.error(f"Heleket payment status error: {e}")
        
        return None
    