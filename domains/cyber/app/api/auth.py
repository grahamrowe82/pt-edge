"""API key authentication and rate limiting."""

import hashlib
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import text

from domains.cyber.app.db import engine

logger = logging.getLogger(__name__)

KEY_PREFIX = "cye_"
KEY_LENGTH = 36  # cye_ + 32 hex chars

# In-memory cache: key_hash -> (key_data, expires_at)
_cache: dict[str, tuple[dict, float]] = {}
CACHE_TTL = 60  # seconds

# Daily rate limits by tier
DAILY_LIMITS = {"free": 100, "pro": 10_000}

# In-memory daily counters: (key_hash, date_str) -> count
_daily_counts: dict[tuple[str, str], int] = {}


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def validate_key(raw_key: str) -> dict | None:
    """Validate an API key. Returns key_data dict or None if invalid.

    Checks: format, existence, active status, rate limit.
    """
    if not raw_key or not raw_key.startswith(KEY_PREFIX) or len(raw_key) != KEY_LENGTH:
        return None

    key_hash = _hash_key(raw_key)
    now = time.time()

    # Check cache
    if key_hash in _cache:
        cached_data, expires = _cache[key_hash]
        if now < expires:
            key_data = cached_data
        else:
            del _cache[key_hash]
            key_data = None
    else:
        key_data = None

    # Fetch from DB if not cached
    if key_data is None:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT id, key_hash, key_prefix, company_name, contact_email,
                       tier, is_active, revoked_at
                FROM api_keys WHERE key_hash = :kh
            """), {"kh": key_hash}).mappings().fetchone()

        if row is None:
            return None

        key_data = dict(row)
        _cache[key_hash] = (key_data, now + CACHE_TTL)

    # Check active
    if not key_data.get("is_active"):
        return None
    if key_data.get("revoked_at"):
        return None

    # Rate limit
    tier = key_data.get("tier", "free")
    limit = DAILY_LIMITS.get(tier, 100)
    counter_key = (key_hash, _today())
    current = _daily_counts.get(counter_key, 0)
    if current >= limit:
        return None

    _daily_counts[counter_key] = current + 1

    # Update last_used_at (fire-and-forget)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "UPDATE api_keys SET last_used_at = now() WHERE key_hash = :kh"
            ), {"kh": key_hash})
            conn.commit()
    except Exception:
        pass

    return key_data
