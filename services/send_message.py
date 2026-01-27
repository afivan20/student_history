"""
Сервис отправки сообщений через Telegram бота
"""
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc
from models import TelegramAuth, SentMessage


async def send_telegram_message(
    bot_app,
    telegram_auth_id: int,
    message_text: str,
    sent_by: str,
    db: Session
) -> dict:
    """
    Отправить сообщение пользователю через Telegram бота

    Args:
        bot_app: Инстанс Telegram Bot Application
        telegram_auth_id: ID записи TelegramAuth
        message_text: Текст сообщения (max 4096 символов)
        sent_by: Имя админа
        db: SQLAlchemy сессия

    Returns:
        dict: {"success": bool, "message": str, "sent_message_id": int}
    """
    # Получить TelegramAuth
    telegram_auth = db.query(TelegramAuth).filter(
        TelegramAuth.id == telegram_auth_id,
        TelegramAuth.is_active == True
    ).first()

    if not telegram_auth:
        return {"success": False, "message": "Telegram привязка не найдена"}



    # Проверить длину сообщения
    if len(message_text) > 4096:
        return {"success": False, "message": "Сообщение слишком длинное (макс. 4096 символов)"}

    if not message_text.strip():
        return {"success": False, "message": "Сообщение не может быть пустым"}

    # Создать запись в истории
    sent_message = SentMessage(
        telegram_auth_id=telegram_auth_id,
        telegram_id=telegram_auth.telegram_id,
        message_text=message_text,
        sent_by=sent_by,
        delivery_status='pending'
    )
    db.add(sent_message)
    db.flush()  # Получить ID

    # Отправить через бота
    try:
        bot = bot_app.bot
        result = await bot.send_message(
            chat_id=int(telegram_auth.telegram_id),
            text=message_text,
            parse_mode='HTML'  # Поддержка базового форматирования
        )

        sent_message.delivery_status = 'sent'
        db.commit()

        return {
            "success": True,
            "message": "Сообщение отправлено",
            "sent_message_id": sent_message.id
        }

    except Exception as e:
        sent_message.delivery_status = 'failed'
        sent_message.error_message = str(e)[:500]  # Ограничить длину ошибки
        db.commit()

        return {
            "success": False,
            "message": f"Ошибка отправки: {str(e)}",
            "sent_message_id": sent_message.id
        }


def get_message_history(db: Session, limit: int = 50, telegram_auth_id: int = None) -> list:
    """
    Получить историю отправленных сообщений

    Args:
        db: SQLAlchemy сессия
        limit: Максимум записей
        telegram_auth_id: Фильтр по конкретному пользователю (опционально)

    Returns:
        list: Список SentMessage
    """
    query = db.query(SentMessage)

    if telegram_auth_id:
        query = query.filter(SentMessage.telegram_auth_id == telegram_auth_id)

    return query.order_by(desc(SentMessage.sent_at)).limit(limit).all()
