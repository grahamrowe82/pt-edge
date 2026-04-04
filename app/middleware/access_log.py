import logging
import time

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


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Log HTTP requests to static directory pages (HTML only)."""

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
            _log_access(
                path=path[:200],
                method=request.method,
                status_code=response.status_code,
                user_agent=(request.headers.get("User-Agent", "") or "")[:300],
                client_ip=client_ip,
                duration_ms=duration_ms,
            )

        return response


def _log_access(path, method, status_code, user_agent, client_ip, duration_ms):
    """Fire-and-forget access logging -- never breaks a request."""
    try:
        session = SessionLocal()
        session.execute(
            text("""
                INSERT INTO http_access_log
                    (path, method, status_code, user_agent, client_ip, duration_ms)
                VALUES (:path, :method, :sc, :ua, :ip, :dur)
            """),
            {
                "path": path,
                "method": method,
                "sc": status_code,
                "ua": user_agent,
                "ip": client_ip,
                "dur": duration_ms,
            },
        )
        session.commit()
        session.close()
    except Exception:
        logger.debug("Failed to log HTTP access", exc_info=True)
