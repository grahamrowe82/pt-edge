"""Canonical-host redirect middleware for *-edge sites.

Redirects requests arriving on non-canonical hostnames (e.g. the bare
apex domain or the Render default *.onrender.com domain) to the canonical
hostname with a 301 Moved Permanently, preserving path and query string.

Usage:
    from app.core.middleware.canonical_host import CanonicalHostMiddleware
    app.add_middleware(CanonicalHostMiddleware, canonical_host="mcp.phasetransitions.ai")
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

logger = logging.getLogger(__name__)

# Paths that must never redirect (health checks, etc.)
_EXEMPT_PATHS = ("/healthz",)


class CanonicalHostMiddleware(BaseHTTPMiddleware):
    """301 redirect from any non-canonical hostname to the canonical one.

    Exempt paths (like /healthz) always pass through regardless of host,
    ensuring Render health checks work on any domain.
    """

    def __init__(self, app, canonical_host: str = ""):
        super().__init__(app)
        self.canonical_host = canonical_host.lower().strip()
        if self.canonical_host:
            logger.info("Canonical host redirect active: %s", canonical_host)

    async def dispatch(self, request, call_next):
        if not self.canonical_host:
            return await call_next(request)

        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        # X-Forwarded-Host is set by Render's reverse proxy
        host = (
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or ""
        )
        # Strip port if present (e.g. "host:443") and normalise case
        host = host.split(":")[0].lower().strip()

        # Missing/empty host: let the app handle it (will 404/400 naturally)
        if not host:
            return await call_next(request)

        if host == self.canonical_host:
            return await call_next(request)

        # Build redirect URL — always https, always canonical casing from env
        redirect_url = f"https://{self.canonical_host}{request.url.path}"
        if request.url.query:
            redirect_url += f"?{request.url.query}"

        return RedirectResponse(url=redirect_url, status_code=301)
