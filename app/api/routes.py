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

        key_data = getattr(request.state, "api_key_data", None)
        if key_data and key_data.get("id"):
            _log_api_usage(
                api_key_id=key_data["id"],
                endpoint=request.url.path,
                params=dict(request.query_params),
                duration_ms=duration_ms,
                status_code=response.status_code,
            )
        return response


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
# Auth dependency that stashes key_data on request.state for middleware
# ---------------------------------------------------------------------------

async def _auth(request: Request, key_data: dict = Depends(optional_api_key)):
    request.state.api_key_data = key_data
    return key_data


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/projects/bulk")
async def projects_bulk(
    request: Request,
    slugs: str = Query(..., description="Comma-separated slugs, max 20"),
    key_data: dict = Depends(_auth),
):
    slug_list = [s.strip() for s in slugs.split(",") if s.strip()][:20]
    results = queries.get_projects_bulk(slug_list)
    return _ok(results, count=len(results), query_params={"slugs": slug_list})


@router.get("/project-briefs")
async def project_briefs_list(
    request: Request,
    domain: str = Query(None),
    tier: int = Query(None, ge=1, le=4),
    limit: int = Query(50, le=100, ge=1),
    key_data: dict = Depends(_auth),
):
    results = queries.get_project_briefs_list(domain=domain, tier=tier, limit=limit)
    return _ok(results, count=len(results), query_params={"domain": domain, "tier": tier, "limit": limit})


@router.get("/projects/{slug}/brief")
async def project_brief(slug: str, request: Request, key_data: dict = Depends(_auth)):
    result = queries.get_project_brief(slug)
    if not result:
        _not_found(f"Brief for project '{slug}'")
    return _ok(result)


@router.get("/domains/{domain}/brief")
async def domain_brief(domain: str, request: Request, key_data: dict = Depends(_auth)):
    result = queries.get_domain_brief(domain)
    if not result:
        _not_found(f"Brief for domain '{domain}'")
    return _ok(result)


@router.get("/projects/{slug}")
async def project_detail(slug: str, request: Request, key_data: dict = Depends(_auth)):
    result = queries.get_project(slug)
    if not result:
        _not_found(f"Project '{slug}'")
    return _ok(result)


@router.get("/projects")
async def project_search(
    request: Request,
    q: str = Query(None),
    category: str = Query(None),
    stack_layer: str = Query(None, pattern="^(model|inference|orchestration|data|eval|interface|infra)$"),
    domain: str = Query(None),
    limit: int = Query(20, le=50, ge=1),
    key_data: dict = Depends(_auth),
):
    results = queries.search_projects(q=q, category=category, stack_layer=stack_layer, domain=domain, limit=limit)
    return _ok(results, count=len(results), query_params={"q": q, "category": category, "stack_layer": stack_layer, "domain": domain, "limit": limit})


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


@router.get("/velocity")
async def velocity(
    request: Request,
    category: str = Query(None),
    stack_layer: str = Query(None, pattern="^(model|inference|orchestration|data|eval|interface|infra)$"),
    domain: str = Query(None),
    band: str = Query(None, pattern="^(dormant|slow|moderate|fast|hyperspeed)$"),
    sort: str = Query("commits_30d", pattern="^(commits_30d|commits_delta|cpc)$"),
    limit: int = Query(20, le=50, ge=1),
    key_data: dict = Depends(_auth),
):
    results = queries.get_velocity(category=category, stack_layer=stack_layer, domain=domain, band=band, sort=sort, limit=limit)
    return _ok(results, count=len(results), query_params={"category": category, "stack_layer": stack_layer, "domain": domain, "band": band, "sort": sort, "limit": limit})


@router.get("/contributors/trending")
async def contributors_trending(
    request: Request,
    stack_layer: str = Query(None, pattern="^(model|inference|orchestration|data|eval|interface|infra)$"),
    limit: int = Query(20, le=50, ge=1),
    key_data: dict = Depends(_auth),
):
    results = queries.get_contributor_trending(stack_layer=stack_layer, limit=limit)
    return _ok(results, count=len(results), query_params={"stack_layer": stack_layer, "limit": limit})


@router.get("/transitions")
async def transitions(
    request: Request,
    days: int = Query(30, le=90, ge=1),
    key_data: dict = Depends(_auth),
):
    results = queries.get_transitions(days=days)
    return _ok(results, count=len(results), query_params={"days": days})


@router.get("/whats-new")
async def whats_new(
    request: Request,
    days: int = Query(7, le=30, ge=1),
    key_data: dict = Depends(_auth),
):
    result = queries.get_whats_new(days=days)
    return _ok(result, query_params={"days": days})


@router.get("/labs/{slug}")
async def lab_detail(slug: str, request: Request, key_data: dict = Depends(_auth)):
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
    key_data: dict = Depends(_auth),
):
    results = queries.get_hn_posts(q=q, days=days, limit=limit)
    return _ok(results, count=len(results), query_params={"q": q, "days": days, "limit": limit})


@router.get("/briefings")
async def briefings_list(
    request: Request,
    domain: str = Query(None),
    key_data: dict = Depends(_auth),
):
    results = queries.get_briefings(domain=domain)
    return _ok(results, count=len(results), query_params={"domain": domain})


@router.get("/dependencies/trending")
async def dependency_trending(
    request: Request,
    source: str = Query(None, pattern="^(pypi|npm)$"),
    limit: int = Query(20, le=50, ge=1),
    min_dependents: int = Query(3, ge=1),
    key_data: dict = Depends(_auth),
):
    results = queries.get_dep_trending(source=source, limit=limit, min_dependents=min_dependents)
    return _ok(results, count=len(results), query_params={"source": source, "limit": limit, "min_dependents": min_dependents})


@router.get("/dependencies/{package_name}/dependents")
async def dependency_dependents(
    package_name: str,
    request: Request,
    source: str = Query(None, pattern="^(pypi|npm)$"),
    include_dev: bool = Query(False),
    limit: int = Query(20, le=50, ge=1),
    key_data: dict = Depends(_auth),
):
    result = queries.get_dependents(package_name=package_name, source=source, include_dev=include_dev, limit=limit)
    return _ok(result, count=len(result["dependents"]), query_params={"package_name": package_name, "source": source, "include_dev": include_dev, "limit": limit})


@router.get("/commercial-projects")
async def commercial_projects(
    request: Request,
    category: str = Query(None),
    limit: int = Query(20, le=50, ge=1),
    key_data: dict = Depends(_auth),
):
    results = queries.get_commercial_projects(category=category, limit=limit)
    return _ok(results, count=len(results), query_params={"category": category, "limit": limit})


@router.get("/briefings/{slug}")
async def briefing_detail(slug: str, request: Request, key_data: dict = Depends(_auth)):
    result = queries.get_briefing(slug)
    if not result:
        _not_found(f"Briefing '{slug}'")
    return _ok(result)


@router.get("/methodology")
async def methodology_list(
    request: Request,
    category: str = Query(None, pattern="^(metric|tool|algorithm|design)$"),
    key_data: dict = Depends(_auth),
):
    results = queries.get_methodology_list(category=category)
    return _ok(results, count=len(results), query_params={"category": category})


@router.get("/methodology/{topic}")
async def methodology_detail(topic: str, request: Request, key_data: dict = Depends(_auth)):
    result = queries.get_methodology_detail(topic)
    if not result:
        _not_found(f"Methodology topic '{topic}'")
    return _ok(result)


@router.get("/papers")
async def papers_list(
    request: Request,
    q: str = Query(None),
    project: str = Query(None),
    year: int = Query(None),
    limit: int = Query(20, le=50, ge=1),
    key_data: dict = Depends(_auth),
):
    results = queries.get_papers(q=q, project_slug=project, year=year, limit=limit)
    return _ok(results, count=len(results), query_params={"q": q, "project": project, "year": year, "limit": limit})


# ---------------------------------------------------------------------------
# Public dataset endpoints (no auth required)
# ---------------------------------------------------------------------------

@router.get("/datasets/projects")
async def dataset_projects(
    response: Response,
    category: str = Query(None),
    domain: str = Query(None),
    tier: int = Query(None, ge=1, le=4),
    lifecycle_stage: str = Query(None),
    limit: int = Query(500, le=2000, ge=1),
    offset: int = Query(0, ge=0),
):
    results = queries.get_dataset_projects(
        category=category, domain=domain, tier=tier,
        lifecycle_stage=lifecycle_stage, limit=limit, offset=offset,
    )
    response.headers["Cache-Control"] = "public, max-age=3600"
    return _ok(results, count=len(results), query_params={
        "category": category, "domain": domain, "tier": tier,
        "lifecycle_stage": lifecycle_stage, "limit": limit, "offset": offset,
    })


@router.get("/datasets/mcp-repos")
async def dataset_mcp_repos(
    response: Response,
    subcategory: str = Query(None),
    include_archived: bool = Query(False),
    limit: int = Query(500, le=2000, ge=1),
    offset: int = Query(0, ge=0),
):
    results = queries.get_dataset_mcp_repos(
        subcategory=subcategory, include_archived=include_archived,
        limit=limit, offset=offset,
    )
    response.headers["Cache-Control"] = "public, max-age=3600"
    return _ok(results, count=len(results), query_params={
        "subcategory": subcategory, "include_archived": include_archived,
        "limit": limit, "offset": offset,
    })


@router.get("/datasets/mcp-scores")
async def dataset_mcp_scores(
    response: Response,
    quality_tier: str = Query(None, pattern="^(verified|established|emerging|experimental)$"),
    subcategory: str = Query(None),
    limit: int = Query(500, le=2000, ge=1),
    offset: int = Query(0, ge=0),
):
    results = queries.get_mcp_quality_scores(
        quality_tier=quality_tier, subcategory=subcategory,
        limit=limit, offset=offset,
    )
    response.headers["Cache-Control"] = "public, max-age=3600"
    return _ok(results, count=len(results), query_params={
        "quality_tier": quality_tier, "subcategory": subcategory,
        "limit": limit, "offset": offset,
    })


# ---------------------------------------------------------------------------
# MCP quality endpoints (auth required)
# ---------------------------------------------------------------------------

@router.get("/mcp/scores")
async def mcp_scores(
    request: Request,
    quality_tier: str = Query(None, pattern="^(verified|established|emerging|experimental)$"),
    subcategory: str = Query(None),
    min_score: int = Query(None, ge=0, le=100),
    limit: int = Query(50, le=200, ge=1),
    offset: int = Query(0, ge=0),
    key_data: dict = Depends(_auth),
):
    results = queries.get_mcp_quality_scores(
        quality_tier=quality_tier, subcategory=subcategory,
        min_score=min_score, limit=limit, offset=offset,
    )
    return _ok(results, count=len(results), query_params={
        "quality_tier": quality_tier, "subcategory": subcategory,
        "min_score": min_score, "limit": limit, "offset": offset,
    })


@router.get("/mcp/health/{repo:path}")
async def mcp_health(
    repo: str,
    request: Request,
    key_data: dict = Depends(_auth),
):
    result = queries.get_mcp_quality_by_repo(repo)
    if not result:
        _not_found(f"MCP repo '{repo}'")
    return _ok(result)


# ---------------------------------------------------------------------------
# Generic quality endpoints (all 18 domains)
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
        _not_found(f"Repo '{repo}' in domain '{domain}'")
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
