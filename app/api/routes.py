"""REST API v1 router with per-key auth, usage tracking, and structured JSON responses."""

import json
import time
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text

from app.api.auth import optional_api_key
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
# Usage tracking middleware (mounted on the app, scoped to /api/v1/)
# ---------------------------------------------------------------------------

class APIUsageMiddleware(BaseHTTPMiddleware):
    """Logs usage for /api/v1/ requests after the response is sent."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/v1/"):
            return await call_next(request)

        start = time.time()
        response = await call_next(request)
        duration_ms = int((time.time() - start) * 1000)

        # Attach rate limit headers
        rate_limit = getattr(request.state, "rate_limit", None)
        if rate_limit:
            from app.api.auth import _rate_limit_headers
            for k, v in _rate_limit_headers(rate_limit["limit"], rate_limit["remaining"]).items():
                response.headers[k] = v

        # Log ALL calls — keyed and anonymous
        from app.api.auth import _get_client_ip
        key_data = getattr(request.state, "api_key_data", None)
        ua = request.headers.get("User-Agent", "")
        transport = "cli" if ua.startswith("ptedge-cli/") else "rest"

        # Merge query params + any POST body params stashed by endpoint handlers
        params = dict(request.query_params)
        extra = getattr(request.state, "log_params", None)
        if extra:
            params.update(extra)

        _log_api_usage(
            api_key_id=key_data.get("id") if key_data else None,
            endpoint=request.url.path,
            params=params,
            duration_ms=duration_ms,
            status_code=response.status_code,
            transport=transport,
            client_ip=_get_client_ip(request),
            user_agent=ua[:500] if ua else None,
        )
        return response


def _log_api_usage(
    api_key_id: int | None,
    endpoint: str,
    params: dict,
    duration_ms: int,
    status_code: int,
    transport: str,
    client_ip: str | None,
    user_agent: str | None,
):
    """Fire-and-forget usage logging — never breaks a request."""
    try:
        session = SessionLocal()
        params_clean = {}
        for k, v in (params or {}).items():
            s = str(v)
            params_clean[k] = s[:200] if len(s) > 200 else s

        session.execute(
            text("""
                INSERT INTO api_usage
                    (api_key_id, endpoint, params, duration_ms, status_code,
                     transport, client_ip, user_agent)
                VALUES
                    (:kid, :ep, CAST(:params AS jsonb), :dur, :sc,
                     :transport, :ip, :ua)
            """),
            {
                "kid": api_key_id, "ep": endpoint,
                "params": json.dumps(params_clean),
                "dur": duration_ms, "sc": status_code,
                "transport": transport, "ip": client_ip,
                "ua": user_agent,
            },
        )
        if api_key_id:
            session.execute(
                text("UPDATE api_keys SET last_used_at = NOW() WHERE id = :kid"),
                {"kid": api_key_id},
            )
        session.commit()
        session.close()
    except Exception:
        logger.debug("Failed to log API usage", exc_info=True)


# ---------------------------------------------------------------------------
# Auth dependency that stashes key_data on request.state for middleware
# ---------------------------------------------------------------------------

async def _auth(request: Request, key_data: dict = Depends(optional_api_key)):
    request.state.api_key_data = key_data
    return key_data


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/projects/{slug}")
async def project_detail(slug: str, request: Request, key_data: dict = Depends(_auth)):
    result = queries.get_project(slug)
    if not result:
        if "/" in slug:
            domains = ", ".join(sorted(queries.DOMAIN_VIEWS.keys()))
            raise HTTPException(status_code=404, detail={"error": {
                "code": "not_found",
                "message": f"Project '{slug}' not found.",
                "hint": f"For repos by full name, use: GET /api/v1/quality/{{domain}}/{slug} — valid domains: {domains}",
            }})
        _not_found(f"Project '{slug}'")
    return _ok(result)


@router.get("/trending")
async def trending(
    request: Request,
    category: str = Query(None),
    stack_layer: str = Query(None, pattern="^(model|inference|orchestration|data|eval|interface|infra)$"),
    domain: str = Query(None),
    window: str = Query("7d", pattern="^(7d|30d)$"),
    limit: int = Query(20, le=50, ge=1),
    key_data: dict = Depends(_auth),
):
    results = queries.get_trending(category=category, stack_layer=stack_layer, domain=domain, window=window, limit=limit)
    return _ok(results, count=len(results), query_params={"category": category, "stack_layer": stack_layer, "domain": domain, "window": window, "limit": limit})


# ---------------------------------------------------------------------------
# Generic quality endpoints (all 30 domains)
# ---------------------------------------------------------------------------

_VALID_DOMAINS = "|".join(queries.DOMAIN_VIEWS.keys())


@router.get("/quality")
async def quality_scores(
    request: Request,
    domain: str = Query(..., description="Domain slug (e.g. mcp, agents, ml-frameworks)"),
    subcategory: str = Query(None),
    quality_tier: str = Query(None, pattern="^(verified|established|emerging|experimental)$"),
    min_score: int = Query(None, ge=0, le=100),
    limit: int = Query(50, le=500, ge=1),
    offset: int = Query(0, ge=0),
    key_data: dict = Depends(_auth),
):
    if domain not in queries.DOMAIN_VIEWS:
        raise HTTPException(status_code=422, detail={"error": {"code": "invalid_domain", "message": f"Unknown domain '{domain}'. Valid: {', '.join(sorted(queries.DOMAIN_VIEWS.keys()))}"}})
    results = queries.get_quality_scores(
        domain=domain, subcategory=subcategory, quality_tier=quality_tier,
        min_score=min_score, limit=limit, offset=offset,
    )
    return _ok(results, count=len(results), query_params={
        "domain": domain, "subcategory": subcategory, "quality_tier": quality_tier,
        "min_score": min_score, "limit": limit, "offset": offset,
    })


@router.get("/quality/{domain}/{repo:path}")
async def quality_repo(
    domain: str,
    repo: str,
    request: Request,
    key_data: dict = Depends(_auth),
):
    if domain not in queries.DOMAIN_VIEWS:
        raise HTTPException(status_code=422, detail={"error": {"code": "invalid_domain", "message": f"Unknown domain '{domain}'."}})
    result = queries.get_quality_by_repo(domain=domain, repo=repo)
    if not result:
        other_domains = ", ".join(sorted(d for d in queries.DOMAIN_VIEWS.keys() if d != domain))
        raise HTTPException(status_code=404, detail={"error": {
            "code": "not_found",
            "message": f"Repo '{repo}' not found in domain '{domain}'.",
            "hint": f"This repo may be in a different domain. Try: {other_domains}",
        }})
    return _ok(result)


@router.get("/datasets/quality")
async def dataset_quality(
    response: Response,
    domain: str = Query(..., description="Domain slug (e.g. mcp, agents, ml-frameworks)"),
    subcategory: str = Query(None),
    quality_tier: str = Query(None, pattern="^(verified|established|emerging|experimental)$"),
    limit: int = Query(500, le=2000, ge=1),
    offset: int = Query(0, ge=0),
):
    if domain not in queries.DOMAIN_VIEWS:
        raise HTTPException(status_code=422, detail={"error": {"code": "invalid_domain", "message": f"Unknown domain '{domain}'. Valid: {', '.join(sorted(queries.DOMAIN_VIEWS.keys()))}"}})
    results = queries.get_quality_scores(
        domain=domain, subcategory=subcategory, quality_tier=quality_tier,
        limit=limit, offset=offset,
    )
    response.headers["Cache-Control"] = "public, max-age=3600"
    return _ok(results, count=len(results), query_params={
        "domain": domain, "subcategory": subcategory, "quality_tier": quality_tier,
        "limit": limit, "offset": offset,
    })


# ---------------------------------------------------------------------------
# Generic endpoints — shared core layer (REST + MCP + CLI parity)
# ---------------------------------------------------------------------------

from app.api import core


@router.get("/status")
async def api_status(request: Request):
    """Orientation: table count, repo count, domains, freshness."""
    data = await core.get_status()
    return _ok(data)


@router.get("/tables")
async def api_list_tables(request: Request, key_data: dict = Depends(_auth)):
    """List all database tables with column count and row estimate."""
    tables = await core.list_tables()
    return _ok(tables, count=len(tables))


@router.get("/tables/search")
async def api_search_tables(
    request: Request,
    q: str = Query(..., description="Keyword to search table/column names"),
    key_data: dict = Depends(_auth),
):
    """Find tables by keyword in table or column names."""
    tables = await core.search_tables(q)
    return _ok(tables, count=len(tables), query_params={"q": q})


@router.get("/tables/{table_name}")
async def api_describe_table(
    table_name: str,
    request: Request,
    key_data: dict = Depends(_auth),
):
    """Column metadata for a specific table."""
    data = await core.describe_table(table_name)
    if data is None:
        _not_found(f"Table '{table_name}'")
    return _ok(data)


@router.post("/query")
async def api_query(
    request: Request,
    key_data: dict = Depends(_auth),
):
    """Run a read-only SQL query. Body: {"sql": "SELECT ..."}"""
    body = await request.json()
    sql = body.get("sql", "")
    if not sql:
        raise HTTPException(status_code=400, detail={"error": {"code": "missing_sql", "message": "Request body must include 'sql' field."}})
    request.state.log_params = {"sql": sql[:500]}
    result = await core.run_query(sql)
    if "error" in result:
        raise HTTPException(status_code=400, detail={"error": {"code": "query_error", "message": result["error"]}})
    return _ok(result["rows"], count=result["count"], query_params={"sql": sql[:200]})


@router.get("/workflows")
async def api_list_workflows(request: Request, key_data: dict = Depends(_auth)):
    """List SQL recipe workflows — pre-built query templates."""
    workflows = await core.list_workflows()
    return _ok(workflows, count=len(workflows))


@router.post("/feedback")
async def api_submit_feedback(
    request: Request,
    key_data: dict = Depends(_auth),
):
    """Submit feedback. Body: {"topic": "...", "text": "...", "category": "observation"}"""
    body = await request.json()
    topic = body.get("topic", "")
    text_body = body.get("text", "")
    if not topic or not text_body:
        raise HTTPException(status_code=400, detail={"error": {"code": "missing_fields", "message": "Request body must include 'topic' and 'text'."}})
    result = await core.submit_feedback(
        topic=topic,
        text_body=text_body,
        context=body.get("context"),
        category=body.get("category", "observation"),
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail={"error": {"code": "validation_error", "message": result["error"]}})
    return _ok(result)
