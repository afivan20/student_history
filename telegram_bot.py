"""
Telegram Bot - Отправка сообщений по команде /start
"""
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# Токен бота из переменных окружения
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""

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