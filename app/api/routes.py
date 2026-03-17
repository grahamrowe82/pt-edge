"""REST API v1 router with per-key auth, usage tracking, and structured JSON responses."""

import json
import time
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import text

from app.api.auth import require_api_key
from app.api import queries
from app.db import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["api"])


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _ok(data, count: int = None, query_params: dict = None):
    meta = {"timestamp": datetime.now(timezone.utc).isoformat()}
    if count is not None:
        meta["count"] = count
    if query_params:
        meta["query"] = query_params
    return {"data": data, "meta": meta}


def _not_found(resource: str):
    raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": f"{resource} not found"}})


# ---------------------------------------------------------------------------
# Usage tracking
# ---------------------------------------------------------------------------

def _log_api_usage(api_key_id: int, endpoint: str, params: dict, duration_ms: int, status_code: int):
    """Fire-and-forget usage logging — never breaks a request."""
    try:
        session = SessionLocal()
        params_clean = {}
        for k, v in (params or {}).items():
            s = str(v)
            params_clean[k] = s[:200] if len(s) > 200 else s

        session.execute(
            text("""
                INSERT INTO api_usage (api_key_id, endpoint, params, duration_ms, status_code)
                VALUES (:kid, :ep, :params::jsonb, :dur, :sc)
            """),
            {"kid": api_key_id, "ep": endpoint, "params": json.dumps(params_clean), "dur": duration_ms, "sc": status_code},
        )
        session.execute(
            text("UPDATE api_keys SET last_used_at = NOW() WHERE id = :kid"),
            {"kid": api_key_id},
        )
        session.commit()
        session.close()
    except Exception:
        logger.debug("Failed to log API usage", exc_info=True)


# ---------------------------------------------------------------------------
# Auth dependency that also records request start time
# ---------------------------------------------------------------------------

async def _auth_and_track(request: Request, bg: BackgroundTasks, key_data: dict = Depends(require_api_key)):
    start = time.time()
    request.state.api_key_data = key_data

    def _log_after():
        duration_ms = int((time.time() - start) * 1000)
        _log_api_usage(
            api_key_id=key_data["id"],
            endpoint=request.url.path,
            params=dict(request.query_params),
            duration_ms=duration_ms,
            status_code=200,
        )

    bg.add_task(_log_after)
    return key_data


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/projects/bulk")
async def projects_bulk(
    request: Request,
    slugs: str = Query(..., description="Comma-separated slugs, max 20"),
    key_data: dict = Depends(_auth_and_track),
):
    slug_list = [s.strip() for s in slugs.split(",") if s.strip()][:20]
    results = queries.get_projects_bulk(slug_list)
    return _ok(results, count=len(results), query_params={"slugs": slug_list})


@router.get("/projects/{slug}")
async def project_detail(slug: str, request: Request, key_data: dict = Depends(_auth_and_track)):
    result = queries.get_project(slug)
    if not result:
        _not_found(f"Project '{slug}'")
    return _ok(result)


@router.get("/projects")
async def project_search(
    request: Request,
    q: str = Query(None),
    category: str = Query(None),
    limit: int = Query(20, le=50, ge=1),
    key_data: dict = Depends(_auth_and_track),
):
    results = queries.search_projects(q=q, category=category, limit=limit)
    return _ok(results, count=len(results), query_params={"q": q, "category": category, "limit": limit})


@router.get("/trending")
async def trending(
    request: Request,
    category: str = Query(None),
    window: str = Query("7d", pattern="^(7d|30d)$"),
    limit: int = Query(20, le=50, ge=1),
    key_data: dict = Depends(_auth_and_track),
):
    results = queries.get_trending(category=category, window=window, limit=limit)
    return _ok(results, count=len(results), query_params={"category": category, "window": window, "limit": limit})


@router.get("/whats-new")
async def whats_new(
    request: Request,
    days: int = Query(7, le=30, ge=1),
    key_data: dict = Depends(_auth_and_track),
):
    result = queries.get_whats_new(days=days)
    return _ok(result, query_params={"days": days})


@router.get("/labs/{slug}")
async def lab_detail(slug: str, request: Request, key_data: dict = Depends(_auth_and_track)):
    result = queries.get_lab(slug)
    if not result:
        _not_found(f"Lab '{slug}'")
    return _ok(result)


@router.get("/hn")
async def hn_posts(
    request: Request,
    q: str = Query(None),
    days: int = Query(30, le=90, ge=1),
    limit: int = Query(20, le=50, ge=1),
    key_data: dict = Depends(_auth_and_track),
):
    results = queries.get_hn_posts(q=q, days=days, limit=limit)
    return _ok(results, count=len(results), query_params={"q": q, "days": days, "limit": limit})


@router.get("/briefings")
async def briefings_list(
    request: Request,
    domain: str = Query(None),
    key_data: dict = Depends(_auth_and_track),
):
    results = queries.get_briefings(domain=domain)
    return _ok(results, count=len(results), query_params={"domain": domain})


@router.get("/briefings/{slug}")
async def briefing_detail(slug: str, request: Request, key_data: dict = Depends(_auth_and_track)):
    result = queries.get_briefing(slug)
    if not result:
        _not_found(f"Briefing '{slug}'")
    return _ok(result)
