"""Shared rate limiters for external API calls.

Usage:
    from app.ingest.rate_limit import NVD_LIMITER, OPENAI_LIMITER

    await NVD_LIMITER.acquire()
    resp = await client.get(...)
"""
import asyncio
import logging

from domains.cyber.app.settings import settings

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

# NVD API: 5 req/30s without key (10 RPM), 50 req/30s with key (100 RPM)
_nvd_rpm = 100 if settings.NVD_API_KEY else 10
NVD_LIMITER = RateLimiter(rpm=_nvd_rpm)
