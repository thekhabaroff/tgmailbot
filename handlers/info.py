"""Обработчик информации и поддержки"""
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.models import Setting, User
from utils.text import (
    FAQ_TEXT, RULES_TEXT, get_support_text, 
    MENU_INFO, MENU_RULES, MENU_SUPPORT, MENU_CATALOG, MENU_BALANCE, 
    MENU_ORDERS, MENU_REFERRAL, MENU_ADMIN, MENU_BROADCAST
)
from config import settings
import logging

logger = logging.getLogger(__name__)

router = Router()


@router.message(F.text == MENU_INFO)
async def show_info(message: Message, session: AsyncSession, state: FSMContext):
    """Показать FAQ"""
    # Очищаем FSM состояние при переходе в информацию
    await state.clear()
    
    # Получаем FAQ из настроек или используем по умолчанию
    stmt = select(Setting).where(Setting.key == "faq_text")
    result = await session.execute(stmt)
    setting = result.scalar_one_or_none()
    faq_text = setting.value if setting and setting.value else FAQ_TEXT
    await message.answer(
        faq_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
    )


@router.message(F.text == MENU_RULES)
async def show_rules(message: Message, session: AsyncSession, state: FSMContext):
    """Показать правила"""
    # Очищаем FSM состояние при переходе в правила
    await state.clear()
    
    # Получаем правила из настроек или используем по умолчанию
    stmt = select(Setting).where(Setting.key == "rules_text")
    result = await session.execute(stmt)
    setting = result.scalar_one_or_none()
    rules_text = setting.value if setting and setting.value else RULES_TEXT
    await message.answer(
        rules_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
    )


@router.message(F.text == MENU_SUPPORT)
async def show_support(message: Message, session: AsyncSession, state: FSMContext):
    """Показать поддержку"""
    # Очищаем FSM состояние при переходе в поддержку
    await state.clear()
    
    # Получаем контакт поддержки из настроек или используем по умолчанию
    stmt = select(Setting).where(Setting.key == "support_chat")
    result = await session.execute(stmt)
    setting = result.scalar_one_or_none()
    
    # Проверяем, настроен ли чат поддержки
    stmt_chat_id = select(Setting).where(Setting.key == "support_chat_id")
    result_chat_id = await session.execute(stmt_chat_id)
    chat_id_setting = result_chat_id.scalar_one_or_none()
    
    if chat_id_setting and chat_id_setting.value:
        support_text = "💬 <b>Поддержка</b>\n\nНапишите ваше сообщение, и администратор обязательно вам ответит.\n\nВы можете отправить текст, фото или файл."
    elif setting and setting.value:
        support_text = f"💬 Для связи с поддержкой перейдите в чат: {setting.value}"
    else:
        support_text = get_support_text()
    
    from utils.keyboards import get_back_keyboard
    await message.answer(
        support_text,
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )


@router.message(F.chat.type.in_(["group", "supergroup"]))
async def handle_group_message(message: Message, session: AsyncSession):
    """Обработка сообщений в группе для автоматической настройки чата поддержки и ответов пользователям"""
    # Если это reply на сообщение - пересылаем пользователю
    if message.reply_to_message:
        await handle_support_reply(message, session)
        return
    
    # Если сообщение отправлено администратором, сохраняем ID чата
    if message.from_user and message.from_user.id in settings.admin_ids_list:
        chat_id = message.chat.id
        
        # Проверяем, не установлен ли уже чат поддержки
        stmt = select(Setting).where(Setting.key == "support_chat_id")
        result = await session.execute(stmt)
        setting = result.scalar_one_or_none()
        
        if not setting:
            setting = Setting(key="support_chat_id", value=str(chat_id))
            session.add(setting)
        elif setting.value != str(chat_id):
            setting.value = str(chat_id)
        
        await session.commit()
        logger.info(f"Support chat ID saved: {chat_id}")


async def handle_support_reply(message: Message, session: AsyncSession):
    """Обработка ответов от поддержки пользователям"""
    # Извлекаем user_id из текста оригинального сообщения
    original_text = message.reply_to_message.text or message.reply_to_message.caption or ""
    
    # Ищем ID пользователя в формате "ID: 123456789"
    import re
    user_id_match = re.search(r'ID:\s*(\d+)', original_text)
    
    if not user_id_match:
        # Если не нашли ID в тексте, проверяем, может это форвард от пользователя
        if message.reply_to_message.forward_from:
            user_id = message.reply_to_message.forward_from.id
        else:
            await message.reply("❌ Не удалось определить ID пользователя из сообщения.")
            return
    else:
        user_id = int(user_id_match.group(1))
    
    # Получаем пользователя из БД
    stmt = select(User).where(User.telegram_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        await message.reply(f"❌ Пользователь с ID {user_id} не найден в базе данных.")
        return
    
    # Отправляем ответ пользователю
    try:
        response_text = f"💬 <b>Ответ от поддержки:</b>\n\n{message.text or '[Медиа файл]'}"
        
        if message.photo:
            # Если в ответе есть фото
            photo = message.photo[-1]  # Берем самое качественное фото
            await message.bot.send_photo(
                user_id,
                photo=photo.file_id,
                caption=response_text if message.caption else "💬 <b>Ответ от поддержки</b>",
                parse_mode="HTML"
            )
        elif message.document:
            # Если в ответе есть документ
            await message.bot.send_document(
                user_id,
                document=message.document.file_id,
                caption=response_text if message.caption else "💬 <b>Ответ от поддержки</b>",
                parse_mode="HTML"
            )
        elif message.video:
            # Если в ответе есть видео
            await message.bot.send_video(
                user_id,
                video=message.video.file_id,
                caption=response_text if message.caption else "💬 <b>Ответ от поддержки</b>",
                parse_mode="HTML"
            )
        elif message.voice:
            # Если в ответе голосовое сообщение
            try:
                await message.bot.send_voice(
                    user_id,
                    voice=message.voice.file_id,
                    caption=response_text if message.caption else "💬 <b>Ответ от поддержки</b>",
                    parse_mode="HTML"
                )
            except Exception as voice_error:
                # Если голосовые сообщения запрещены пользователем, отправляем текстовое сообщение
                if "VOICE_MESSAGES_FORBIDDEN" in str(voice_error):
                    fallback_text = "💬 <b>Ответ от поддержки:</b>\n\n"
                    if message.caption:
                        fallback_text += message.caption
                    else:
                        fallback_text += "Вам отправлено голосовое сообщение, но у вас отключены голосовые сообщения в настройках приватности Telegram.\n\nПожалуйста, включите голосовые сообщения в настройках приватности или обратитесь в поддержку другим способом."
                    await message.bot.send_message(
                        user_id,
                        fallback_text,
                        parse_mode="HTML"
                    )
                else:
                    # Если другая ошибка, пробрасываем её дальше
                    raise
        elif message.text:
            # Если это просто текст
            await message.bot.send_message(
                user_id,
                response_text,
                parse_mode="HTML"
            )
        else:
            await message.reply("❌ Неподдерживаемый тип сообщения.")
            return
        
        # Подтверждаем отправку
        await message.reply(f"✅ Ответ отправлен пользователю {user.first_name or 'N/A'} (@{user.username or 'N/A'})")
        
    except Exception as e:
        logger.error(f"Failed to send reply to user {user_id}: {e}")
        await message.reply(f"❌ Не удалось отправить ответ пользователю: {e}")



async def forward_to_support_chat(message: Message, session: AsyncSession):
    """Пересылка сообщения пользователя в чат поддержки"""
    user_id = message.from_user.id
    
    # Получаем пользователя из БД
    stmt = select(User).where(User.telegram_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        await message.answer("Вы не зарегистрированы. Используйте /start")
        return False
    
    # Получаем ID чата поддержки
    stmt_chat = select(Setting).where(Setting.key == "support_chat_id")
    result_chat = await session.execute(stmt_chat)
    chat_setting = result_chat.scalar_one_or_none()
    
    support_chat_id = None
    if chat_setting and chat_setting.value:
        try:
            support_chat_id = int(chat_setting.value)
        except:
            pass
    
    # Если чат не настроен, отправляем администраторам в личные сообщения
    if not support_chat_id:
        admin_text = f"💬 <b>Сообщение от пользователя</b>\n\n"
        admin_text += f"👤 Пользователь: {user.first_name or 'N/A'}\n"
        admin_text += f"Username: @{user.username or 'N/A'}\n"
        admin_text += f"ID: {user.telegram_id}\n\n"
        admin_text += f"📝 Сообщение:\n{message.text or '[Медиа файл]'}"
        
        # Отправляем всем администраторам
        sent = False
        for admin_id in settings.admin_ids_list:
            try:
                if message.photo:
                    await message.forward(admin_id)
                    await message.bot.send_message(admin_id, admin_text, parse_mode="HTML")
                elif message.document:
                    await message.forward(admin_id)
                    await message.bot.send_message(admin_id, admin_text, parse_mode="HTML")
                else:
                    await message.bot.send_message(admin_id, admin_text, parse_mode="HTML")
                sent = True
            except Exception as e:
                logger.error(f"Failed to send support message to admin {admin_id}: {e}")
        
        if sent:
            await message.answer("✅ Ваше сообщение отправлено администратору. Ожидайте ответа.")
            return True
        else:
            await message.answer("❌ Не удалось отправить сообщение администратору. Попробуйте позже.")
            return False
    else:
        # Отправляем в чат поддержки
        try:
            admin_text = f"💬 <b>Сообщение от пользователя</b>\n\n"
            admin_text += f"👤 Пользователь: {user.first_name or 'N/A'}\n"
            admin_text += f"Username: @{user.username or 'N/A'}\n"
            admin_text += f"ID: {user.telegram_id}\n\n"
            admin_text += f"📝 Сообщение:\n{message.text or '[Медиа файл]'}"
            
            if message.photo:
                await message.forward(support_chat_id)
                await message.bot.send_message(support_chat_id, admin_text, parse_mode="HTML")
            elif message.document:
                await message.forward(support_chat_id)
                await message.bot.send_message(support_chat_id, admin_text, parse_mode="HTML")
            elif message.video:
                await message.forward(support_chat_id)
                await message.bot.send_message(support_chat_id, admin_text, parse_mode="HTML")
            else:
                await message.bot.send_message(support_chat_id, admin_text, parse_mode="HTML")
            
            await message.answer("✅ Ваше сообщение отправлено в поддержку. Ожидайте ответа.")
            return True
        except Exception as e:
            logger.error(f"Failed to send message to support chat {support_chat_id}: {e}")
            await message.answer("❌ Не удалось отправить сообщение в поддержку. Попробуйте позже.")
            return False


@router.message(F.chat.type == "private")
async def handle_user_message(message: Message, session: AsyncSession, state: FSMContext):
    """Обработка сообщений от пользователей для поддержки"""
    # Проверяем, что это не команда
    if message.text and message.text.startswith('/'):
        return  # Пропускаем команды
    
    # Проверяем, что это не кнопка меню (ПЕРВЫМ ДЕЛОМ!)
    menu_buttons = [MENU_CATALOG, MENU_BALANCE, MENU_ORDERS, MENU_REFERRAL, MENU_SUPPORT, MENU_INFO, MENU_RULES, MENU_ADMIN, MENU_BROADCAST]
    if message.text and message.text in menu_buttons:
        # Очищаем FSM состояние при переходе в другой раздел
        await state.clear()
        return  # Пропускаем кнопки меню (они обрабатываются другими роутерами)
    
    # Проверяем, что пользователь не в FSM состоянии (если в состоянии - пропускаем)
    current_state = await state.get_state()
    if current_state is not None:
        # Если пользователь в FSM состоянии другого обработчика, не обрабатываем здесь
        return  # Пропускаем, если пользователь в FSM состоянии
    
    # Проверяем, что это не администратор
    if message.from_user.id in settings.admin_ids_list:
        return  # Администраторы могут отправлять обычные сообщения
    
    # Пересылаем в поддержку
    await forward_to_support_chat(message, session)

