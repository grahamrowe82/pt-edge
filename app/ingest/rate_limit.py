"""Shared rate limiters for external API calls.

OpenAI: 500 RPM — we use 400 for safety margin.

Note: Gemini rate limiting has moved to app/ingest/budget.py which
tracks RPM and daily budget via the database. OpenAI will follow in
a future PR.

Usage:

    resp = await client.post(...)
"""
import asyncio
import logging

from app.settings import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token-bucket rate limiter. Ensures minimum interval between calls."""

    def __init__(self, rpm: int):
        self.rpm = rpm
        self._interval = 60.0 / rpm
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def acquire(self):
        async with self._lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            wait = self._interval - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = asyncio.get_event_loop().time()


OPENAI_LIMITER = RateLimiter(rpm=settings.OPENAI_RPM)
