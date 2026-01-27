"""
Admin Middleware
Проверка JWT токена для доступа к админ-панели
"""
from fastapi import Request, HTTPException, status, Depends, Response
from fastapi.responses import RedirectResponse
from typing import Optional
from admin.auth import verify_token


async def get_current_admin(request: Request) -> Optional[str]:
    """Получить текущего админа из cookie"""
    token = request.cookies.get("admin_token")
    if not token:
        return None

    payload = verify_token(token)
    if not payload:
        return None

    return payload.get("sub")  # username


async def require_admin(admin: Optional[str] = Depends(get_current_admin)):
    """Dependency для админ роутов"""
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            detail="Not authenticated",
            headers={"Location": "/admin/login"}
        )
    return admin
