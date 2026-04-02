"""API key generation and self-serve signup endpoint."""

import hashlib
import secrets

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
    email: EmailStr
    company: str


MAX_KEYS_PER_EMAIL = 3


@router.post("/keys")
async def create_key(body: KeyRequest, request: Request):
    email = body.email.strip().lower()
    company = body.company.strip()

    if not company:
        raise HTTPException(status_code=422, detail="Company name is required.")

    session = SessionLocal()
    try:
        count = session.execute(
            text("SELECT count(*) FROM api_keys WHERE contact_email = :email AND revoked_at IS NULL"),
            {"email": email},
        ).scalar()

        if count >= MAX_KEYS_PER_EMAIL:
            raise HTTPException(
                status_code=429,
                detail=f"Maximum {MAX_KEYS_PER_EMAIL} active keys per email address.",
            )

        raw_key = generate_key()
        key_hash = hash_key(raw_key)
        key_prefix = raw_key[:8]

        session.execute(
            text("""
                INSERT INTO api_keys (key_hash, key_prefix, company_name, contact_email, tier)
                VALUES (:h, :p, :company, :email, 'free')
            """),
            {"h": key_hash, "p": key_prefix, "company": company, "email": email},
        )
        session.commit()

        return {
            "data": {
                "key": raw_key,
                "prefix": key_prefix,
                "tier": "free",
                "daily_limit": 100,
            }
        }
    finally:
        session.close()
