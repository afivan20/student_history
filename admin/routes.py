"""
Admin Panel Routes
Управление студентами, Telegram привязками, UUID токенами и просмотр логов
"""
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, timedelta
from typing import Optional

from database import get_db_session
from models import Student, TelegramAuth, AccessToken, AccessLog, AdminUser, PendingTelegramLink, SentMessage
from admin.middleware import require_admin, get_current_admin
from admin.auth import verify_password, create_access_token
from services.google_sheets import get_sheets_manager
from services.send_message import send_telegram_message, get_message_history

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates/admin")


# ========== AUTH ==========

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Страница входа в админ-панель"""
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        db: Session = Depends(get_db_session)
):
    """Обработка входа"""
    # Проверить credentials
    admin = db.query(AdminUser).filter(
        AdminUser.username == username,
        AdminUser.is_active == True
    ).first()

    if not admin or not verify_password(password, admin.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Неверный логин или пароль"}
        )

    # Создать JWT token
    access_token = create_access_token(data={"sub": username})

    # Обновить last_login_at
    admin.last_login_at = datetime.utcnow()
    db.commit()

    # Redirect с cookie
    response = RedirectResponse(url="/admin/dashboard", status_code=302)
    response.set_cookie(
        key="admin_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax"
    )
    return response


@router.get("/logout")
async def logout():
    """Выход из админ-панели"""
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie(key="admin_token")
    return response


# ========== DASHBOARD ==========

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
        request: Request,
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """Главная страница админки с статистикой"""
    # Статистика
    total_students = db.query(func.count(Student.id)).filter(Student.is_active == True).scalar()
    total_telegram = db.query(func.count(TelegramAuth.id)).filter(TelegramAuth.is_active == True).scalar()
    total_tokens = db.query(func.count(AccessToken.id)).filter(AccessToken.is_active == True).scalar()

    # Активность за последние 7 дней
    week_ago = datetime.utcnow() - timedelta(days=7)
    recent_access = db.query(AccessLog).filter(
        AccessLog.accessed_at >= week_ago,
        AccessLog.success == True
    ).count()

    # Последние логи
    recent_logs = db.query(AccessLog).order_by(desc(AccessLog.accessed_at)).limit(10).all()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "admin": admin,
            "stats": {
                "students": total_students,
                "telegram": total_telegram,
                "tokens": total_tokens,
                "recent_access": recent_access
            },
            "recent_logs": recent_logs
        }
    )


# ========== STUDENTS ==========

@router.get("/students", response_class=HTMLResponse)
async def students_list(
        request: Request,
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """Список всех студентов"""
    students = db.query(Student).filter(Student.is_active == True).all()
    return templates.TemplateResponse(
        "students.html",
        {"request": request, "admin": admin, "students": students}
    )


@router.post("/students")
async def create_student(
        slug: str = Form(...),
        full_name: str = Form(...),
        google_sheet_name: str = Form(...),
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """Создать нового студента"""
    try:
        student = Student(
            slug=slug.lower(),
            full_name=full_name,
            google_sheet_name=google_sheet_name
        )
        db.add(student)
        db.commit()
        return RedirectResponse(url="/admin/students", status_code=302)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ========== TELEGRAM ==========

@router.get("/telegram", response_class=HTMLResponse)
async def telegram_list(
        request: Request,
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """Список Telegram привязок и ожидающих привязки"""
    telegram_auths = db.query(TelegramAuth).filter(
        TelegramAuth.is_active == True
    ).all()

    pending_links = db.query(PendingTelegramLink).order_by(
        desc(PendingTelegramLink.last_attempt_at)
    ).all()

    students = db.query(Student).filter(Student.is_active == True).all()

    return templates.TemplateResponse(
        "telegram.html",
        {
            "request": request,
            "admin": admin,
            "telegram_auths": telegram_auths,
            "pending_links": pending_links,
            "students": students
        }
    )


@router.post("/telegram/link")
async def link_telegram(
        student_id: int = Form(...),
        telegram_id: str = Form(...),
        telegram_username: str = Form(None),
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """Привязать Telegram ID к студенту

    Один telegram_id может быть привязан к нескольким студентам
    (например, родитель с двумя детьми). Но нельзя привязать один
    telegram_id к одному студенту дважды.
    """
    # Проверить что студент существует
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Проверить что эта пара ещё не существует
    existing = db.query(TelegramAuth).filter(
        TelegramAuth.telegram_id == telegram_id,
        TelegramAuth.student_id == student_id
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="This Telegram ID is already linked to this student")

    try:
        # Создать привязку
        telegram_auth = TelegramAuth(
            student_id=student_id,
            telegram_id=telegram_id,
            telegram_username=telegram_username
        )
        db.add(telegram_auth)
        db.commit()
        return RedirectResponse(url="/admin/telegram", status_code=302)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/telegram/{auth_id}/unlink")
async def unlink_telegram(
        auth_id: int,
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """Отвязать Telegram ID (удалить запись полностью)"""
    telegram_auth = db.query(TelegramAuth).filter(TelegramAuth.id == auth_id).first()
    if telegram_auth:
        db.delete(telegram_auth)  # Удалить полностью вместо деактивации
        db.commit()
    return RedirectResponse(url="/admin/telegram", status_code=302)


@router.post("/telegram/pending/{pending_id}/approve")
async def approve_pending_link(
        pending_id: int,
        student_id: int = Form(...),
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """Одобрить pending link - создать TelegramAuth и удалить pending

    Примечание: один telegram_id может быть привязан к нескольким студентам
    (например, родитель с двумя детьми). Проверяем только что эта конкретная
    пара (telegram_id, student_id) ещё не существует.
    """
    pending = db.query(PendingTelegramLink).filter(
        PendingTelegramLink.id == pending_id
    ).first()

    if not pending:
        raise HTTPException(status_code=404, detail="Pending link not found")

    student = db.query(Student).filter(
        Student.id == student_id,
        Student.is_active == True
    ).first()

    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Проверить что эта пара (telegram_id, student_id) ещё не существует
    existing = db.query(TelegramAuth).filter(
        TelegramAuth.telegram_id == pending.telegram_id,
        TelegramAuth.student_id == student_id
    ).first()

    if existing:
        db.delete(pending)
        db.commit()
        raise HTTPException(status_code=400, detail="This Telegram ID is already linked to this student")

    try:
        telegram_auth = TelegramAuth(
            student_id=student_id,
            telegram_id=pending.telegram_id,
            telegram_username=pending.telegram_username,
            telegram_first_name=pending.telegram_first_name,
            telegram_last_name=pending.telegram_last_name
        )
        db.add(telegram_auth)
        db.delete(pending)
        db.commit()
        return RedirectResponse(url="/admin/telegram", status_code=302)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/telegram/pending/{pending_id}/reject")
async def reject_pending_link(
        pending_id: int,
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """Отклонить pending link (удалить запись)"""
    pending = db.query(PendingTelegramLink).filter(
        PendingTelegramLink.id == pending_id
    ).first()

    if pending:
        db.delete(pending)
        db.commit()

    return RedirectResponse(url="/admin/telegram", status_code=302)


# ========== TOKENS ==========

@router.get("/tokens", response_class=HTMLResponse)
async def tokens_list(
        request: Request,
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """Список UUID токенов"""
    tokens = db.query(AccessToken).filter(
        AccessToken.is_active == True
    ).all()

    students = db.query(Student).filter(Student.is_active == True).all()

    return templates.TemplateResponse(
        "tokens.html",
        {
            "request": request,
            "admin": admin,
            "tokens": tokens,
            "students": students
        }
    )


@router.post("/tokens/generate")
async def generate_token(
        student_id: int = Form(...),
        note: str = Form(None),
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """Сгенерировать новый UUID токен"""
    token = AccessToken(
        student_id=student_id,
        token=AccessToken.generate_token(),
        created_by='admin',
        note=note
    )
    db.add(token)
    db.commit()
    return RedirectResponse(url="/admin/tokens", status_code=302)


@router.post("/tokens/{token_id}/revoke")
async def revoke_token(
        token_id: int,
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """Отозвать UUID токен"""
    token = db.query(AccessToken).filter(AccessToken.id == token_id).first()
    if token:
        token.is_active = False
        db.commit()
    return RedirectResponse(url="/admin/tokens", status_code=302)


# ========== LOGS ==========

@router.get("/logs", response_class=HTMLResponse)
async def logs_list(
        request: Request,
        student_id: int = None,
        days: int = 7,
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """Просмотр логов доступа"""
    # Фильтры
    query = db.query(AccessLog)

    if student_id:
        query = query.filter(AccessLog.student_id == student_id)

    cutoff_date = datetime.utcnow() - timedelta(days=days)
    query = query.filter(AccessLog.accessed_at >= cutoff_date)

    logs = query.order_by(desc(AccessLog.accessed_at)).limit(100).all()

    students = db.query(Student).filter(Student.is_active == True).all()

    return templates.TemplateResponse(
        "logs.html",
        {
            "request": request,
            "admin": admin,
            "logs": logs,
            "students": students,
            "selected_student_id": student_id,
            "selected_days": days
        }
    )


# ========== CACHE MANAGEMENT ==========

@router.post("/cache/clear")
async def clear_sheets_cache(
    student: Optional[str] = None,
    current_admin: AdminUser = Depends(require_admin)
):
    """Clear Google Sheets cache (all or specific student)"""
    manager = get_sheets_manager()

    if student:
        cache_key = f"student_history:{student.capitalize()}"
        manager.clear_cache(cache_key)
        return {"message": f"Cache cleared for student: {student}", "success": True}
    else:
        manager.clear_cache()
        return {"message": "Entire cache cleared", "success": True}


@router.get("/cache/stats")
async def get_cache_stats(current_admin: AdminUser = Depends(require_admin)):
    """Get cache statistics"""
    manager = get_sheets_manager()
    stats = manager.get_cache_stats()
    return stats


@router.get("/cache", response_class=HTMLResponse)
async def cache_page(
        request: Request,
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """Страница управления кэшем"""
    manager = get_sheets_manager()
    cache_stats = manager.get_cache_stats()
    students = db.query(Student).filter(Student.is_active == True).all()
    return templates.TemplateResponse(
        "cache.html",
        {"request": request, "admin": admin, "cache_stats": cache_stats, "students": students}
    )


# ========== MESSAGES ==========

@router.get("/messages", response_class=HTMLResponse)
async def messages_page(
        request: Request,
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """Страница отправки сообщений"""
    telegram_auths = db.query(TelegramAuth).filter(
        TelegramAuth.is_active == True
    ).all()

    recipients = []
    for auth in telegram_auths:
        recipients.append({
            "id": auth.id,
            "telegram_id": auth.telegram_id,
            "telegram_username": auth.telegram_username or "-",
            "student_slug": auth.student.slug,
            "student_full_name": auth.student.full_name
        })

    return templates.TemplateResponse(
        "send_message.html",
        {
            "request": request,
            "admin": admin,
            "recipients": recipients
        }
    )


@router.post("/messages/send")
async def send_message_route(
        request: Request,
        telegram_auth_id: int = Form(...),
        message_text: str = Form(...),
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):

    # Проверка AJAX запроса
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or \
              'application/json' in request.headers.get('Accept', '')



    result = await send_telegram_message(
        telegram_auth_id=telegram_auth_id,
        message_text=message_text,
        sent_by=admin,
        db=db
    )

    if is_ajax:
        return JSONResponse(content=result)

    # Для обычного POST - редирект на историю
    if result.get("success"):
        return RedirectResponse(url="/admin/messages/history", status_code=302)
    else:
        return RedirectResponse(url="/admin/messages?error=" + result.get("message", "Ошибка"), status_code=302)


@router.get("/messages/history", response_class=HTMLResponse)
async def messages_history(
        request: Request,
        telegram_auth_id: int = None,
        admin: str = Depends(require_admin),
        db: Session = Depends(get_db_session)
):
    """История отправленных сообщений"""
    messages = get_message_history(db, limit=100, telegram_auth_id=telegram_auth_id)

    telegram_auths = db.query(TelegramAuth).filter(
        TelegramAuth.is_active == True
    ).all()

    return templates.TemplateResponse(
        "message_history.html",
        {
            "request": request,
            "admin": admin,
            "messages": messages,
            "telegram_auths": telegram_auths,
            "selected_auth_id": telegram_auth_id
        }
    )
