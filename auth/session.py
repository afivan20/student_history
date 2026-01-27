"""
Session Management Utilities
Работа с cookies для аутентификации
"""
from fastapi import Response


def set_token_cookie(response: Response, token: str, max_age: int = 31536000):
    """
    Установить UUID токен в cookie

    Args:
        response: FastAPI response
        token: UUID токен
        max_age: время жизни в секундах (по умолчанию 1 год)
    """
    response.set_cookie(
        key="access_token",
        value=token,
        max_age=max_age,
        httponly=True,  # Защита от XSS
        secure=True,    # Только HTTPS
        samesite="none"  # Разрешить в iframe (Telegram Web App)
    )


def clear_token_cookie(response: Response):
    """Удалить токен из cookie"""
    response.delete_cookie(
        key="access_token",
        secure=True,
        samesite="none"
    )


def set_telegram_session(response: Response, telegram_id: str, selected_student_id: int = None):
    """
    Установить данные Telegram сессии в cookies.

    Args:
        response: FastAPI response
        telegram_id: Telegram user ID
        selected_student_id: ID выбранного студента (если несколько привязок)
    """
    response.set_cookie(
        key="telegram_id",
        value=telegram_id,
        max_age=86400,  # 24 часа
        httponly=True,
        secure=True,
        samesite="none"
    )

    if selected_student_id is not None:
        response.set_cookie(
            key="selected_student_id",
            value=str(selected_student_id),
            max_age=86400,  # 24 часа
            httponly=True,
            secure=True,
            samesite="none"
        )


def clear_telegram_session(response: Response):
    """Удалить Telegram сессию из cookies"""
    response.delete_cookie(key="telegram_id", secure=True, samesite="none")
    response.delete_cookie(key="selected_student_id", secure=True, samesite="none")


def get_telegram_session(request) -> tuple:
    """
    Получить данные Telegram сессии из cookies.

    Returns:
        Tuple (telegram_id, selected_student_id) или (None, None)
    """
    telegram_id = request.cookies.get("telegram_id")
    selected_str = request.cookies.get("selected_student_id")

    selected_student_id = None
    if selected_str and selected_str.isdigit():
        selected_student_id = int(selected_str)

    return telegram_id, selected_student_id
