"""
Сервис отправки сообщений через Telegram бота
"""
import aiohttp
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

import os
from typing import Optional, Dict, Any

from models import TelegramAuth, SentMessage





class TelegramAPIClient:
    """Клиент для работы с Telegram Bot API"""
    
    def __init__(self, bot_token: str, timeout: int = 30):
        """
        Args:
            bot_token: Токен Telegram бота
            timeout: Таймаут запроса в секундах
        """
        self.bot_token = bot_token
        self.timeout = timeout
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, aiohttp.ServerTimeoutError))
    )
    async def send_message(
        self,
        telegram_id: int,
        text: str,
        parse_mode: str = "HTML",
    ) -> Dict[str, Any]:
        """
        Отправить сообщение через Telegram Bot API
        
        Args:
            telegram_id: ID чата получателя
            text: Текст сообщения
            parse_mode: Форматирование (HTML или Markdown)
            disable_web_page_preview: Отключить предпросмотр ссылок
            disable_notification: Отключить уведомление
            
        Returns:
            dict: Ответ Telegram API
            
        Raises:
            aiohttp.ClientError: При ошибках сети
            ValueError: При ошибках API Telegram
        """
        url = f"{self.base_url}/sendMessage"
        
        payload = {
            "chat_id": telegram_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as response:
                    result = await response.json()
                    
                    if not result.get("ok", False):
                        error_description = result.get("description", "Unknown Telegram API error")
                        print(f"Telegram API error: {error_description}")
                        raise ValueError(f"Telegram API error: {error_description}")
                    
                    print(f"Message sent successfully to telegram_id {telegram_id}")
                    return result
                    
        except aiohttp.ServerTimeoutError:
            print(f"Timeout sending message to telegram_id {telegram_id}")
            raise
        except aiohttp.ClientError as e:
            print(f"Network error sending message to telegram_id {telegram_id}: {str(e)}")
            raise


async def send_telegram_message(
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
        telegram_api_client = TelegramAPIClient(bot_token=os.getenv("TELEGRAM_BOT_TOKEN"))
        result = await telegram_api_client.send_message(
            telegram_id=int(telegram_auth.telegram_id),
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
