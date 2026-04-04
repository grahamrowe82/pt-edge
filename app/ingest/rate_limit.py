"""Shared rate limiters for external API calls.

Anthropic Tier 1: 50 RPM — we use 40 for safety margin.
OpenAI: 500 RPM — we use 400 for safety margin.

Usage:
    from app.ingest.rate_limit import ANTHROPIC_LIMITER, OPENAI_LIMITER

    await ANTHROPIC_LIMITER.acquire()
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


ANTHROPIC_LIMITER = RateLimiter(rpm=settings.ANTHROPIC_RPM)
OPENAI_LIMITER = RateLimiter(rpm=settings.OPENAI_RPM)
GEMINI_LIMITER = RateLimiter(rpm=settings.GEMINI_RPM)
