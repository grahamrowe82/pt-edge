"""Centralized GitHub API gateway.

Every GitHub API call in the codebase flows through this module.
It reads rate-limit headers from every response (the source of truth),
logs per-caller attribution, and classifies 403 responses correctly.

Usage:
    from app.github_client import get_github_client

    gh = get_github_client()
    resp = await gh.get("/repos/openai/gpt/readme", caller="handler.fetch_readme",
                        accept="application/vnd.github.raw+json")
"""
import logging
import time

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)

# How often to log usage stats (seconds)
_LOG_INTERVAL = 300  # 5 minutes
# Log immediately when remaining drops below this threshold
_LOW_REMAINING_THRESHOLD = 500


class GitHubRateLimitError(Exception):
    """Primary rate limit exhausted. Caller should back off until reset."""

    def __init__(self, reset_at: float):
        self.reset_at = reset_at
        wait = max(0, reset_at - time.time())
        super().__init__(f"GitHub rate limit exhausted, resets in {wait:.0f}s")


class GitHubClient:
    """Centralized GitHub API gateway. Single instance per process."""

    def __init__(self, token: str):
        headers = {
            "User-Agent": "pt-edge/1.0",
            "Accept": "application/vnd.github+json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        self._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers=headers,
            timeout=30.0,
            follow_redirects=True,
        )
        # Rate limit state (updated from response headers)
        self._core_remaining: int = 5000
        self._core_reset: float = 0.0
        self._search_remaining: int = 30
        self._search_reset: float = 0.0

        # Per-caller attribution
        self._caller_counts: dict[str, int] = {}
        self._total_calls: int = 0
        self._last_log: float = time.monotonic()
        self._window_start: float = time.monotonic()

    # ── Public API ──────────────────────────────────────────────

    async def get(
        self,
        path: str,
        *,
        caller: str,
        params: dict | None = None,
        accept: str | None = None,
    ) -> httpx.Response:
        """GET request to GitHub REST API.

        Args:
            path: Relative path, e.g. "/repos/openai/gpt/readme"
            caller: Identifies who is consuming budget, e.g. "handler.fetch_readme"
            params: Optional query parameters
            accept: Optional Accept header override
        """
        is_search = path.startswith("/search/")

        # Pre-request guard: don't waste a call if we know we're exhausted
        if is_search:
            if self._search_remaining <= 0 and self._search_reset > time.time():
                raise GitHubRateLimitError(self._search_reset)
        else:
            if self._core_remaining <= 0 and self._core_reset > time.time():
                raise GitHubRateLimitError(self._core_reset)

        headers = {}
        if accept:
            headers["Accept"] = accept

        resp = await self._client.get(path, params=params, headers=headers)

        api = "search" if is_search else "core"
        self._update_rate_limits(resp, api)
        self._record_call(caller)

        return resp

    async def post_graphql(self, query: str, *, caller: str) -> httpx.Response:
        """POST to /graphql endpoint.

        Args:
            query: GraphQL query string
            caller: Identifies who is consuming budget
        """
        if self._core_remaining <= 0 and self._core_reset > time.time():
            raise GitHubRateLimitError(self._core_reset)

        resp = await self._client.post("/graphql", json={"query": query})

        self._update_rate_limits(resp, "core")
        self._record_call(caller)

        return resp

    def remaining(self, api: str = "core") -> int:
        """Current remaining calls from GitHub headers."""
        if api == "search":
            return self._search_remaining
        return self._core_remaining

    def caller_stats(self) -> dict[str, int]:
        """Snapshot of per-caller call counts for the current window."""
        return dict(self._caller_counts)

    def classify_403(self, resp: httpx.Response) -> str:
        """Classify a 403 response.

        Returns:
            "rate_limit" — primary rate limit exhausted (X-RateLimit-Remaining: 0)
            "secondary_rate_limit" — abuse detection (Retry-After header)
            "access_denied" — private repo, DMCA, insufficient scope, etc.
        """
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining is not None and int(remaining) == 0:
            return "rate_limit"

        if resp.headers.get("Retry-After"):
            return "secondary_rate_limit"

        try:
            body = resp.json()
            message = body.get("message", "").lower()
            if "rate limit" in message or "abuse" in message:
                return "secondary_rate_limit"
        except Exception:
            pass

        return "access_denied"

    async def close(self):
        """Shutdown the underlying client."""
        self._log_stats(force=True)
        await self._client.aclose()

    # ── Internal ────────────────────────────────────────────────

    def _update_rate_limits(self, resp: httpx.Response, api: str = "core") -> None:
        """Read X-RateLimit-* headers and update internal state."""
        remaining = resp.headers.get("X-RateLimit-Remaining")
        reset = resp.headers.get("X-RateLimit-Reset")

        if remaining is not None:
            remaining_int = int(remaining)
            if api == "search":
                self._search_remaining = remaining_int
                if reset:
                    self._search_reset = float(reset)
            else:
                prev = self._core_remaining
                self._core_remaining = remaining_int
                if reset:
                    self._core_reset = float(reset)
                # Log immediately if we just crossed the low threshold
                if prev >= _LOW_REMAINING_THRESHOLD and remaining_int < _LOW_REMAINING_THRESHOLD:
                    self._log_stats(force=True)
                # Reset caller counts when GitHub resets the window
                if remaining_int > prev + 100:
                    # Big jump in remaining = new window
                    self._caller_counts.clear()
                    self._total_calls = 0
                    self._window_start = time.monotonic()

    def _record_call(self, caller: str) -> None:
        """Increment per-caller counter and periodically log stats."""
        self._caller_counts[caller] = self._caller_counts.get(caller, 0) + 1
        self._total_calls += 1
        self._log_stats()

    def _log_stats(self, force: bool = False) -> None:
        """Log usage stats every _LOG_INTERVAL seconds."""
        now = time.monotonic()
        if not force and (now - self._last_log) < _LOG_INTERVAL:
            return

        self._last_log = now
        reset_in = max(0, self._core_reset - time.time())
        logger.info(
            f"github_api remaining={self._core_remaining} "
            f"reset_in={reset_in:.0f}s "
            f"total={self._total_calls} "
            f"callers={self._caller_counts}"
        )


# ── Module singleton ────────────────────────────────────────────

_client: GitHubClient | None = None


def get_github_client() -> GitHubClient:
    """Return the process-wide GitHubClient singleton."""
    global _client
    if _client is None:
        _client = GitHubClient(settings.GITHUB_TOKEN)
    return _client
