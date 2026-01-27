"""
Simple in-memory Rate Limiter
Защита от brute-force атак
"""
from fastapi import Request, HTTPException
from collections import defaultdict
from datetime import datetime, timedelta
import asyncio


class RateLimiter:
    """Простой in-memory rate limiter"""

    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.requests = defaultdict(list)
        self.cleanup_interval = 60  # Очистка каждую минуту
        asyncio.create_task(self._cleanup_loop())

    async def check_rate_limit(self, request: Request):
        """Проверить rate limit для IP адреса"""
        ip = request.client.host
        now = datetime.utcnow()

        # Удалить старые запросы (старше 1 минуты)
        cutoff = now - timedelta(minutes=1)
        self.requests[ip] = [
            req_time for req_time in self.requests[ip]
            if req_time > cutoff
        ]

        # Проверить лимит
        if len(self.requests[ip]) >= self.requests_per_minute:
            raise HTTPException(
                status_code=429,
                detail="Too many requests"
            )

        # Добавить текущий запрос
        self.requests[ip].append(now)

    async def _cleanup_loop(self):
        """Периодическая очистка старых записей"""
        while True:
            await asyncio.sleep(self.cleanup_interval)
            now = datetime.utcnow()
            cutoff = now - timedelta(minutes=2)

            # Удалить IPs без активности
            for ip in list(self.requests.keys()):
                self.requests[ip] = [
                    req_time for req_time in self.requests[ip]
                    if req_time > cutoff
                ]
                if not self.requests[ip]:
                    del self.requests[ip]
