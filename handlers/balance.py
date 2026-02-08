"""Обработчик баланса"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from database.models import User, Payment
from utils.keyboards import get_balance_topup_keyboard
from utils.text import get_balance_text
from services.payment import PaymentService
from config import settings
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = Router()


class TopupStates(StatesGroup):
    """Состояния для пополнения баланса"""
    waiting_amount = State()


@router.message(F.text == "💰 Баланс")
async def show_balance(message: Message, session: AsyncSession, state: FSMContext):
    """Показать баланс"""
    # Очищаем FSM состояние при переходе в баланс
    await state.clear()
    
    user_id = message.from_user.id
    
    stmt = select(User).where(User.telegram_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        await message.answer("Пользователь не найден. Используйте /start")
        return
    
    await message.answer(
        get_balance_text(user.balance),
        reply_markup=get_balance_topup_keyboard()
    )


@router.callback_query(F.data.startswith("topup_"))
async def process_topup(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Обработка пополнения баланса"""
    method = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    stmt = select(User).where(User.telegram_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    # Пополнение через администратора
    if method == "admin":
        await callback.message.edit_text(
            "ℹ️ <b>Пополнение баланса</b>\n\n"
            "Обратитесь к администратору для пополнения баланса.\n\n"
            "Администратор сможет пополнить ваш баланс через пункт управления.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
            ])
        )
        await callback.answer()
        return
    
    # Реальное пополнение через платежные системы
    if method in ["yookassa", "heleket"]:
        method_name = "ЮКасса" if method == "yookassa" else "Heleket"
        await callback.message.edit_text(
            f"💳 <b>Пополнение баланса через {method_name}</b>\n\n"
            "Введите сумму пополнения (минимум 1 ₽):",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
            ])
        )
        await state.update_data(topup_method=method)
        await state.set_state(TopupStates.waiting_amount)
        await callback.answer()
        return


@router.message(TopupStates.waiting_amount)
async def process_topup_amount(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка суммы пополнения"""
    # Проверяем, не выбрана ли кнопка меню
    from utils.text import MENU_CATALOG, MENU_BALANCE, MENU_ORDERS, MENU_REFERRAL, MENU_SUPPORT, MENU_INFO, MENU_RULES, MENU_ADMIN, MENU_BROADCAST
    menu_buttons = [MENU_CATALOG, MENU_BALANCE, MENU_ORDERS, MENU_REFERRAL, MENU_SUPPORT, MENU_INFO, MENU_RULES, MENU_ADMIN, MENU_BROADCAST, "📢 Рассылка", "⚙️ Пункт управления"]
    
    if message.text and (message.text in menu_buttons or message.text.startswith('/')):
        await state.clear()
        return
    
    try:
        amount = float(message.text)
        if amount < 1:
            from utils.keyboards import get_back_keyboard
            await message.answer(
                "Минимальная сумма пополнения: 1 ₽. Введите сумму:",
                reply_markup=get_back_keyboard()
            )
            return
        
        data = await state.get_data()
        method = data.get("topup_method")
        user_id = message.from_user.id
        
        stmt = select(User).where(User.telegram_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("Пользователь не найден")
            await state.clear()
            return
        
        # Создаем платеж через выбранную платежную систему
        payment_data = None
        method_name = ""
        try:
            if method == "yookassa":
                method_name = "ЮКасса"
                payment_data = await PaymentService.create_yookassa_payment(amount, None, user.id)
            elif method == "heleket":
                method_name = "Heleket"
                payment_data = await PaymentService.create_heleket_payment(amount, None, user.id)
            else:
                await message.answer(
                    "❌ Неизвестный способ оплаты.\n"
                    "Обратитесь в поддержку.",
                    parse_mode="HTML"
                )
                await state.clear()
                return
        except Exception as e:
            logger.error(f"Error creating payment via {method_name}: {e}", exc_info=True)
            await message.answer(
                f"❌ <b>Ошибка создания платежа</b>\n\n"
                f"Не удалось создать платеж через {method_name}.\n"
                "Проверьте настройки платежной системы в конфигурации.\n\n"
                "Обратитесь в поддержку или используйте пополнение через администратора.",
                parse_mode="HTML"
            )
            await state.clear()
            return
        
        if payment_data and payment_data.get("payment_url"):
            # Сохраняем платеж
            payment = Payment(
                user_id=user.id,
                amount=amount,
                payment_method=method,
                payment_id=payment_data.get("payment_id"),
                status="PENDING"
            )
            session.add(payment)
            await session.commit()
            
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_data.get("payment_url"))],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
            ])
            
            method_display = "ЮКасса" if method == "yookassa" else "Heleket"
            await message.answer(
                f"💳 <b>Пополнение баланса</b>\n\n"
                f"Сумма: {amount:.2f} ₽\n"
                f"Способ: {method_display}\n\n"
                f"Перейдите по ссылке для оплаты.\n"
                f"После оплаты баланс будет пополнен автоматически.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            await message.answer(
                "❌ Ошибка создания платежа.\n"
                "Проверьте настройки платежной системы или обратитесь в поддержку."
            )
        
        await state.clear()
        
    except ValueError:
        await message.answer("Введите корректную сумму (число, например: 100 или 100.50):")

