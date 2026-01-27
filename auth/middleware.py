"""
FastAPI Authentication Middleware
Определение текущего пользователя через Telegram или UUID токен
"""
from fastapi import Request, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from database import get_db_session
from models import Student, TelegramAuth
from auth.telegram_auth import TelegramAuthValidator
from auth.token_auth import TokenAuthValidator
from datetime import datetime
import os


class AuthContext:
    """Контекст аутентификации для request.state"""

    def __init__(self):
        self.student: Optional[Student] = None
        self.auth_method: Optional[str] = None  # 'telegram', 'token', None
        self.auth_identifier: Optional[str] = None
        self.telegram_id: Optional[str] = None  # Telegram ID (если известен)


async def get_current_student(
        request: Request,
        db: Session = Depends(get_db_session)
) -> Optional[Student]:
    """
    Dependency для получения текущего студента.

    ПРИОРИТЕТ ПРОВЕРКИ:
    1. UUID token в URL (явный запрос конкретного студента по ссылке)
    2. Telegram initData (если есть) - приоритет при входе через TG
       - Проверяет что привязка существует и активна
       - Использует selected_student_id из cookie если есть несколько привязок
    3. Telegram session cookies (для GET запросов после TG входа)
    4. UUID token из cookie (fallback)

    Returns:
        Student или None
    """
    from auth.session import get_telegram_session

    # 1. ВЫСШИЙ ПРИОРИТЕТ: Токен явно передан в URL
    # Это означает что пользователь открыл ссылку с токеном и хочет именно этого студента
    url_token = request.query_params.get('token')
    if url_token:
        student = TokenAuthValidator.validate_token(db, url_token)
        if student:
            request.state.auth = AuthContext()
            request.state.auth.student = student
            request.state.auth.auth_method = 'token'
            request.state.auth.auth_identifier = url_token

            return student
        else:
            # Токен передан но невалиден - НЕ fallback на другие методы
            # Пользователь явно запросил конкретный токен, отозванный токен = отказ
            return None

    # 2. Telegram initData (для fetch запросов из JS)
    telegram_init_data = request.headers.get('X-Telegram-Init-Data')

    if telegram_init_data:
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        if bot_token and bot_token != 'YOUR_TELEGRAM_BOT_TOKEN_HERE':
            validator = TelegramAuthValidator(bot_token)
            user_data = validator.validate_init_data(telegram_init_data)

            if user_data:
                telegram_id = user_data['telegram_id']

                # Найти ВСЕ активные привязки по Telegram ID
                telegram_auths = db.query(TelegramAuth).filter(
                    TelegramAuth.telegram_id == telegram_id,
                    TelegramAuth.is_active == True
                ).all()

                # Отфильтровать только активных студентов
                active_auths = [ta for ta in telegram_auths if ta.student.is_active]

                if not active_auths:
                    # Нет привязок - не авторизован
                    return None

                selected_student = None

                if len(active_auths) == 1:
                    # Один студент - автоматически выбираем
                    selected_student = active_auths[0].student
                else:
                    # Несколько студентов - проверяем selected_student_id из cookie
                    _, selected_student_id = get_telegram_session(request)

                    if selected_student_id:
                        # Проверить что selected_student_id соответствует одной из привязок
                        for ta in active_auths:
                            if ta.student_id == selected_student_id:
                                selected_student = ta.student
                                break

                    # Если selected_student_id не найден или невалиден - выбрать первого студента
                    # Это предотвращает неожиданный logout при устаревшей cookie
                    if not selected_student:
                        selected_student = active_auths[0].student

                if selected_student:
                    # Обновить last_auth_at для соответствующей привязки
                    for ta in active_auths:
                        if ta.student_id == selected_student.id:
                            ta.last_auth_at = datetime.utcnow()
                            db.commit()
                            break

                    request.state.auth = AuthContext()
                    request.state.auth.student = selected_student
                    request.state.auth.auth_method = 'telegram'
                    request.state.auth.auth_identifier = telegram_id
                    request.state.auth.telegram_id = telegram_id

                    return selected_student

                # Несколько студентов и нет выбора - пользователь должен выбрать
                return None

    # 3. Если НЕТ initData - проверяем telegram session cookies (для GET запросов после TG входа)
    cookie_telegram_id, cookie_student_id = get_telegram_session(request)
    if cookie_telegram_id and cookie_student_id:
        # Проверить что привязка существует и активна
        telegram_auth = db.query(TelegramAuth).filter(
            TelegramAuth.telegram_id == cookie_telegram_id,
            TelegramAuth.student_id == cookie_student_id,
            TelegramAuth.is_active == True
        ).first()

        if telegram_auth and telegram_auth.student.is_active:
            telegram_auth.last_auth_at = datetime.utcnow()
            db.commit()

            request.state.auth = AuthContext()
            request.state.auth.student = telegram_auth.student
            request.state.auth.auth_method = 'telegram'
            request.state.auth.auth_identifier = cookie_telegram_id
            request.state.auth.telegram_id = cookie_telegram_id

            return telegram_auth.student

        # Если привязка не найдена (отвязали) - НЕ fallback на токен, вернуть None
        # Это гарантирует что после отвязки доступ пропадёт
        return None

    # 4. Если НЕТ telegram session - пробуем UUID token из cookie
    cookie_token = request.cookies.get('access_token')
    if cookie_token:
        student = TokenAuthValidator.validate_token(db, cookie_token)
        if student:
            request.state.auth = AuthContext()
            request.state.auth.student = student
            request.state.auth.auth_method = 'token'
            request.state.auth.auth_identifier = cookie_token

            return student

    return None


async def require_student(
        student: Optional[Student] = Depends(get_current_student)
) -> Student:
    """
    Dependency для роутов, требующих аутентификации

    Raises:
        HTTPException: 401 если не авторизован

    Returns:
        Student
    """
    if not student:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    return student
