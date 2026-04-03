"""API key generation and self-serve signup endpoint."""

import hashlib
import secrets
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import text

from app.db import SessionLocal

router = APIRouter(prefix="/api/v1", tags=["keys"])


def generate_key() -> str:
    return "pte_" + secrets.token_hex(16)


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


class KeyRequest(BaseModel):
    email: Optional[EmailStr] = None
    company: Optional[str] = None


MAX_KEYS_PER_EMAIL = 3
MAX_ANON_KEYS_PER_IP_PER_DAY = 5

# In-memory counter: ip -> (date_str, count)
_ip_daily_counts: dict[str, tuple[str, int]] = defaultdict(lambda: ("", 0))


def _today_utc() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/keys")
async def create_key(body: KeyRequest = KeyRequest(), request: Request = None):
    email = body.email.strip().lower() if body.email else None
    company = body.company.strip() if body.company else None

    session = SessionLocal()
    try:
        if email:
            count = session.execute(
                text("SELECT count(*) FROM api_keys WHERE contact_email = :email AND revoked_at IS NULL"),
                {"email": email},
            ).scalar()

            if count >= MAX_KEYS_PER_EMAIL:
                raise HTTPException(
                    status_code=429,
                    detail=f"Maximum {MAX_KEYS_PER_EMAIL} active keys per email address.",
                )
        else:
            # IP-based spam guard for anonymous keys
            client_ip = _get_client_ip(request)
            today = _today_utc()
            date_str, count = _ip_daily_counts[client_ip]
            if date_str != today:
                _ip_daily_counts[client_ip] = (today, 1)
            else:
                if count >= MAX_ANON_KEYS_PER_IP_PER_DAY:
                    raise HTTPException(
                        status_code=429,
                        detail=f"Maximum {MAX_ANON_KEYS_PER_IP_PER_DAY} anonymous keys per day. Provide an email for more.",
                    )
                _ip_daily_counts[client_ip] = (today, count + 1)

        raw_key = generate_key()
        key_hash = hash_key(raw_key)
        key_prefix = raw_key[:8]

        tier = "pro" if email else "free"
        from app.api.auth import TIER_LIMITS
        daily_limit = TIER_LIMITS.get(tier, 500)

        session.execute(
            text("""
                INSERT INTO api_keys (key_hash, key_prefix, company_name, contact_email, tier)
                VALUES (:h, :p, :company, :email, :tier)
            """),
            {"h": key_hash, "p": key_prefix, "company": company or "anonymous", "email": email or "", "tier": tier},
        )
        session.commit()

        return {
            "data": {
                "key": raw_key,
                "prefix": key_prefix,
                "tier": tier,
                "daily_limit": daily_limit,
            }
        }
    finally:
        session.close()
