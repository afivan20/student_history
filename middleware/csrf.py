"""
Simple CSRF Protection
Requires custom header for non-Telegram requests
"""
from fastapi import Request, HTTPException


async def require_csrf(request: Request):
    """
    CSRF protection dependency.

    Validates that request has either:
    - X-Telegram-Init-Data header (Telegram Web App - protected by HMAC)
    - X-Requested-With: XMLHttpRequest header (AJAX request)

    Browsers don't auto-send custom headers, so this prevents CSRF.
    """
    # Telegram requests are protected by initData signature
    if request.headers.get('X-Telegram-Init-Data'):
        return

    # Non-Telegram requests must have X-Requested-With header
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return

    raise HTTPException(status_code=403, detail="CSRF validation failed")
