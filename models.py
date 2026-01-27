"""
SQLAlchemy модели для системы аутентификации студентов
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Index, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

Base = declarative_base()


class Student(Base):
    """Основная таблица студентов"""
    __tablename__ = 'students'

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(50), unique=True, nullable=False, index=True)  # ivan, maria
    full_name = Column(String(255), nullable=False)  # Иван Иванов
    google_sheet_name = Column(String(100), nullable=False)  # Ivan (имя листа в Google Sheets)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Отношения
    telegram_ids = relationship("TelegramAuth", back_populates="student", cascade="all, delete-orphan")
    access_tokens = relationship("AccessToken", back_populates="student", cascade="all, delete-orphan")
    access_logs = relationship("AccessLog", back_populates="student", cascade="all, delete-orphan")

    # Индексы для производительности
    __table_args__ = (
        Index('idx_student_slug_active', 'slug', 'is_active'),
    )

    def __repr__(self):
        return f"<Student(id={self.id}, slug='{self.slug}', full_name='{self.full_name}')>"


class TelegramAuth(Base):
    """Привязки Telegram ID к студентам (many-to-many через несколько записей)

    Один telegram_id может быть привязан к нескольким студентам (например, родитель с двумя детьми).
    Уникальность обеспечивается парой (telegram_id, student_id).
    """
    __tablename__ = 'telegram_auth'

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey('students.id', ondelete='CASCADE'), nullable=False)
    telegram_id = Column(String(50), nullable=False, index=True)  # Telegram user ID (не unique!)
    telegram_username = Column(String(100), nullable=True)  # @username (может меняться)
    telegram_first_name = Column(String(255), nullable=True)
    telegram_last_name = Column(String(255), nullable=True)
   
    linked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_auth_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Отношения
    student = relationship("Student", back_populates="telegram_ids")

    # Индексы и ограничения
    __table_args__ = (
        Index('idx_telegram_id_active', 'telegram_id', 'is_active'),
        UniqueConstraint('telegram_id', 'student_id', name='uq_telegram_student'),
    )

    def __repr__(self):
        return f"<TelegramAuth(id={self.id}, telegram_id='{self.telegram_id}', student_id={self.student_id})>"


class PendingTelegramLink(Base):
    """Ожидающие привязки Telegram аккаунты"""
    __tablename__ = 'pending_telegram_links'

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(String(50), unique=True, nullable=False, index=True)
    telegram_username = Column(String(100), nullable=True)
    telegram_first_name = Column(String(255), nullable=True)
    telegram_last_name = Column(String(255), nullable=True)

    first_attempt_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_attempt_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    attempt_count = Column(Integer, default=1, nullable=False)
    ip_address = Column(String(45), nullable=True)
   

    def __repr__(self):
        return f"<PendingTelegramLink(id={self.id}, telegram_id='{self.telegram_id}')>"


class SentMessage(Base):
    """История отправленных сообщений через Telegram бота"""
    __tablename__ = 'sent_messages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_auth_id = Column(Integer, ForeignKey('telegram_auth.id', ondelete='SET NULL'), nullable=True)
    telegram_id = Column(String(50), nullable=False)  # Telegram user ID

    message_text = Column(String(4096), nullable=False)  # Текст сообщения (Telegram limit: 4096)

    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    sent_by = Column(String(50), nullable=True)  # Какой админ отправил

    # Статус доставки
    delivery_status = Column(String(20), default='pending', nullable=False)  # pending, sent, failed
    error_message = Column(String(500), nullable=True)  # Ошибка если failed

    # Отношения
    telegram_auth = relationship("TelegramAuth", backref="sent_messages")

    __table_args__ = (
        Index('idx_sent_messages_date', 'sent_at'),
    )

    def __repr__(self):
        return f"<SentMessage(id={self.id}, telegram_id='{self.telegram_id}', status='{self.delivery_status}')>"


class AccessToken(Base):
    """UUID токены для доступа через секретные ссылки"""
    __tablename__ = 'access_tokens'

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey('students.id', ondelete='CASCADE'), nullable=False)
    token = Column(String(36), unique=True, nullable=False, index=True)  # UUID4

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)  # Срок действия токена (None = бессрочный)
    last_used_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Метаданные
    created_by = Column(String(50), nullable=True)  # 'admin', 'auto_migration', 'telegram_auth'
    note = Column(String(255), nullable=True)  # Описание для чего создан токен

    # Отношения
    student = relationship("Student", back_populates="access_tokens")

    # Индексы
    __table_args__ = (
        Index('idx_token_active', 'token', 'is_active'),
    )

    # Срок действия по умолчанию (24 часа)
    DEFAULT_TTL_HOURS = 24

    @staticmethod
    def generate_token():
        """Генерировать новый UUID4 токен"""
        return str(uuid.uuid4())

    def is_expired(self) -> bool:
        """Проверить, истёк ли токен"""
        if self.expires_at is None:
            return False  # Бессрочный токен
        return datetime.utcnow() > self.expires_at

    def __repr__(self):
        return f"<AccessToken(id={self.id}, token='{self.token[:8]}...', student_id={self.student_id})>"


class AccessLog(Base):
    """Логирование попыток доступа для статистики"""
    __tablename__ = 'access_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey('students.id', ondelete='SET NULL'), nullable=True)

    auth_method = Column(String(20), nullable=False)  # 'telegram', 'token', 'failed'
    auth_identifier = Column(String(100), nullable=True)  # telegram_id или token

    ip_address = Column(String(45), nullable=True)  # IPv4/IPv6
    user_agent = Column(String(500), nullable=True)

    success = Column(Boolean, nullable=False)
    error_message = Column(String(255), nullable=True)

    accessed_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Отношения
    student = relationship("Student", back_populates="access_logs")

    # Индексы для аналитики
    __table_args__ = (
        Index('idx_access_student_date', 'student_id', 'accessed_at'),
        Index('idx_access_method_date', 'auth_method', 'accessed_at'),
    )

    def __repr__(self):
        return f"<AccessLog(id={self.id}, student_id={self.student_id}, method='{self.auth_method}', success={self.success})>"


class AdminUser(Base):
    """Таблица администраторов"""
    __tablename__ = 'admin_users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)  # bcrypt hash
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<AdminUser(id={self.id}, username='{self.username}')>"
