"""API key generation and self-serve endpoint."""

import hashlib
import logging
import secrets

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import text

from domains.cyber.app.db import engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["keys"])

KEY_PREFIX = "cye_"


def generate_key() -> str:
    """Generate a new API key: cye_ + 32 hex chars = 36 chars total."""
    return KEY_PREFIX + secrets.token_hex(16)


class CreateKeyRequest(BaseModel):
    email: EmailStr
    company: str


@router.post("/keys")
async def create_key(req: CreateKeyRequest):
    """Self-serve API key creation. Max 3 active keys per email."""
    with engine.connect() as conn:
        # Check existing keys for this email
        count = conn.execute(text("""
            SELECT COUNT(*) FROM api_keys
            WHERE contact_email = :email AND is_active = true
        """), {"email": req.email}).scalar()

        if count >= 3:
            raise HTTPException(status_code=429, detail="Maximum 3 active keys per email")

        raw_key = generate_key()
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:8]

        conn.execute(text("""
            INSERT INTO api_keys (key_hash, key_prefix, company_name, contact_email, tier)
            VALUES (:kh, :kp, :company, :email, 'free')
        """), {"kh": key_hash, "kp": key_prefix, "company": req.company, "email": req.email})
        conn.commit()

    return {
        "data": {
            "key": raw_key,
            "prefix": key_prefix,
            "tier": "free",
            "daily_limit": 100,
        }
    }
