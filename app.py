"""
Student History - Главное приложение
Система отслеживания уроков с аутентификацией через Telegram Web App и UUID токены
"""
import asyncio
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
from dateutil import parser as date_parser
import uvicorn
from subprocess import Popen
import os
from dotenv import load_dotenv

# Импорты модулей проекта
from database import get_db_session, init_db
from models import Student, AccessLog
from auth.middleware import get_current_student, require_student
from auth.token_auth import TokenAuthValidator
from auth.session import set_token_cookie
from student_api import student_history
from middleware.rate_limit import RateLimiter
from middleware.security import add_security_headers
from middleware.csrf import require_csrf
from admin.routes import router as admin_router
from services.google_sheets import get_sheets_manager
from telegram_bot import start_bot

# Загрузить переменные окружения
load_dotenv()

# Создать приложение
app = FastAPI(title="Student History", version="2.0")

# Static files и templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Подключить админ роутер
app.include_router(admin_router)

# Rate limiter
rate_limiter = RateLimiter(requests_per_minute=60)
login_rate_limiter = RateLimiter(requests_per_minute=5)  # Строгий лимит для логина

# Middleware
app.middleware("http")(add_security_headers)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting"""
    try:
        # Строгий лимит на логин (защита от брутфорса)
        if request.url.path == "/admin/login" and request.method == "POST":
            await login_rate_limiter.check_rate_limit(request)
        # Обычный лимит для остальных (кроме админки)
        elif not request.url.path.startswith('/admin'):
            await rate_limiter.check_rate_limit(request)
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"detail": e.detail}
        )

    response = await call_next(request)
    return response


# Инициализация БД при старте
@app.on_event("startup")
async def startup_event():
    init_db()

    # Initialize Google Sheets manager
    sheets_manager = get_sheets_manager()
    print("✅ Google Sheets connection manager initialized")

    # Запустить Telegram бота в фоновом режиме
    try:
        bot_app = await start_bot()
        if bot_app:
            # Сохранить ссылку на приложение бота для корректного завершения
            app.state.telegram_bot = bot_app
            print("✅ Telegram bot started successfully")
        else:
            print("⚠️ Telegram bot NOT started (check BOT_TOKEN in .env)")
    except Exception as e:
        print(f"❌ Failed to start Telegram bot: {e}")

    print("✅ Приложение запущено, база данных инициализирована")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown"""
    # Остановить Telegram бота
    if hasattr(app.state, 'telegram_bot') and app.state.telegram_bot:
        try:
            await app.state.telegram_bot.updater.stop()
            await app.state.telegram_bot.stop()
            await app.state.telegram_bot.shutdown()
            print("✅ Telegram bot stopped")
        except Exception as e:
            print(f"❌ Error stopping Telegram bot: {e}")
    
    # остановаить sheets manager (google страницы)
    sheets_manager = get_sheets_manager()
    sheets_manager.clear_cache()
    print("✅ Application shutdown complete")


# ============= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =============

def log_access(db: Session, student_id: int, auth_method: str,
               auth_identifier: str, request: Request,
               success: bool, error: str = None):
    """Логировать попытку доступа"""
    try:
        log = AccessLog(
            student_id=student_id,
            auth_method=auth_method,
            auth_identifier=auth_identifier,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get('user-agent'),
            success=success,
            error_message=error
        )
        db.add(log)
        db.commit()
    except Exception as e:
        print(f"Error logging access: {e}")
        db.rollback()


def format_russian_date(date_obj: datetime) -> str:
    """
    Форматировать дату на русском языке без использования locale

    Args:
        date_obj: datetime объект

    Returns:
        Строка вида "Пн 24-янв-2025"
    """
    weekdays = {
        0: 'Пн', 1: 'Вт', 2: 'Ср', 3: 'Чт',
        4: 'Пт', 5: 'Сб', 6: 'Вс'
    }
    months = {
        1: 'янв', 2: 'фев', 3: 'мар', 4: 'апр',
        5: 'май', 6: 'июн', 7: 'июл', 8: 'авг',
        9: 'сен', 10: 'окт', 11: 'ноя', 12: 'дек'
    }

    weekday = weekdays[date_obj.weekday()]
    day = date_obj.day
    month = months[date_obj.month]
    year = date_obj.year

    return f"{weekday} {day:02d}-{month}-{year}"


# ============= ПУБЛИЧНЫЕ РОУТЫ =============

@app.post("/auth/telegram")
async def telegram_auth(
        request: Request,
        db: Session = Depends(get_db_session),
        _csrf: None = Depends(require_csrf)
):
    """
    Аутентификация через Telegram Web App
    1. Валидировать initData из заголовка
    2. Найти всех студентов по Telegram ID
    3. Если 1 студент - вернуть redirect_url (БЕЗ токена)
    4. Если несколько - вернуть список для выбора

    ВАЖНО: НЕ создаем токен! Полагаемся на initData для аутентификации.
    """
    from auth.telegram_auth import TelegramAuthValidator
    from models import TelegramAuth, PendingTelegramLink

    telegram_init_data = request.headers.get('X-Telegram-Init-Data')
    
    if not telegram_init_data:
        return {"success": False, "error": "Missing Telegram init data"}

    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not bot_token or bot_token == 'YOUR_TELEGRAM_BOT_TOKEN_HERE':
        return {"success": False, "error": "Telegram bot not configured"}

    validator = TelegramAuthValidator(bot_token)
    user_data = validator.validate_init_data(telegram_init_data)

    if not user_data:
        log_access(db, None, 'telegram', 'invalid', request, success=False, error="Invalid init data")
        return {"success": False, "error": "Invalid Telegram authentication"}

    # Найти ВСЕ привязки по Telegram ID (может быть несколько студентов)
    telegram_auth_records = db.query(TelegramAuth).filter(
        TelegramAuth.telegram_id == user_data['telegram_id'],
        TelegramAuth.is_active == True
    ).all()

    # Отфильтровать только активных студентов
    active_records = [r for r in telegram_auth_records if r.student.is_active]

    if not active_records:
        # Сохранить pending link для последующей привязки админом
        try:
            pending = db.query(PendingTelegramLink).filter(
                PendingTelegramLink.telegram_id == user_data['telegram_id']
            ).first()

            if pending:
                pending.last_attempt_at = datetime.utcnow()
                pending.attempt_count += 1
                pending.telegram_username = user_data.get('username')
                pending.telegram_first_name = user_data.get('first_name')
                pending.telegram_last_name = user_data.get('last_name')
            else:
                pending = PendingTelegramLink(
                    telegram_id=user_data['telegram_id'],
                    telegram_username=user_data.get('username'),
                    telegram_first_name=user_data.get('first_name'),
                    telegram_last_name=user_data.get('last_name'),
                    ip_address=request.client.host if request.client else None
                )
                db.add(pending)
            db.commit()
        except Exception as e:
            db.rollback()

        log_access(db, None, 'telegram', user_data['telegram_id'], request, success=False, error="Telegram ID not linked")
        return {"success": False, "error": "Telegram account not linked to any student"}

    # Обновить метаданные Telegram для всех привязок
    for record in active_records:
        record.last_auth_at = datetime.utcnow()
        record.telegram_username = user_data.get('username')
        record.telegram_first_name = user_data.get('first_name')
        record.telegram_last_name = user_data.get('last_name')
    db.commit()

    # Если несколько студентов - вернуть список для выбора
    if len(active_records) > 1:
        students_list = [
            {"slug": r.student.slug, "name": r.student.full_name, "id": r.student.id}
            for r in active_records
        ]
        return {
            "success": True,
            "multiple_students": True,
            "students": students_list,
            "telegram_id": user_data['telegram_id']
        }

    # Один студент - вернуть redirect_url (БЕЗ токена!)
    student = active_records[0].student

    # Логировать успешный доступ
    log_access(db, student.id, 'telegram', user_data['telegram_id'], request, success=True)

    # Создать response с cookies (нужно для GET запросов, когда initData нет в заголовке)
    from auth.session import set_telegram_session

    response = JSONResponse(content={
        "success": True,
        "redirect_url": "/student",
        "student_id": student.id,
        "telegram_id": user_data['telegram_id']
    })

    # Установить telegram session cookie (для авторизации при GET запросах)
    set_telegram_session(response, user_data['telegram_id'], student.id)

    return response


@app.post("/auth/select-student")
async def select_student(
        request: Request,
        db: Session = Depends(get_db_session),
        _csrf: None = Depends(require_csrf)
):
    """
    Выбор конкретного студента при наличии нескольких привязок.
    Вызывается после /auth/telegram когда multiple_students=True,
    или при переключении между студентами на странице /student.

    Сохраняет выбор в cookie selected_student_id.
    НЕ создает токен - аутентификация через initData.

    Принимает JSON: {"student_slug": "...", "telegram_id": "..."}
    или X-Telegram-Init-Data в заголовке + student_slug в body
    """
    from auth.telegram_auth import TelegramAuthValidator
    from models import TelegramAuth
    from auth.session import set_telegram_session

    # Получить данные из body
    try:
        body = await request.json()
        student_slug = body.get('student_slug')
    except:
        return JSONResponse(
            content={"success": False, "error": "Invalid request body"},
            status_code=400
        )

    if not student_slug:
        return JSONResponse(
            content={"success": False, "error": "Missing student_slug"},
            status_code=400
        )

    # Получить telegram_id из initData (приоритет) или body
    telegram_id = None

    telegram_init_data = request.headers.get('X-Telegram-Init-Data')
    if telegram_init_data:
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        if bot_token and bot_token != 'YOUR_TELEGRAM_BOT_TOKEN_HERE':
            validator = TelegramAuthValidator(bot_token)
            user_data = validator.validate_init_data(telegram_init_data)
            if user_data:
                telegram_id = user_data['telegram_id']

    if not telegram_id:
        telegram_id = body.get('telegram_id')

    # Fallback на telegram_id из cookie (для Desktop Telegram где initData пустой)
    if not telegram_id:
        telegram_id = request.cookies.get('telegram_id')

    if not telegram_id:
        return JSONResponse(
            content={"success": False, "error": "Unable to determine Telegram ID. Please re-authenticate."},
            status_code=401
        )

    # Найти привязку для конкретного студента
    telegram_auth_record = db.query(TelegramAuth).join(Student).filter(
        TelegramAuth.telegram_id == str(telegram_id),
        TelegramAuth.is_active == True,
        Student.slug == student_slug,
        Student.is_active == True
    ).first()

    if not telegram_auth_record:
        log_access(db, None, 'telegram', telegram_id, request, success=False, error="Invalid student selection")
        return JSONResponse(
            content={"success": False, "error": "Student not linked to this Telegram account"},
            status_code=403
        )

    student = telegram_auth_record.student

    # Обновить last_auth_at
    telegram_auth_record.last_auth_at = datetime.utcnow()
    db.commit()

    # Логировать успешный доступ
    log_access(db, student.id, 'telegram', telegram_id, request, success=True)

    # Создать response с cookies
    response = JSONResponse(content={
        "success": True,
        "redirect_url": "/student",
        "student_id": student.id
    })

    # Сохранить telegram_id и выбранного студента в cookies
    set_telegram_session(response, telegram_id, student.id)

    return response


@app.post("/auth/logout")
async def logout(request: Request, _csrf: None = Depends(require_csrf)):
    """
    Выход из системы - очистить все cookies.
    Используется для явного выхода или при смене аккаунта.
    """
    from auth.session import clear_telegram_session, clear_token_cookie

    response = JSONResponse(content={"success": True, "redirect_url": "/"})
    clear_telegram_session(response)
    clear_token_cookie(response)
    return response


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, student: Student = Depends(get_current_student)):
    """
    Landing page
    - Если авторизован через Telegram Web App или токен → редирект на /student
    - Если нет → показать форму для ввода UUID токена
    """
    if student:
        return RedirectResponse(url="/student", status_code=302)

    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )


@app.get("/t/{token}")
async def token_access(
        token: str,
        request: Request,
        db: Session = Depends(get_db_session)
):
    """
    Доступ через UUID токен
    1. Валидировать токен
    2. Установить cookie
    3. Логировать доступ
    4. Редирект на /student
    """
    student = TokenAuthValidator.validate_token(db, token)

    if not student:
        log_access(db, None, 'token', token, request, success=False, error="Invalid token")
        return PlainTextResponse("Неверный или истекший токен", status_code=401)

    # Логировать успешный доступ
    log_access(db, student.id, 'token', token, request, success=True)

    # Редирект с токеном в URL (для iframe где cookies блокируются)
    # + установить cookie (для случаев где cookies работают)
    response = RedirectResponse(url=f"/student?token={token}", status_code=302)
    set_token_cookie(response, token)

    return response


# ============= АУТЕНТИФИЦИРОВАННЫЕ РОУТЫ =============

@app.get("/student", response_class=HTMLResponse)
async def student_page(
        request: Request,
        query: int = 5,
        student: Student = Depends(require_student),
        db: Session = Depends(get_db_session)
):
    """
    Главная страница студента - показывает историю уроков
    Требует аутентификацию (Telegram или UUID token)
    """
    from models import TelegramAuth, AccessToken

    try:
        # Получить данные из Google Sheets
        googlesheet_data = student_history(student.google_sheet_name)

        # Баланс загружается асинхронно через JavaScript (/api/student/balance)
        # чтобы избежать падения при ошибках формул (#NAME?, #VALUE!)
        message = "Загрузка..."

        n = query
        history = []

        for lesson in googlesheet_data[0]:
            if not query:
                break
            if not lesson or len(lesson) < 2:
                continue

            # Пометить тип урока
            if 'Оплата' not in lesson[1]:
                lesson[1] = 'Урок завершен'

            # Парсинг даты
            lesson_date = datetime.strptime(lesson[0], '%d-%b-%y')
            history.append((lesson_date, lesson[1]))
            query -= 1

        # Форматирование дат на русском
        history = list(map(
            lambda x: f"{format_russian_date(x[0])} {x[1]}",
            history
        ))

        # Логировать успешный доступ
        if hasattr(request.state, 'auth'):
            log_access(
                db,
                student.id,
                request.state.auth.auth_method,
                request.state.auth.auth_identifier,
                request,
                success=True
            )

        # Получить токен из URL для передачи в ссылки
        current_token = request.query_params.get('token', '')

        # Найти связанных студентов (для переключателя)
        # Переключатель показываем ТОЛЬКО при входе через Telegram
        # При входе по токену - показываем только одного студента (токен = конкретный студент)
        linked_students = []

        if hasattr(request.state, 'auth') and request.state.auth.auth_method == 'telegram':
            telegram_id = request.state.auth.telegram_id
            if telegram_id:
                telegram_links = db.query(TelegramAuth).filter(
                    TelegramAuth.telegram_id == telegram_id,
                    TelegramAuth.is_active == True
                ).all()
                linked_students = [
                    {"slug": link.student.slug, "name": link.student.full_name}
                    for link in telegram_links
                    if link.student.is_active
                ]

        return templates.TemplateResponse(
            "student.html",
            context={
                "request": request,
                "history": history,
                "name": student.full_name,
                "student_id": student.slug,
                "query": n,
                "is_more": not query,
                "message": message,
                "token": current_token,
                "linked_students": linked_students if len(linked_students) > 1 else [],
            }
        )

    except Exception as e:
        # Вывести полный traceback для отладки
        import traceback
        print("=" * 80)
        print(f"ОШИБКА при обработке /student для студента: {student.full_name}")
        print(f"Тип ошибки: {type(e).__name__}")
        print(f"Сообщение: {str(e)}")
        print("-" * 80)
        traceback.print_exc()
        print("=" * 80)

        # Логировать ошибку
        if hasattr(request.state, 'auth'):
            log_access(
                db,
                student.id,
                request.state.auth.auth_method,
                request.state.auth.auth_identifier,
                request,
                success=False,
                error=str(e)
            )

        return PlainTextResponse(
            f"Ошибка получения данных: {str(e)}",
            status_code=500
        )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "version": "2.0"}


@app.get("/api/student/balance")
async def get_student_balance(
    student: Student = Depends(require_student)
):
    """
    API для получения баланса уроков.
    Возвращает JSON с числом или статусом загрузки.
    Используется для динамической загрузки баланса на странице студента.
    """
    try:
        googlesheet_data = student_history(student.google_sheet_name, use_cache=False)
        value = googlesheet_data[1][0][0]

        # Проверка на ошибки Google Sheets формул (#NAME?, #VALUE!, etc.)
        if isinstance(value, str) and value.startswith('#'):
            return {"status": "loading", "raw_value": value}

        number = int(value)
        return {"status": "ok", "balance": number}

    except (ValueError, TypeError):
        # Значение не является числом
        return {"status": "loading", "raw_value": str(googlesheet_data[1][0][0]) if googlesheet_data else "unknown"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============= ЗАПУСК ПРИЛОЖЕНИЯ =============

if __name__ == '__main__':
    # Запустить HTTPS redirect в фоне
    Popen(['python', '-m', 'https_redirect'])

    # Получить SSL пути из .env
    ssl_keyfile = os.getenv('SSL_KEYFILE', '/etc/letsencrypt/live/domen.com/privkey.pem')
    ssl_certfile = os.getenv('SSL_CERTFILE', '/etc/letsencrypt/live/domen.com/fullchain.pem')

    uvicorn.run(
        'app:app',
        port=443,
        host='0.0.0.0',
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile
    )
