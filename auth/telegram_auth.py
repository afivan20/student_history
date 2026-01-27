"""
Telegram Web App Authentication Validator
Проверка HMAC-SHA256 подписи initData от Telegram
"""
import hmac
import hashlib
from urllib.parse import parse_qsl
from typing import Optional, Dict
import time
import json


class TelegramAuthValidator:
    """Валидация Telegram Web App initData"""

    def __init__(self, bot_token: str):
        """
        Args:
            bot_token: Telegram Bot Token от @BotFather
        """
        self.bot_token = bot_token

    def validate_init_data(self, init_data: str, max_age: int = 3600) -> Optional[Dict]:
        """
        Проверить подпись Telegram initData

        Args:
            init_data: строка из window.Telegram.WebApp.initData
            max_age: максимальный возраст данных в секундах (защита от replay)

        Returns:
            Dict с данными пользователя или None если невалидно
            {
                'telegram_id': str,
                'username': str | None,
                'first_name': str | None,
                'last_name': str | None,
                'auth_date': int
            }
        """
        try:
            # Парсим query string
            params = dict(parse_qsl(init_data))

            # Извлекаем hash
            received_hash = params.pop('hash', None)
            if not received_hash:
                return None

            # Проверяем auth_date (защита от replay атак)
            auth_date = int(params.get('auth_date', 0))
            current_time = int(time.time())
            if current_time - auth_date > max_age:
                return None

            # Создаём data_check_string
            data_check_string = '\n'.join(
                f"{k}={v}" for k, v in sorted(params.items())
            )

            # Вычисляем secret_key = HMAC-SHA256(bot_token, "WebAppData")
            secret_key = hmac.new(
                key=b"WebAppData",
                msg=self.bot_token.encode(),
                digestmod=hashlib.sha256
            ).digest()

            # Вычисляем hash
            calculated_hash = hmac.new(
                key=secret_key,
                msg=data_check_string.encode(),
                digestmod=hashlib.sha256
            ).hexdigest()

            # Сравниваем хэши (защита от timing attacks)
            if not hmac.compare_digest(calculated_hash, received_hash):
                return None

            # Парсим user данные (они передаются как JSON строка)
            user_data = json.loads(params.get('user', '{}'))

            return {
                'telegram_id': str(user_data.get('id')),
                'username': user_data.get('username'),
                'first_name': user_data.get('first_name'),
                'last_name': user_data.get('last_name'),
                'auth_date': auth_date,
            }

        except Exception as e:
            print(f"Telegram auth validation error: {e}")
            return None
