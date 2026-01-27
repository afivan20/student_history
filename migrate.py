"""
Скрипт миграции данных из students.json в SQLite
"""
import json
import sys
import os
from database import SessionLocal, init_db
from models import Student, AccessToken, AdminUser
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def migrate_students():
    """Перенести students.json в SQLite"""

    # Проверить существование файла
    if not os.path.exists('students.json'):
        print("❌ Файл students.json не найден")
        print("   Создайте файл students.json с данными студентов:")
        print('   {"ivan": "Иван Иванов", "maria": "Мария Петрова"}')
        return

    # Инициализировать БД
    init_db()

    db = SessionLocal()

    try:
        # Загрузить students.json
        with open('students.json', 'r', encoding='utf-8') as f:
            students_data = json.load(f)

        print(f"📚 Найдено {len(students_data)} студентов в students.json")
        print()

        migrated = 0
        skipped = 0

        for slug, full_name in students_data.items():
            # Проверить существует ли уже
            existing = db.query(Student).filter(Student.slug == slug.lower()).first()
            if existing:
                print(f"⏭️  Студент {slug} уже существует, пропускаем")
                skipped += 1
                continue

            # Создать студента
            student = Student(
                slug=slug.lower(),
                full_name=full_name,
                google_sheet_name=slug.capitalize()  # Ivan -> Ivan (имя листа)
            )
            db.add(student)
            db.flush()  # Получить ID

            # Автоматически создать UUID токен
            token = AccessToken(
                student_id=student.id,
                token=AccessToken.generate_token(),
                created_by='auto_migration',
                note='Автоматически создан при миграции'
            )
            db.add(token)

            print(f"✅ Создан студент: {full_name} (slug: {slug})")
            print(f"   UUID токен: {token.token}")
            print(f"   Ссылка: /t/{token.token}")
            print()

            migrated += 1

        db.commit()
        print(f"\n🎉 Миграция завершена!")
        print(f"   Создано: {migrated} студентов")
        print(f"   Пропущено: {skipped} студентов")
        print()
        print("📝 Следующий шаг: Создайте админа")
        print(f"   python {sys.argv[0]} admin <username> <password>")

    except Exception as e:
        print(f"❌ Ошибка миграции: {e}")
        db.rollback()
    finally:
        db.close()


def create_admin_user(username: str, password: str):
    """Создать администратора"""

    # Инициализировать БД
    init_db()

    db = SessionLocal()
    try:
        # Проверить существует ли
        existing = db.query(AdminUser).filter(AdminUser.username == username).first()
        if existing:
            print(f"⚠️  Админ '{username}' уже существует")

            # Спросить хотим ли обновить пароль
            response = input("   Обновить пароль? (y/n): ")
            if response.lower() == 'y':
                existing.password_hash = pwd_context.hash(password)
                db.commit()
                print(f"✅ Пароль для админа '{username}' обновлен")
            else:
                print("   Пароль не изменен")
            return

        admin = AdminUser(
            username=username,
            password_hash=pwd_context.hash(password)
        )
        db.add(admin)
        db.commit()

        print(f"✅ Создан админ: {username}")
        print()
        print("🔐 Теперь можете войти в админ-панель:")
        print(f"   /admin/login")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        db.rollback()
    finally:
        db.close()


def add_expires_at_column():
    """Добавить колонку expires_at в таблицу access_tokens"""
    from sqlalchemy import text
    from database import engine

    with engine.connect() as conn:
        # Проверить, есть ли уже колонка
        result = conn.execute(text("PRAGMA table_info(access_tokens)"))
        columns = [row[1] for row in result.fetchall()]

        if 'expires_at' in columns:
            print("✅ Колонка expires_at уже существует")
            return

        # Добавить колонку
        conn.execute(text("ALTER TABLE access_tokens ADD COLUMN expires_at DATETIME"))
        conn.commit()
        print("✅ Колонка expires_at добавлена в таблицу access_tokens")


def add_chat_id_columns():
    """Добавить колонку chat_id в telegram_auth и pending_telegram_links"""
    from sqlalchemy import text
    from database import engine

    with engine.connect() as conn:
        # TelegramAuth
        result = conn.execute(text("PRAGMA table_info(telegram_auth)"))
        columns = [row[1] for row in result.fetchall()]

        if 'chat_id' not in columns:
            conn.execute(text("ALTER TABLE telegram_auth ADD COLUMN chat_id VARCHAR(50)"))
            print("✅ Колонка chat_id добавлена в telegram_auth")
        else:
            print("✅ Колонка chat_id уже существует в telegram_auth")

        # PendingTelegramLink
        result = conn.execute(text("PRAGMA table_info(pending_telegram_links)"))
        columns = [row[1] for row in result.fetchall()]

        if 'chat_id' not in columns:
            conn.execute(text("ALTER TABLE pending_telegram_links ADD COLUMN chat_id VARCHAR(50)"))
            print("✅ Колонка chat_id добавлена в pending_telegram_links")
        else:
            print("✅ Колонка chat_id уже существует в pending_telegram_links")

        conn.commit()


def create_sent_messages_table():
    """Создать таблицу sent_messages"""
    from models import Base, SentMessage
    from database import engine

    SentMessage.__table__.create(engine, checkfirst=True)
    print("✅ Таблица sent_messages создана или уже существует")


def show_usage():
    """Показать справку по использованию"""
    print("Скрипт миграции данных Student History")
    print()
    print("Использование:")
    print(f"  python {sys.argv[0]} students              - Мигрировать студентов из students.json")
    print(f"  python {sys.argv[0]} admin <user> <pass>   - Создать администратора")
    print(f"  python {sys.argv[0]} upgrade               - Обновить схему БД (добавить новые колонки)")
    print(f"  python {sys.argv[0]} add_chat_id           - Добавить колонку chat_id для отправки сообщений")
    print(f"  python {sys.argv[0]} create_messages       - Создать таблицу истории сообщений")
    print()
    print("Примеры:")
    print(f"  python {sys.argv[0]} students")
    print(f"  python {sys.argv[0]} admin admin password123")
    print(f"  python {sys.argv[0]} upgrade")
    print(f"  python {sys.argv[0]} add_chat_id")
    print(f"  python {sys.argv[0]} create_messages")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        show_usage()
        sys.exit(1)

    command = sys.argv[1]

    if command == 'students':
        migrate_students()
    elif command == 'admin' and len(sys.argv) == 4:
        create_admin_user(sys.argv[2], sys.argv[3])
    elif command == 'upgrade':
        add_expires_at_column()
    elif command == 'add_chat_id':
        add_chat_id_columns()
    elif command == 'create_messages':
        create_sent_messages_table()
    else:
        print("❌ Неверная команда\n")
        show_usage()
        sys.exit(1)
