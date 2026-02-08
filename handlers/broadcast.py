"""Обработчик рассылки"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.models import User
from config import settings
import asyncio
import logging

logger = logging.getLogger(__name__)

router = Router()


def get_all_menu_buttons():
    """Получить все кнопки меню"""
    from utils.text import MENU_CATALOG, MENU_BALANCE, MENU_ORDERS, MENU_REFERRAL, MENU_SUPPORT, MENU_INFO, MENU_RULES, MENU_ADMIN, MENU_BROADCAST
    return [MENU_CATALOG, MENU_BALANCE, MENU_ORDERS, MENU_REFERRAL, MENU_SUPPORT, MENU_INFO, MENU_RULES, MENU_ADMIN, MENU_BROADCAST, "📢 Рассылка", "⚙️ Пункт управления"]


async def check_menu_button_and_clear_state(message: Message, state: FSMContext) -> bool:
    """Проверить, является ли сообщение кнопкой меню, и очистить состояние если да"""
    if message.text:
        menu_buttons = get_all_menu_buttons()
        if message.text in menu_buttons or message.text.startswith('/'):
            await state.clear()
            return True
    return False


class BroadcastStates(StatesGroup):
    """Состояния для рассылки"""
    waiting_message = State()
    waiting_user_id = State()


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    return user_id in settings.admin_ids_list


@router.message(F.text == "📢 Рассылка")
async def broadcast_menu(message: Message, state: FSMContext):
    """Меню рассылки"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен")
        return
    
    # Очищаем предыдущее состояние, если оно было
    await state.clear()
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Массовая рассылка", callback_data="broadcast_mass")],
        [InlineKeyboardButton(text="👤 Индивидуальная рассылка", callback_data="broadcast_individual")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    
    await message.answer(
        "📢 <b>Рассылка</b>\n\n"
        "Выберите тип рассылки:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.callback_query(F.data == "broadcast_mass")
async def broadcast_mass_start(callback: CallbackQuery, state: FSMContext):
    """Начать массовую рассылку"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await state.update_data(broadcast_type="mass")
    await state.set_state(BroadcastStates.waiting_message)
    
    from utils.keyboards import get_back_keyboard
    await callback.message.edit_text(
        "📢 <b>Массовая рассылка</b>\n\n"
        "Отправьте сообщение для рассылки всем пользователям:",
        reply_markup=get_back_keyboard("admin_menu"),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "broadcast_individual")
async def broadcast_individual_start(callback: CallbackQuery, state: FSMContext):
    """Начать индивидуальную рассылку"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await state.update_data(broadcast_type="individual")
    await state.set_state(BroadcastStates.waiting_user_id)
    
    await callback.message.edit_text(
        "👤 <b>Индивидуальная рассылка</b>\n\n"
        "Введите ID пользователя:",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(BroadcastStates.waiting_user_id)
async def process_user_id(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка ID пользователя для индивидуальной рассылки"""
    # Проверяем, не выбрана ли кнопка меню
    if await check_menu_button_and_clear_state(message, state):
        return
    
    try:
        user_id = int(message.text)
        await state.update_data(target_user_id=user_id)
        await message.answer(
            "👤 <b>Индивидуальная рассылка</b>\n\n"
            "Отправьте сообщение для пользователя:"
        )
        await state.set_state(BroadcastStates.waiting_message)
    except ValueError:
        await message.answer("Введите корректный ID пользователя (число):")


async def send_broadcast_message(
    bot,
    user_id: int,
    message_text: str,
    message_photo: str = None,
    message_document: str = None
):
    """Отправить сообщение пользователю"""
    try:
        if message_photo:
            await bot.send_photo(user_id, message_photo, caption=message_text)
        elif message_document:
            await bot.send_document(user_id, message_document, caption=message_text)
        else:
            await bot.send_message(user_id, message_text)
        return True
    except Exception as e:
        logger.error(f"Error sending message to user {user_id}: {e}")
        return False


@router.message(BroadcastStates.waiting_message)
async def process_broadcast_message(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка сообщения для рассылки"""
    # Проверяем, не выбрана ли кнопка меню
    if await check_menu_button_and_clear_state(message, state):
        return
    
    data = await state.get_data()
    broadcast_type = data.get("broadcast_type")
    
    if not broadcast_type:
        await message.answer("Ошибка. Начните заново.")
        await state.clear()
        return
    
    if broadcast_type == "mass":
        # Массовая рассылка
        await message.answer("📢 Начинаю массовую рассылку...")
        
        stmt = select(User).where(User.is_blocked == False)
        result = await session.execute(stmt)
        users = result.scalars().all()
        
        total = len(users)
        success = 0
        failed = 0
        
        # Throttling: не более 25 сообщений в секунду
        throttle_delay = 1.0 / settings.BROADCAST_THROTTLE
        
        for user in users:
            try:
                # Определяем тип сообщения
                if message.photo:
                    await send_broadcast_message(
                        message.bot,
                        user.telegram_id,
                        message.caption or "",
                        message_photo=message.photo[-1].file_id
                    )
                elif message.document:
                    await send_broadcast_message(
                        message.bot,
                        user.telegram_id,
                        message.caption or "",
                        message_document=message.document.file_id
                    )
                else:
                    await send_broadcast_message(
                        message.bot,
                        user.telegram_id,
                        message.text
                    )
                success += 1
            except Exception as e:
                logger.error(f"Error sending to user {user.telegram_id}: {e}")
                failed += 1
            
            # Throttling
            await asyncio.sleep(throttle_delay)
        
        await message.answer(
            f"✅ Рассылка завершена!\n"
            f"Всего: {total}\n"
            f"Успешно: {success}\n"
            f"Ошибок: {failed}"
        )
        
    elif broadcast_type == "individual":
        # Индивидуальная рассылка
        target_user_id = data.get("target_user_id")
        
        try:
            if message.photo:
                await send_broadcast_message(
                    message.bot,
                    target_user_id,
                    message.caption or "",
                    message_photo=message.photo[-1].file_id
                )
            elif message.document:
                await send_broadcast_message(
                    message.bot,
                    target_user_id,
                    message.caption or "",
                    message_document=message.document.file_id
                )
            else:
                await send_broadcast_message(
                    message.bot,
                    target_user_id,
                    message.text
                )
            
            await message.answer(f"✅ Сообщение отправлено пользователю {target_user_id}")
        except Exception as e:
            logger.error(f"Error sending to user {target_user_id}: {e}")
            await message.answer(f"❌ Ошибка при отправке: {e}")
    
    await state.clear()

