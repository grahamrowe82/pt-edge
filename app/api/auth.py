import hashlib
import time
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException, Request
from sqlalchemy import text

from app.db import readonly_engine

logger = logging.getLogger(__name__)

# In-memory cache: key_hash -> (key_data_dict, expires_at)
_key_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 60  # seconds

# In-memory daily rate counters
_daily_counts: dict[int, tuple[str, int]] = defaultdict(lambda: ("", 0))  # key_id -> (date, count)
_ip_daily_counts: dict[str, tuple[str, int]] = defaultdict(lambda: ("", 0))  # ip -> (date, count)

TIER_LIMITS = {
    "anonymous": 100,
    "free": 1_000,
    "pro": 10_000,
}


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _lookup_key(key_hash: str) -> dict | None:
    """Look up an API key by hash, with 60s cache."""
    now = time.time()
    cached = _key_cache.get(key_hash)
    if cached and cached[1] > now:
        return cached[0]

    try:
        with readonly_engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT id, key_hash, key_prefix, company_name, contact_email,
                           tier, is_active, revoked_at
                    FROM api_keys
                    WHERE key_hash = :h
                """),
                {"h": key_hash},
            ).fetchone()
    except Exception:
        logger.exception("Failed to look up API key")
        return None

    if not row:
        return None

    data = dict(row._mapping)
    _key_cache[key_hash] = (data, now + _CACHE_TTL)
    return data


def _rate_limit_headers(limit: int, remaining: int) -> dict[str, str]:
    """Standard rate limit headers."""
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": tomorrow.isoformat(),
    }


def _enforce_rate_limit_keyed(key_data: dict, request: Request) -> None:
    """Rate limit by API key."""
    key_id = key_data["id"]
    tier = key_data.get("tier", "free")
    limit = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
    today = _today_utc()

    date_str, count = _daily_counts[key_id]
    if date_str != today:
        _daily_counts[key_id] = (today, 1)
        count = 0
    else:
        if count >= limit:
            raise HTTPException(
                status_code=429,
                detail={"error": {"code": "rate_limit_exceeded", "message": f"Daily limit of {limit} requests exceeded. Resets at midnight UTC."}},
                headers=_rate_limit_headers(limit, 0),
            )
        _daily_counts[key_id] = (today, count + 1)

    request.state.rate_limit = {"limit": limit, "remaining": max(0, limit - count - 1)}


def _enforce_rate_limit_anonymous(request: Request) -> None:
    """Rate limit by IP address for unauthenticated requests."""
    ip = _get_client_ip(request)
    limit = TIER_LIMITS["anonymous"]
    today = _today_utc()

    date_str, count = _ip_daily_counts[ip]
    if date_str != today:
        _ip_daily_counts[ip] = (today, 1)
        count = 0
    else:
        if count >= limit:
            raise HTTPException(
                status_code=429,
                detail={"error": {
                    "code": "rate_limit_exceeded",
                    "message": (
                        f"Anonymous limit of {limit} requests/day exceeded. "
                        f"Get a free API key for {TIER_LIMITS['free']}/day: POST /api/v1/keys (no email required). "
                        f"Add your email for {TIER_LIMITS['pro']:,}/day."
                    ),
                }},
                headers=_rate_limit_headers(limit, 0),
            )
        _ip_daily_counts[ip] = (today, count + 1)

    request.state.rate_limit = {"limit": limit, "remaining": max(0, limit - count - 1)}


async def optional_api_key(request: Request) -> dict:
    """FastAPI dependency: validates Bearer token if present, allows anonymous access otherwise."""
    auth = request.headers.get("authorization", "")

    if not auth.lower().startswith("bearer "):
        # Anonymous access — rate limit by IP
        _enforce_rate_limit_anonymous(request)
        return {"tier": "anonymous", "id": None}

    raw_key = auth[7:].strip()
    if not raw_key.startswith("pte_") or len(raw_key) != 36:
        raise HTTPException(status_code=401, detail={"error": {"code": "unauthorized", "message": "Invalid API key format. Keys start with pte_ and are 36 characters."}})

    key_hash = _hash_key(raw_key)
    key_data = _lookup_key(key_hash)

    if not key_data:
        raise HTTPException(status_code=401, detail={"error": {"code": "unauthorized", "message": "Invalid API key"}})

    if not key_data.get("is_active") or key_data.get("revoked_at") is not None:
        raise HTTPException(status_code=401, detail={"error": {"code": "unauthorized", "message": "API key has been revoked"}})

    _enforce_rate_limit_keyed(key_data, request)
    return key_data


def validate_api_key(raw_key: str) -> dict | None:
    """Validate a pte_* API key without HTTP context. Returns key_data dict or None.

    Used by MCP and CLI transports where FastAPI dependencies aren't available.
    Does NOT enforce rate limits — caller is responsible for that.
    """
    if not raw_key or not raw_key.startswith("pte_") or len(raw_key) != 36:
        return None
    key_hash = _hash_key(raw_key)
    key_data = _lookup_key(key_hash)
    if not key_data:
        return None
    if not key_data.get("is_active") or key_data.get("revoked_at") is not None:
        return None
    return key_data


# Keep the old name as alias for backward compatibility with manage script imports
require_api_key = optional_api_key
