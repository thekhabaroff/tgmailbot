"""Сервис промоакций и скидок"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from database.models import Promotion, Coupon, Product, Order
from datetime import datetime
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


async def get_active_promotion(
    session: AsyncSession,
    product_id: int,
    quantity: int
) -> Optional[Promotion]:
    """Получить активную промоакцию для товара"""
    now = datetime.now()
    
    stmt = select(Promotion).where(
        and_(
            Promotion.is_active == True,
            Promotion.start_date <= now,
            Promotion.end_date >= now,
            Promotion.min_quantity <= quantity,
            (Promotion.product_id == product_id) | (Promotion.product_id.is_(None))
        )
    ).order_by(Promotion.discount_value.desc())
    
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def apply_promotion(
    base_price: float,
    quantity: int,
    promotion: Promotion
) -> Tuple[float, float]:
    """
    Применить промоакцию
    Возвращает: (скидка, итоговая цена)
    """
    if promotion.discount_type == "PERCENT":
        discount = base_price * quantity * (promotion.discount_value / 100)
    else:  # FIXED
        discount = promotion.discount_value * quantity
    
    total = (base_price * quantity) - discount
    return (discount, total)


async def validate_coupon(
    session: AsyncSession,
    coupon_code: str
) -> Optional[Tuple[Coupon, str]]:
    """
    Проверить промокод
    Возвращает: (Coupon, error_message) или (None, None) если валиден
    """
    stmt = select(Coupon).where(Coupon.code == coupon_code.upper())
    result = await session.execute(stmt)
    coupon = result.scalar_one_or_none()
    
    if not coupon:
        return (None, "Промокод не найден")
    
    if not coupon.is_active:
        return (None, "Промокод неактивен")
    
    now = datetime.now()
    if now < coupon.valid_from or now > coupon.valid_until:
        return (None, "Промокод недействителен")
    
    if coupon.max_uses and coupon.used_count >= coupon.max_uses:
        return (None, "Промокод исчерпан")
    
    return (coupon, None)


async def apply_coupon(
    total_amount: float,
    coupon: Coupon
) -> Tuple[float, float]:
    """
    Применить промокод
    Возвращает: (скидка, итоговая цена)
    """
    if coupon.discount_type == "PERCENT":
        discount = total_amount * (coupon.discount_value / 100)
    else:  # FIXED
        discount = min(coupon.discount_value, total_amount)
    
    total = total_amount - discount
    return (discount, total)


async def use_coupon(session: AsyncSession, coupon_id: int):
    """Использовать промокод (увеличить счетчик)"""
    from sqlalchemy import update
    
    await session.execute(
        update(Coupon)
        .where(Coupon.id == coupon_id)
        .values(used_count=Coupon.used_count + 1)
    )
    await session.commit()
