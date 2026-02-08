"""Обработчик реферальной системы"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database.models import User, ReferralTransaction
from utils.keyboards import get_main_menu_keyboard, get_back_keyboard
from utils.text import get_referral_text, MENU_REFERRAL
from config import settings

router = Router()


@router.message(F.text == MENU_REFERRAL)
async def show_referral(message: Message, session: AsyncSession, state: FSMContext):
    """Показать реферальную ссылку и статистику"""
    # Очищаем FSM состояние при переходе в реферальную систему
    await state.clear()
    
    user_id = message.from_user.id
    
    stmt = select(User).where(User.telegram_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user or not user.referral_code:
        await message.answer("Пользователь не найден. Используйте /start")
        return
    
    # Получаем список рефералов
    stmt_referrals = select(User).where(User.referred_by == user.id)
    result_referrals = await session.execute(stmt_referrals)
    referrals = result_referrals.scalars().all()
    
    # Получаем статистику по комиссиям
    stmt_stats = select(
        func.count(ReferralTransaction.id).label('total_transactions'),
        func.sum(ReferralTransaction.commission).label('total_commission')
    ).where(ReferralTransaction.referrer_id == user.id)
    result_stats = await session.execute(stmt_stats)
    stats = result_stats.first()
    
    total_transactions = stats.total_transactions or 0
    total_commission = stats.total_commission or 0.0
    
    # Формируем текст
    referral_text = get_referral_text(user.referral_code)
    
    stats_text = f"""

📊 <b>Статистика рефералов:</b>
👥 Всего рефералов: {len(referrals)}
💰 Заработано комиссий: {total_commission:.2f} ₽
📦 Всего транзакций: {total_transactions}
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Подробная статистика", callback_data="referral_stats")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    
    await message.answer(
        referral_text + stats_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.callback_query(F.data == "referral_stats")
async def show_referral_stats(callback: CallbackQuery, session: AsyncSession):
    """Показать подробную статистику рефералов"""
    user_id = callback.from_user.id
    
    stmt = select(User).where(User.telegram_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    # Получаем список рефералов
    stmt_referrals = select(User).where(User.referred_by == user.id)
    result_referrals = await session.execute(stmt_referrals)
    referrals = result_referrals.scalars().all()
    
    # Получаем последние транзакции
    stmt_transactions = select(ReferralTransaction).where(
        ReferralTransaction.referrer_id == user.id
    ).order_by(ReferralTransaction.created_at.desc()).limit(20)
    result_transactions = await session.execute(stmt_transactions)
    transactions = result_transactions.scalars().all()
    
    # Получаем общую статистику
    stmt_stats = select(
        func.count(ReferralTransaction.id).label('total_transactions'),
        func.sum(ReferralTransaction.commission).label('total_commission'),
        func.sum(ReferralTransaction.amount).label('total_amount')
    ).where(ReferralTransaction.referrer_id == user.id)
    result_stats = await session.execute(stmt_stats)
    stats = result_stats.first()
    
    total_transactions = stats.total_transactions or 0
    total_commission = stats.total_commission or 0.0
    total_amount = stats.total_amount or 0.0
    
    # Формируем текст
    text = f"📊 <b>Подробная статистика рефералов</b>\n\n"
    text += f"👥 Всего рефералов: {len(referrals)}\n"
    text += f"💰 Заработано комиссий: {total_commission:.2f} ₽\n"
    text += f"📦 Всего транзакций: {total_transactions}\n"
    text += f"💵 Общая сумма покупок рефералов: {total_amount:.2f} ₽\n\n"
    
    if referrals:
        text += "<b>Список рефералов:</b>\n"
        for i, ref in enumerate(referrals[:30], 1):  # Показываем первые 30
            username = f"@{ref.username}" if ref.username else f"ID: {ref.telegram_id}"
            name = ref.first_name or ""
            text += f"{i}. {name} ({username})\n"
        
        if len(referrals) > 30:
            text += f"\n... и еще {len(referrals) - 30} рефералов\n"
    else:
        text += "📭 У вас пока нет рефералов\n"
    
    if transactions:
        text += "\n<b>Последние комиссии:</b>\n"
        for trans in transactions[:10]:  # Показываем последние 10
            text += f"• +{trans.commission:.2f} ₽ (заказ #{trans.order_id}, сумма: {trans.amount:.2f} ₽)\n"
        
        if len(transactions) > 10:
            text += f"\n... и еще {len(transactions) - 10} транзакций\n"
    else:
        text += "\n📭 Пока нет транзакций с рефералами"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

