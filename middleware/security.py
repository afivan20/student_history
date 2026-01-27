"""
Security Headers Middleware
Добавление заголовков безопасности
"""
from fastapi import Request


async def add_security_headers(request: Request, call_next):
    """Middleware для добавления security headers"""
    response = await call_next(request)

    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "no-referrer"  # Не передавать URL с токеном в Referer

    # CSP (Content Security Policy)
    # frame-ancestors разрешает встраивание в iframe для Telegram Web App
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://telegram.org https://cdn.jsdelivr.net 'unsafe-inline'; "
        "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "img-src 'self' data:; "
        "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org; "
    )

    return response
