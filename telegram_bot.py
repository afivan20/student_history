"""
Telegram Bot - Отправка сообщений по команде /start
"""
import os
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# Токен бота из переменных окружения
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start - сохраняет chat_id и отправляет приветствие"""
    from database import SessionLocal
    from models import TelegramAuth, PendingTelegramLink

    user = update.effective_user
    chat_id = str(update.message.chat_id)
    telegram_id = str(user.id)

    # Сохранить chat_id в БД
    db = SessionLocal()
    try:
        # 1. Обновить TelegramAuth если пользователь уже привязан
        telegram_auths = db.query(TelegramAuth).filter(
            TelegramAuth.telegram_id == telegram_id,
            TelegramAuth.is_active == True
        ).all()

        for auth in telegram_auths:
            auth.chat_id = chat_id

        # 2. Если не привязан - обновить или создать PendingTelegramLink
        if not telegram_auths:
            pending = db.query(PendingTelegramLink).filter(
                PendingTelegramLink.telegram_id == telegram_id
            ).first()

            if pending:
                pending.chat_id = chat_id
                pending.last_attempt_at = datetime.utcnow()
                pending.telegram_username = user.username
                pending.telegram_first_name = user.first_name
                pending.telegram_last_name = user.last_name
            else:
                pending = PendingTelegramLink(
                    telegram_id=telegram_id,
                    chat_id=chat_id,
                    telegram_username=user.username,
                    telegram_first_name=user.first_name,
                    telegram_last_name=user.last_name
                )
                db.add(pending)

        db.commit()
    except Exception as e:
        print(f"❌ Ошибка сохранения chat_id: {e}")
        db.rollback()
    finally:
        db.close()

    # Отправить приветствие
    username_bot = os.getenv('TELEGRAM_BOT_NAME')
    welcome_message = (
        "👋 Привет! Я бот для отслеживания истории уроков.\n\n"
        "Чтобы посмотреть свою историю уроков и баланс:\n"
        f"Просто нажми [ЗАПУСТИТЬ / LAUNCH](https://t.me/{username_bot}?startapp)\n\n"
        "Или на кнопку в левом нижнем углу\n"
        f"👉 [посмотреть уроки](https://t.me/{username_bot}?startapp)\n\n")

    await update.message.reply_text(welcome_message, parse_mode='Markdown')

def create_bot_application():
    """Создать и настроить приложение бота"""
    if not BOT_TOKEN or BOT_TOKEN == 'YOUR_TELEGRAM_BOT_TOKEN_HERE':
        print("⚠️ Telegram bot token not configured in .env file")
        return None
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start_command))
    
    return application

async def start_bot():
    """Запустить бота в фоновом режиме"""
    application = create_bot_application()
    if application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        print("✅ Telegram bot started successfully")
        return application
    return None