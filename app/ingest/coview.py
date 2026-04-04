"""ETL: Extract co-view pairs from Umami session data.

Queries the Umami Postgres database for recent pageview events, stitches
them into synthetic sessions (same fingerprint, <5 min gap), and extracts
(project_A, project_B) pairs from sessions with 2+ project page views.

Pairs are upserted into coview_pairs in the PT-Edge database, incrementing
coview_count on each occurrence. Used for future "people also viewed"
recommendations on server detail pages.
"""

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from app.db import engine as pt_engine
from app.settings import settings

logger = logging.getLogger(__name__)

# Extract owner/repo from URL paths like /agents/servers/owner/repo/
_SERVER_PATH_RE = re.compile(
    r"^(?:/[\w-]+)?/servers/([\w.-]+/[\w._-]+)/?$"
)

# Map URL prefixes to domains
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
    ("perception", "/perception/"),
]


def _parse_server_path(path: str) -> tuple[str | None, str | None]:
    """Extract (domain, full_name) from a server detail page URL path."""
    m = _SERVER_PATH_RE.match(path)
    if not m:
        return None, None
    full_name = m.group(1)
    for domain, prefix in _DOMAIN_PREFIXES:
        if path.startswith(prefix):
            return domain, full_name
    # Root paths belong to MCP
    if path.startswith("/servers/"):
        return "mcp", full_name
    return None, full_name


async def ingest_coview() -> dict:
    """Extract co-view pairs from Umami and upsert into PT-Edge."""
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
        website_filter = "AND s.website_id = :website_id"
        params["website_id"] = settings.UMAMI_WEBSITE_ID

    try:
        # Fetch last 24h of pageview events with session fingerprint
        with umami_engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT
                    s.country, s.browser, s.os, s.device,
                    we.url_path,
                    we.created_at
                FROM website_event we
                JOIN session s ON we.session_id = s.session_id
                WHERE we.created_at >= NOW() - INTERVAL '25 hours'
                  AND we.event_type = 1
                  AND we.url_path LIKE '%%/servers/%%'
                  {website_filter}
                ORDER BY s.country, s.browser, s.os, s.device, we.created_at
            """), params).fetchall()
    finally:
        umami_engine.dispose()

    if not rows:
        return {"pairs": 0, "sessions": 0}

    # Stitch into synthetic sessions: same fingerprint, <5 min gap
    sessions: list[list[tuple[str, str]]] = []  # list of [(domain, full_name), ...]
    current_session: list[tuple[str, str]] = []
    prev_fingerprint = None
    prev_time = None

    for row in rows:
        fingerprint = (row.country, row.browser, row.os, row.device)
        domain, full_name = _parse_server_path(row.url_path)
        if not full_name:
            continue

        # New session if fingerprint changed or gap > 5 min
        if fingerprint != prev_fingerprint or (
            prev_time and (row.created_at - prev_time).total_seconds() > 300
        ):
            if len(current_session) >= 2:
                sessions.append(current_session)
            current_session = []

        current_session.append((domain or "unknown", full_name))
        prev_fingerprint = fingerprint
        prev_time = row.created_at

    # Don't forget the last session
    if len(current_session) >= 2:
        sessions.append(current_session)

    # Filter out likely bots (sessions with 20+ pages)
    sessions = [s for s in sessions if len(s) <= 20]

    # Extract unique co-view pairs per session
    pair_counts: dict[tuple[str, str, str], int] = {}  # (a, b, domain) -> count
    for session in sessions:
        seen_pairs: set[tuple[str, str]] = set()
        for i in range(len(session)):
            for j in range(i + 1, len(session)):
                domain_a, name_a = session[i]
                domain_b, name_b = session[j]
                # Only pair within same domain
                if domain_a != domain_b:
                    continue
                # Canonical order to avoid duplicates
                a, b = sorted([name_a, name_b])
                if (a, b) not in seen_pairs:
                    seen_pairs.add((a, b))
                    key = (a, b, domain_a)
                    pair_counts[key] = pair_counts.get(key, 0) + 1

    if not pair_counts:
        return {"pairs": 0, "sessions": len(sessions)}

    # Upsert into PT-Edge database
    records = [
        {"a": a, "b": b, "domain": d, "count": c}
        for (a, b, d), c in pair_counts.items()
    ]

    with pt_engine.begin() as conn:
        for rec in records:
            conn.execute(text("""
                INSERT INTO coview_pairs (full_name_a, full_name_b, domain, coview_count, last_seen_at)
                VALUES (:a, :b, :domain, :count, NOW())
                ON CONFLICT (full_name_a, full_name_b) DO UPDATE SET
                    coview_count = coview_pairs.coview_count + :count,
                    last_seen_at = NOW()
            """), rec)

    logger.info(f"Co-view collection: {len(records)} pairs from {len(sessions)} sessions")
    return {"pairs": len(records), "sessions": len(sessions)}
