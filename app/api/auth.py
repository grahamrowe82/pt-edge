import hashlib
import time
import logging
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from sqlalchemy import text

from app.db import readonly_engine

logger = logging.getLogger(__name__)

# In-memory cache: key_hash -> (key_data_dict, expires_at)
_key_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 60  # seconds

# In-memory daily rate counter: key_id -> (date_str, count)
_daily_counts: dict[int, tuple[str, int]] = defaultdict(lambda: ("", 0))

TIER_LIMITS = {
    "free": 100,
    "pro": 10_000,
}


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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


async def require_api_key(request: Request) -> dict:
    """FastAPI dependency that validates Bearer token and enforces rate limits."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail={"error": {"code": "unauthorized", "message": "Missing Authorization: Bearer <key> header"}})

    raw_key = auth[7:].strip()
    if not raw_key.startswith("pte_") or len(raw_key) != 36:
        raise HTTPException(status_code=401, detail={"error": {"code": "unauthorized", "message": "Invalid API key format"}})

    key_hash = _hash_key(raw_key)
    key_data = _lookup_key(key_hash)

    if not key_data:
        raise HTTPException(status_code=401, detail={"error": {"code": "unauthorized", "message": "Invalid API key"}})

    if not key_data.get("is_active") or key_data.get("revoked_at") is not None:
        raise HTTPException(status_code=401, detail={"error": {"code": "unauthorized", "message": "API key has been revoked"}})

    # Rate limiting
    key_id = key_data["id"]
    tier = key_data.get("tier", "free")
    limit = TIER_LIMITS.get(tier, 100)
    today = _today_utc()

    date_str, count = _daily_counts[key_id]
    if date_str != today:
        # New day — reset
        _daily_counts[key_id] = (today, 1)
    else:
        if count >= limit:
            raise HTTPException(
                status_code=429,
                detail={"error": {"code": "rate_limit_exceeded", "message": f"Daily limit of {limit} requests exceeded. Resets at midnight UTC."}},
            )
        _daily_counts[key_id] = (today, count + 1)

    return key_data
