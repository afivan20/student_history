"""
UUID Token Authentication Validator
Проверка секретных UUID токенов для доступа
"""
from sqlalchemy.orm import Session
from models import AccessToken, Student
from typing import Optional
from datetime import datetime


class TokenAuthValidator:
    """Валидация UUID токенов"""

    @staticmethod
    def validate_token(db: Session, token: str) -> Optional[Student]:
        """
        Проверить UUID токен и вернуть студента

        Args:
            db: database session
            token: UUID токен

        Returns:
            Student объект или None
        """
        try:
            # Найти активный токен
            access_token = db.query(AccessToken).filter(
                AccessToken.token == token,
                AccessToken.is_active == True
            ).first()

            if not access_token:
                return None

            # Проверить срок действия токена
            if access_token.is_expired():
                return None

            # Проверить что студент активен
            student = db.query(Student).filter(
                Student.id == access_token.student_id,
                Student.is_active == True
            ).first()

            if not student:
                return None

            # Обновить last_used_at
            access_token.last_used_at = datetime.utcnow()
            db.commit()

            return student

        except Exception as e:
            print(f"Token validation error: {e}")
            db.rollback()
            return None
