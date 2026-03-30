"""ETL: Pull aggregated page stats from Umami analytics DB into PT-Edge.

Queries the Umami Postgres database (separate instance), maps URL paths to
(domain, subcategory) pairs, and upserts daily aggregates into umami_page_stats.
Runs as part of the daily ingest pipeline, before materialized view refresh.
"""

import logging
import re
from datetime import date, timedelta

from sqlalchemy import create_engine, text

from app.db import engine as pt_engine
from app.settings import settings

logger = logging.getLogger(__name__)

# URL path -> domain mapping (MCP is at root, others at /{domain}/)
_DOMAIN_PREFIXES = [
    ("agents", "/agents/"),
    ("rag", "/rag/"),
    ("ai-coding", "/ai-coding/"),
    ("voice-ai", "/voice-ai/"),
    ("diffusion", "/diffusion/"),
    ("vector-db", "/vector-db/"),
    ("embeddings", "/embeddings/"),
    ("prompt-engineering", "/prompt-engineering/"),
    ("ml-frameworks", "/ml-frameworks/"),
    ("llm-tools", "/llm-tools/"),
    ("nlp", "/nlp/"),
    ("transformers", "/transformers/"),
    ("generative-ai", "/generative-ai/"),
    ("computer-vision", "/computer-vision/"),
    ("data-engineering", "/data-engineering/"),
    ("mlops", "/mlops/"),
]

# Match /categories/SUBCATEGORY/ or /{domain}/categories/SUBCATEGORY/
_CATEGORY_RE = re.compile(r"^(?:/[\w-]+)?/categories/([\w-]+)/?$")

# Match /servers/OWNER/REPO/ — used for domain-level aggregation
_SERVER_RE = re.compile(r"^(?:/[\w-]+)?/servers/")


def _path_to_domain(path: str) -> str | None:
    """Map a URL path to its domain. Returns None for non-directory pages."""
    for domain, prefix in _DOMAIN_PREFIXES:
        if path.startswith(prefix):
            return domain
    # Root paths (/, /categories/*, /servers/*) belong to MCP
    if path == "/" or path.startswith("/categories/") or path.startswith("/servers/"):
        return "mcp"
    return None


def _path_to_subcategory(path: str) -> str | None:
    """Extract subcategory from a category page path."""
    m = _CATEGORY_RE.match(path)
    return m.group(1) if m else None


async def ingest_umami() -> dict:
    """Pull 7-day page stats from Umami and upsert into PT-Edge."""
    if not settings.UMAMI_DATABASE_URL:
        return "skipped (no UMAMI_DATABASE_URL)"

    umami_engine = create_engine(
        settings.UMAMI_DATABASE_URL,
        connect_args={"sslmode": "require"},
        pool_pre_ping=True,
    )

    website_filter = ""
    params: dict = {}
    if settings.UMAMI_WEBSITE_ID:
        website_filter = "AND we.website_id = :website_id"
        params["website_id"] = settings.UMAMI_WEBSITE_ID

    try:
        with umami_engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT
                    we.url_path,
                    COUNT(*) AS pageviews,
                    COUNT(DISTINCT we.session_id) AS unique_sessions
                FROM website_event we
                WHERE we.created_at >= NOW() - INTERVAL '7 days'
                  AND we.event_type = 1
                  {website_filter}
                GROUP BY we.url_path
                HAVING COUNT(*) >= 1
            """), params).fetchall()
    finally:
        umami_engine.dispose()

    # Aggregate by (domain, subcategory, date=today)
    # For now we store a single rolling 7d aggregate per day
    today = date.today()
    aggregates: dict[tuple[str, str | None], dict] = {}

    for row in rows:
        path = row.url_path
        domain = _path_to_domain(path)
        if not domain:
            continue

        subcategory = _path_to_subcategory(path)

        # Aggregate at domain level (subcategory=None) for all pages
        key_domain = (domain, None)
        if key_domain not in aggregates:
            aggregates[key_domain] = {"pageviews": 0, "sessions": 0}
        aggregates[key_domain]["pageviews"] += row.pageviews
        aggregates[key_domain]["sessions"] += row.unique_sessions

        # Also aggregate at subcategory level for category pages
        if subcategory:
            key_cat = (domain, subcategory)
            if key_cat not in aggregates:
                aggregates[key_cat] = {"pageviews": 0, "sessions": 0}
            aggregates[key_cat]["pageviews"] += row.pageviews
            aggregates[key_cat]["sessions"] += row.unique_sessions

    # Upsert into PT-Edge
    upserted = 0
    with pt_engine.connect() as conn:
        for (domain, subcategory), stats in aggregates.items():
            conn.execute(text("""
                INSERT INTO umami_page_stats
                    (domain, subcategory, stat_date, pageviews, unique_sessions)
                VALUES (:domain, :subcategory, :stat_date, :pageviews, :sessions)
                ON CONFLICT (domain, COALESCE(subcategory, ''), stat_date)
                DO UPDATE SET
                    pageviews = EXCLUDED.pageviews,
                    unique_sessions = EXCLUDED.unique_sessions
            """), {
                "domain": domain,
                "subcategory": subcategory,
                "stat_date": today,
                "pageviews": stats["pageviews"],
                "sessions": stats["sessions"],
            })
            upserted += 1
        conn.commit()

    logger.info(f"Umami ETL: {len(rows)} paths -> {upserted} category aggregates")
    return {"paths_fetched": len(rows), "categories_upserted": upserted}
