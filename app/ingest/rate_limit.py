"""Shared rate limiters for external API calls.

Note: Rate limiting for all providers has moved to app/ingest/budget.py
which tracks RPM and daily budget via the database (resource_budgets table).

The RateLimiter class is kept for any future in-process use cases.
"""
import asyncio
import logging

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
