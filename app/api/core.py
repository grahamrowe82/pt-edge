"""Shared query layer for REST, MCP, and CLI transports.

Generic functions live in app.core.api.core. Domain-specific functions
(search_similar, get_status, list_workflows) live here.
"""

import logging
import re
from math import log10

from sqlalchemy import text

from app.db import engine, readonly_engine

# Re-export generic functions from core
from app.core.api.core import (  # noqa: F401
    validate_sql,
    list_tables,
    describe_table,
    search_tables,
    run_query,
    submit_feedback,
    _serialize,
    _row_to_dict,
    _EXCLUDE_TABLES,
    _FORBIDDEN_RE,
    ROW_LIMIT,
    QUERY_TIMEOUT_MS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain-specific functions (PT-Edge only)
# ---------------------------------------------------------------------------

async def get_status() -> dict:
    """Orientation: table count, key stats, freshness, available domains."""
    with readonly_engine.connect() as conn:
        table_count = conn.execute(text(
            "SELECT COUNT(DISTINCT table_name) FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        )).scalar() or 0

        repo_count = conn.execute(text(
            "SELECT COUNT(*) FROM ai_repos WHERE archived = false"
        )).scalar() or 0

        domain_rows = conn.execute(text(
            "SELECT domain, COUNT(*) AS cnt FROM ai_repos "
            "WHERE archived = false AND domain IS NOT NULL "
            "GROUP BY domain ORDER BY cnt DESC"
        )).fetchall()

        # Latest sync
        latest_sync = conn.execute(text(
            "SELECT sync_type, finished_at FROM sync_log "
            "ORDER BY finished_at DESC LIMIT 1"
        )).fetchone()

    domains = [
        {"name": r._mapping["domain"], "count": r._mapping["cnt"]}
        for r in domain_rows
    ]

    status = {
        "tables": table_count,
        "ai_repos": repo_count,
        "domains": domains,
        "guidance": (
            "Use list_tables() to see all tables, describe_table(name) for columns. "
            "The ai_repos table is the main index — 220K+ repos with stars, quality scores, "
            "embeddings, and domain classifications. Use query() for SQL, or "
            "list_workflows() for pre-built query recipes."
        ),
    }
    if latest_sync:
        m = latest_sync._mapping
        status["last_sync"] = {
            "type": m["sync_type"],
            "at": _serialize(m["finished_at"]),
        }
    return status


async def list_workflows() -> list[dict]:
    """List available SQL recipe workflows from the sql_recipes table."""
    try:
        with readonly_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, name, description, category, sql_template, parameters
                FROM sql_recipes
                ORDER BY category, name
            """)).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception:
        # Table may not exist yet
        return []


async def search_similar(
    query: str,
    domain: str = "",
    limit: int = 5,
    offset: int = 0,
) -> dict:
    """Semantic + keyword search across ai_repos. Returns structured results.

    Used by find_ai_tool, find_mcp_server, and CLI search.
    """
    if not query or len(query) > 500:
        return {"error": "Please provide a search query (max 500 characters)."}

    limit = min(max(1, limit), 20)
    offset = min(max(0, offset), 100)
    domain = domain.strip().lower()

    from app.embeddings import is_enabled, embed_one

    AI_REPO_EMBED_DIM = 256
    seen_ids: set[int] = set()
    results: list[dict] = []
    domain_filter = "AND domain = :domain" if domain else ""
    params_base: dict = {"domain": domain} if domain else {}

    try:
        # ---- Semantic search ----
        if is_enabled():
            vec = await embed_one(query, dimensions=AI_REPO_EMBED_DIM)
            if vec:
                with readonly_engine.connect() as conn:
                    rows = conn.execute(text(f"""
                        SELECT id, full_name, name, description, stars, forks,
                               language, topics, license, archived, domain,
                               subcategory, downloads_monthly, last_pushed_at,
                               1 - (embedding <=> :vec) AS similarity
                        FROM ai_repos
                        WHERE embedding IS NOT NULL AND archived = false
                        {domain_filter}
                        ORDER BY embedding <=> :vec
                        LIMIT :lim
                    """), {**params_base, "vec": str(vec), "lim": (offset + limit) * 3}).fetchall()

                    for r in rows:
                        m = r._mapping
                        results.append(_repo_result(m))
                        seen_ids.add(m["id"])

        # ---- Keyword fallback ----
        keyword = f"%{query.strip()[:100]}%"
        with readonly_engine.connect() as conn:
            kw_rows = conn.execute(text(f"""
                SELECT id, full_name, name, description, stars, forks,
                       language, topics, license, domain, subcategory,
                       downloads_monthly, last_pushed_at
                FROM ai_repos
                WHERE archived = false
                  AND (name ILIKE :kw OR description ILIKE :kw
                       OR full_name ILIKE :kw)
                  {domain_filter}
                ORDER BY stars DESC
                LIMIT :lim
            """), {**params_base, "kw": keyword, "lim": offset + limit}).fetchall()

            for r in kw_rows:
                m = r._mapping
                if m["id"] not in seen_ids:
                    result = _repo_result(m)
                    result["similarity"] = 0.5  # keyword match baseline
                    results.append(result)
                    seen_ids.add(m["id"])

        if not results:
            scope = f" in domain '{domain}'" if domain else ""
            return {"results": [], "query": query, "message": f"No results for '{query}'{scope}."}

        # ---- Rank: blend similarity, stars, downloads, name match ----
        for r in results:
            star_score = log10(max(r["stars"], 1) + 1) / 5.0
            dl = r.get("downloads_monthly") or 0
            download_score = log10(max(dl, 1) + 1) / 7.0
            nb = _name_boost(query, r["name"], r["full_name"])
            r["score"] = 0.6 * r["similarity"] + 0.2 * star_score + 0.2 * download_score + nb

        # Filter low-quality
        results = [r for r in results if r["similarity"] >= 0.3 or _name_boost(query, r["name"], r["full_name"]) > 0]
        results.sort(key=lambda x: x["score"], reverse=True)
        page = results[offset:offset + limit]

        return {"results": page, "query": query, "total_candidates": len(results)}

    except Exception as e:
        logger.exception(f"search_similar failed: {e}")
        return {"error": "Search failed. Please try again."}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _repo_result(m) -> dict:
    """Build a standardised repo result dict from a row mapping."""
    return {
        "id": m["id"],
        "full_name": m["full_name"],
        "name": m["name"],
        "description": m.get("description"),
        "stars": m["stars"],
        "forks": m.get("forks", 0),
        "language": m.get("language"),
        "topics": list(m["topics"]) if m.get("topics") else [],
        "license": None if m.get("license") == "NOASSERTION" else m.get("license"),
        "domain": m.get("domain"),
        "subcategory": m.get("subcategory"),
        "downloads_monthly": m.get("downloads_monthly") or 0,
        "last_pushed_at": _serialize(m["last_pushed_at"]) if m.get("last_pushed_at") else None,
        "similarity": float(m["similarity"]) if "similarity" in dict(m) else 0.0,
    }


def _name_boost(
    query: str, *fields: str,
    exact_bonus: float = 0.15, partial_bonus: float = 0.08,
) -> float:
    """Score boost when query matches a name/title field."""
    q = query.strip().lower()
    if not q:
        return 0.0
    for f in fields:
        fl = (f or "").lower()
        if q == fl or fl.endswith(f"/{q}"):
            return exact_bonus
    for f in fields:
        if q in (f or "").lower():
            return partial_bonus
    return 0.0
