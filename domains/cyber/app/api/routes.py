"""REST API routes with authentication, usage tracking, and rate limiting."""

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text

from domains.cyber.app.api.auth import validate_key
from domains.cyber.app.api import queries
from domains.cyber.app.db import engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["api"])


def _auth(request: Request) -> dict:
    """Extract and validate API key from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        raw_key = auth[7:]
    else:
        raw_key = request.query_params.get("key", "")

    if not raw_key:
        raise HTTPException(status_code=401, detail="API key required")

    key_data = validate_key(raw_key)
    if key_data is None:
        raise HTTPException(status_code=403, detail="Invalid or rate-limited API key")

    return key_data


def _meta(count: int, **kwargs) -> dict:
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "count": count, **kwargs}


# ---------------------------------------------------------------------------
# CVE endpoints
# ---------------------------------------------------------------------------

@router.get("/cves")
async def list_cves(
    q: str | None = Query(None), min_severity: float | None = Query(None),
    kev_only: bool = Query(False), limit: int = Query(20),
    _key: dict = Depends(_auth),
):
    data = queries.search_cves(q=q, min_severity=min_severity, kev_only=kev_only, limit=limit)
    return {"data": data, "meta": _meta(len(data), query={"q": q, "min_severity": min_severity})}


@router.get("/cves/{cve_id}")
async def get_cve(cve_id: str, _key: dict = Depends(_auth)):
    data = queries.get_cve(cve_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"CVE {cve_id} not found")
    return {"data": data, "meta": _meta(1)}


# ---------------------------------------------------------------------------
# Software endpoints
# ---------------------------------------------------------------------------

@router.get("/software")
async def list_software(
    q: str | None = Query(None), limit: int = Query(20),
    _key: dict = Depends(_auth),
):
    data = queries.search_software(q=q, limit=limit)
    return {"data": data, "meta": _meta(len(data))}


@router.get("/software/{slug}")
async def get_software(slug: str, _key: dict = Depends(_auth)):
    results = queries.search_software(q=slug, limit=1)
    if not results:
        raise HTTPException(status_code=404, detail=f"Software '{slug}' not found")
    return {"data": results[0], "meta": _meta(1)}


# ---------------------------------------------------------------------------
# Vendor endpoints
# ---------------------------------------------------------------------------

@router.get("/vendors")
async def list_vendors(
    q: str | None = Query(None), limit: int = Query(20),
    _key: dict = Depends(_auth),
):
    data = queries.search_vendors(q=q, limit=limit)
    return {"data": data, "meta": _meta(len(data))}


@router.get("/vendors/{slug}")
async def get_vendor(slug: str, _key: dict = Depends(_auth)):
    results = queries.search_vendors(q=slug, limit=1)
    if not results:
        raise HTTPException(status_code=404, detail=f"Vendor '{slug}' not found")
    return {"data": results[0], "meta": _meta(1)}


# ---------------------------------------------------------------------------
# Weakness endpoints
# ---------------------------------------------------------------------------

@router.get("/weaknesses")
async def list_weaknesses(
    q: str | None = Query(None), limit: int = Query(20),
    _key: dict = Depends(_auth),
):
    data = queries.search_weaknesses(q=q, limit=limit)
    return {"data": data, "meta": _meta(len(data))}


@router.get("/weaknesses/{cwe_id}")
async def get_weakness(cwe_id: str, _key: dict = Depends(_auth)):
    results = queries.search_weaknesses(q=cwe_id, limit=1)
    if not results:
        raise HTTPException(status_code=404, detail=f"Weakness {cwe_id} not found")
    return {"data": results[0], "meta": _meta(1)}


# ---------------------------------------------------------------------------
# Technique endpoints
# ---------------------------------------------------------------------------

@router.get("/techniques")
async def list_techniques(
    q: str | None = Query(None), limit: int = Query(20),
    _key: dict = Depends(_auth),
):
    data = queries.search_techniques(q=q, limit=limit)
    return {"data": data, "meta": _meta(len(data))}


@router.get("/techniques/{technique_id}")
async def get_technique(technique_id: str, _key: dict = Depends(_auth)):
    results = queries.search_techniques(q=technique_id, limit=1)
    if not results:
        raise HTTPException(status_code=404, detail=f"Technique {technique_id} not found")
    return {"data": results[0], "meta": _meta(1)}


# ---------------------------------------------------------------------------
# Pattern endpoints
# ---------------------------------------------------------------------------

@router.get("/patterns")
async def list_patterns(
    q: str | None = Query(None), limit: int = Query(20),
    _key: dict = Depends(_auth),
):
    data = queries.search_patterns(q=q, limit=limit)
    return {"data": data, "meta": _meta(len(data))}


@router.get("/patterns/{capec_id}")
async def get_pattern(capec_id: str, _key: dict = Depends(_auth)):
    results = queries.search_patterns(q=capec_id, limit=1)
    if not results:
        raise HTTPException(status_code=404, detail=f"Pattern {capec_id} not found")
    return {"data": results[0], "meta": _meta(1)}


# ---------------------------------------------------------------------------
# Usage tracking middleware
# ---------------------------------------------------------------------------

class APIUsageMiddleware(BaseHTTPMiddleware):
    """Track API usage per request. Fire-and-forget — never blocks."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/v1/"):
            return await call_next(request)

        t0 = time.time()
        response = await call_next(request)
        duration_ms = int((time.time() - t0) * 1000)

        try:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                from domains.cyber.app.api.auth import _hash_key
                key_hash = _hash_key(auth[7:])
                with engine.connect() as conn:
                    conn.execute(text("""
                        INSERT INTO api_usage (api_key_id, endpoint, duration_ms, status_code)
                        SELECT id, :ep, :dur, :sc FROM api_keys WHERE key_hash = :kh
                    """), {
                        "kh": key_hash,
                        "ep": request.url.path,
                        "dur": duration_ms,
                        "sc": response.status_code,
                    })
                    conn.commit()
        except Exception:
            pass  # fire-and-forget

        return response
