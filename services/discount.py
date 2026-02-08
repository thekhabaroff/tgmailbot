"""Расчет скидок"""
from typing import Dict


def calculate_discount(quantity: int) -> float:
    """
    Расчет скидки в зависимости от количества
    Пример: 500 почт = -5%, 1000 почт = -10%
    """
    # Можно настроить через БД или конфиг
    discount_rules = {
        500: 5,
        1000: 10,
        2000: 15,
        5000: 20
    }
    
    # Находим максимальную скидку для данного количества
    max_discount = 0
    for threshold, discount in sorted(discount_rules.items(), reverse=True):
        if quantity >= threshold:
            max_discount = discount
            break
    
    return max_discount


def calculate_total_price(price_per_unit: float, quantity: int) -> tuple[float, float]:
    """
    Расчет итоговой цены с учетом скидки
    Возвращает: (скидка в процентах, итоговая сумма)
    """
    discount_percent = calculate_discount(quantity)
    total = price_per_unit * quantity
    discount_amount = total * (discount_percent / 100)
    final_total = total - discount_amount
    
    return discount_percent, final_total

