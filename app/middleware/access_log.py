import asyncio
import logging
import time
import threading

from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.db import SessionLocal

logger = logging.getLogger(__name__)

# Paths already logged elsewhere or not useful
_SKIP_PREFIXES = ("/api/", "/mcp/", "/healthz")

# Static asset extensions — never log these
_SKIP_EXTENSIONS = (
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".xml", ".txt", ".woff", ".woff2", ".ttf", ".eot", ".map", ".json",
)

# Buffer settings: flush when buffer hits this size OR this many seconds elapse
_BUFFER_SIZE = 100
_FLUSH_INTERVAL = 5.0  # seconds

# In-memory buffer + lock for thread safety
_buffer: list[dict] = []
_buffer_lock = threading.Lock()
_flush_task_started = False


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Log HTTP requests to static directory pages (HTML only).

    Buffers log entries in memory and flushes to the database in batches
    (every 100 rows or 5 seconds, whichever comes first). This reduces
    DB transactions by ~99% compared to per-request writes.
    """

    async def dispatch(self, request, call_next):
        path = request.url.path

        # Fast-skip: paths handled elsewhere or static assets
        if any(path.startswith(p) for p in _SKIP_PREFIXES) or any(
            path.endswith(ext) for ext in _SKIP_EXTENSIONS
        ):
            return await call_next(request)

        start = time.time()
        response = await call_next(request)
        duration_ms = int((time.time() - start) * 1000)

        # Only log HTML responses (the static directory site)
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            raw_ip = request.client.host if request.client else None
            client_ip = (
                request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or raw_ip
            )
            _buffer_access(
                path=path[:200],
                method=request.method,
                status_code=response.status_code,
                user_agent=(request.headers.get("User-Agent", "") or "")[:300],
                client_ip=client_ip,
                duration_ms=duration_ms,
            )

        # Start the periodic flush task on first request
        global _flush_task_started
        if not _flush_task_started:
            _flush_task_started = True
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(_periodic_flush())
            except RuntimeError:
                pass  # no event loop — flush will happen on buffer-full only

        return response


def _buffer_access(path, method, status_code, user_agent, client_ip, duration_ms):
    """Add a log entry to the in-memory buffer. Flushes when full."""
    entry = {
        "path": path,
        "method": method,
        "sc": status_code,
        "ua": user_agent,
        "ip": client_ip,
        "dur": duration_ms,
    }
    with _buffer_lock:
        _buffer.append(entry)
    # Never flush in the request path — the background task handles it.
    # This ensures a dead DB never blocks request handlers.


async def _periodic_flush():
    """Flush the buffer every _FLUSH_INTERVAL seconds, or sooner if full.

    Checks every second so large bursts don't accumulate unbounded,
    but only writes to DB on the interval or when buffer exceeds threshold.
    """
    last_flush = time.time()
    while True:
        await asyncio.sleep(1.0)
        with _buffer_lock:
            buf_len = len(_buffer)
        elapsed = time.time() - last_flush
        if buf_len >= _BUFFER_SIZE or (buf_len > 0 and elapsed >= _FLUSH_INTERVAL):
            _flush_buffer()
            last_flush = time.time()


def _flush_buffer():
    """Write all buffered entries to the database in a single transaction."""
    with _buffer_lock:
        if not _buffer:
            return
        entries = list(_buffer)
        _buffer.clear()

    try:
        session = SessionLocal()
        session.execute(
            text("""
                INSERT INTO http_access_log
                    (path, method, status_code, user_agent, client_ip, duration_ms)
                VALUES (:path, :method, :sc, :ua, :ip, :dur)
            """),
            entries,
        )
        session.commit()
        session.close()
    except Exception:
        logger.debug(f"Failed to flush {len(entries)} access log entries", exc_info=True)
