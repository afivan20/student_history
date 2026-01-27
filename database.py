"""
Database connection and session management
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import os
from dotenv import load_dotenv

# Загрузить переменные окружения
load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./student_history.db')

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=False  # Set to True for SQL debugging
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Создать все таблицы в базе данных"""
    from models import Base
    Base.metadata.create_all(bind=engine)
    print("✅ База данных инициализирована")


@contextmanager
def get_db() -> Session:
    """
    Context manager для работы с БД

    Usage:
        with get_db() as db:
            db.query(Student).all()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_session():
    """
    FastAPI dependency для получения DB session

    Usage:
        @app.get("/route")
        async def route(db: Session = Depends(get_db_session)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
