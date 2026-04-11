"""Shared query layer for REST, MCP, and CLI transports.

Every transport (REST API, MCP server, CLI) calls these functions.
No duplicated query logic — one place for validation, timeouts, and auth.
"""

import json
import logging
import re
from datetime import date, datetime, timezone
from math import log10

from sqlalchemy import text

from app.db import engine, readonly_engine

logger = logging.getLogger(__name__)

# Tables excluded from schema discovery (internal bookkeeping)
_EXCLUDE_TABLES = frozenset({
    "pg_stat_statements", "pg_stat_statements_info",
    "alembic_version", "sync_log",
})

# SQL validation: forbidden keywords and Postgres admin functions
_FORBIDDEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE"
    r"|COPY|DO|CALL|EXECUTE"
    r"|pg_read_file|pg_write_file|pg_read_binary_file"
    r"|lo_import|lo_export|lo_get|lo_put"
    r"|set_config|pg_reload_conf|pg_terminate_backend)\b",
    re.IGNORECASE,
)

ROW_LIMIT = 1000
QUERY_TIMEOUT_MS = 5000


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _serialize(obj):
    """Convert non-JSON-serializable types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if hasattr(obj, "__float__"):
        return float(obj)
    return str(obj)


def _row_to_dict(row):
    """Convert a SQLAlchemy Row to a dict with serialized values."""
    d = dict(row._mapping)
    return {k: _serialize(v) if v is not None else None for k, v in d.items()}


# ---------------------------------------------------------------------------
# SQL validation
# ---------------------------------------------------------------------------

def validate_sql(sql: str) -> str | None:
    """Validate a SQL string for read-only execution.

    Returns None if valid, or an error message string if invalid.
    """
    sql_stripped = sql.strip()

    # Block semicolons (no stacked queries)
    if ";" in sql_stripped.rstrip(";"):
        return "Multiple statements not allowed."
    sql_stripped = sql_stripped.rstrip(";").strip()

    # Strip SQL comments before validation to prevent obfuscation
    sql_clean = re.sub(r"/\*.*?\*/", " ", sql_stripped, flags=re.DOTALL)
    sql_clean = re.sub(r"--[^\n]*", " ", sql_clean)

    # Must start with SELECT (or WITH for CTEs)
    if not re.match(r"(?i)^\s*(SELECT|WITH)\b", sql_clean):
        return "Only SELECT queries are allowed."

    if _FORBIDDEN_RE.search(sql_clean):
        return "Query contains forbidden keywords."

    return None


# ---------------------------------------------------------------------------
# Core functions — called by all transports
# ---------------------------------------------------------------------------

async def list_tables() -> list[dict]:
    """List all public tables with column count and row estimate."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT c.table_name,
                   COUNT(*) AS column_count,
                   s.n_live_tup AS row_estimate
            FROM information_schema.columns c
            LEFT JOIN pg_stat_user_tables s
                   ON s.relname = c.table_name
            WHERE c.table_schema = 'public'
            GROUP BY c.table_name, s.n_live_tup
            ORDER BY c.table_name
        """)).fetchall()

    return [
        {
            "table_name": r._mapping["table_name"],
            "column_count": r._mapping["column_count"],
            "row_estimate": r._mapping["row_estimate"] or 0,
        }
        for r in rows
        if r._mapping["table_name"] not in _EXCLUDE_TABLES
    ]


async def describe_table(table_name: str) -> dict | None:
    """Return column metadata for a single table. None if table not found."""
    # Prevent SQL injection — only allow word chars
    if not re.match(r"^\w+$", table_name):
        return None

    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT column_name, data_type, is_nullable, udt_name,
                   column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :tname
            ORDER BY ordinal_position
        """), {"tname": table_name}).fetchall()

    if not rows:
        return None

    columns = []
    for r in rows:
        m = r._mapping
        dtype = m["data_type"]
        if dtype == "USER-DEFINED" and m.get("udt_name") == "vector":
            dtype = "vector"
        columns.append({
            "name": m["column_name"],
            "type": dtype,
            "nullable": m["is_nullable"] == "YES",
        })

    # Row count estimate
    with readonly_engine.connect() as conn:
        est = conn.execute(text(
            "SELECT n_live_tup FROM pg_stat_user_tables WHERE relname = :t"
        ), {"t": table_name}).scalar()

    return {
        "table_name": table_name,
        "columns": columns,
        "row_estimate": est or 0,
    }


async def search_tables(keyword: str) -> list[dict]:
    """Find tables whose name or columns match a keyword."""
    kw = f"%{keyword.strip().lower()[:100]}%"
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT c.table_name
            FROM information_schema.columns c
            WHERE c.table_schema = 'public'
              AND (LOWER(c.table_name) LIKE :kw
                   OR LOWER(c.column_name) LIKE :kw)
            ORDER BY c.table_name
        """), {"kw": kw}).fetchall()

    results = []
    for r in rows:
        tname = r._mapping["table_name"]
        if tname not in _EXCLUDE_TABLES:
            results.append({"table_name": tname})
    return results


async def run_query(sql: str) -> dict:
    """Execute a read-only SQL query with validation and timeout.

    Returns {"rows": [...], "count": N} on success,
    or {"error": "..."} on failure.
    """
    error = validate_sql(sql)
    if error:
        return {"error": error}

    sql_stripped = sql.strip().rstrip(";").strip()

    try:
        with readonly_engine.connect() as conn:
            conn.execute(text(f"SET LOCAL statement_timeout = '{QUERY_TIMEOUT_MS}'"))
            result = conn.execute(text(sql_stripped))
            rows = [_row_to_dict(r) for r in result.fetchmany(ROW_LIMIT)]
            return {"rows": rows, "count": len(rows)}
    except Exception as e:
        err = str(e)[:1000]
        if "canceling statement" in err:
            return {"error": "Query timed out (5 second limit)."}
        return {"error": err}


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
            "embeddings, and domain classifications. Use run_query() for SQL, or "
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


async def submit_feedback(
    topic: str,
    text_body: str,
    context: str | None = None,
    category: str = "observation",
) -> dict:
    """Submit feedback (bug, feature, observation, insight). Returns the new ID."""
    if len(topic) > 300:
        return {"error": "Topic must be 300 characters or fewer."}
    if len(text_body) > 5000:
        return {"error": "Text must be 5,000 characters or fewer."}
    if context and len(context) > 2000:
        return {"error": "Context must be 2,000 characters or fewer."}

    valid_categories = {"bug", "feature", "observation", "insight"}
    if category not in valid_categories:
        return {"error": f"Invalid category '{category}'. Must be one of: {', '.join(sorted(valid_categories))}"}

    with engine.connect() as conn:
        row = conn.execute(text("""
            INSERT INTO corrections (topic, correction, context, category, status, votes)
            VALUES (:topic, :correction, :context, :category, 'active', 0)
            RETURNING id
        """), {
            "topic": topic,
            "correction": text_body,
            "context": context,
            "category": category,
        }).fetchone()
        conn.commit()

    return {"id": row._mapping["id"], "status": "submitted"}


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
