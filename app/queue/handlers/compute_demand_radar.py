"""Demand Radar compute handlers.

Coarse-grained COMPUTE tasks (db_only) that aggregate access log
signals into snapshot tables for ML training data.
"""
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import engine
from app.db import SessionLocal
from app.models import SyncLog

logger = logging.getLogger(__name__)

# Domain extraction from URL path — same logic as mv_allocation_scores
_PATH_DOMAIN_CASE = """
    CASE
        WHEN path LIKE '%/agents/%' THEN 'agents'
        WHEN path LIKE '%/rag/%' THEN 'rag'
        WHEN path LIKE '%/ai-coding/%' THEN 'ai-coding'
        WHEN path LIKE '%/voice-ai/%' THEN 'voice-ai'
        WHEN path LIKE '%/diffusion/%' THEN 'diffusion'
        WHEN path LIKE '%/vector-db/%' THEN 'vector-db'
        WHEN path LIKE '%/embeddings/%' THEN 'embeddings'
        WHEN path LIKE '%/prompt-engineering/%' THEN 'prompt-engineering'
        WHEN path LIKE '%/ml-frameworks/%' THEN 'ml-frameworks'
        WHEN path LIKE '%/llm-tools/%' THEN 'llm-tools'
        WHEN path LIKE '%/nlp/%' THEN 'nlp'
        WHEN path LIKE '%/transformers/%' THEN 'transformers'
        WHEN path LIKE '%/generative-ai/%' THEN 'generative-ai'
        WHEN path LIKE '%/computer-vision/%' THEN 'computer-vision'
        WHEN path LIKE '%/data-engineering/%' THEN 'data-engineering'
        WHEN path LIKE '%/mlops/%' THEN 'mlops'
        WHEN path LIKE '%/perception/%' THEN 'perception'
        ELSE NULL
    END"""


async def handle_snapshot_bot_activity(task: dict) -> dict:
    """Snapshot yesterday's bot activity from mv_access_bot_demand into
    bot_activity_daily, grouped by (date, domain, subcategory, bot_family).

    Two paths to (domain, subcategory):
    1. Project pages: join path to ai_repos via full_name
    2. Category pages: extract from URL pattern /domain/categories/subcategory/
    """
    started_at = datetime.now(timezone.utc)

    with engine.connect() as conn:
        # Check if yesterday's data already exists
        existing = conn.execute(text("""
            SELECT COUNT(*) FROM bot_activity_daily
            WHERE snapshot_date = CURRENT_DATE - 1
        """)).scalar()

        if existing and existing > 0:
            logger.info(f"bot_activity_daily already has {existing} rows for yesterday, upserting")

        # Aggregate project pages: path → ai_repos → (domain, subcategory)
        result = conn.execute(text("""
            INSERT INTO bot_activity_daily
                (snapshot_date, domain, subcategory, bot_family,
                 hits, unique_pages, unique_ips, revisit_ratio)
            SELECT
                bad.access_date,
                ar.domain,
                ar.subcategory,
                bad.bot_family,
                SUM(bad.hits),
                COUNT(DISTINCT bad.path),
                SUM(bad.unique_ips),
                CASE WHEN COUNT(DISTINCT bad.path) > 0
                     THEN ROUND(SUM(bad.hits)::numeric / COUNT(DISTINCT bad.path), 2)
                END
            FROM mv_access_bot_demand bad
            JOIN ai_repos ar ON bad.path LIKE '%/servers/' || ar.full_name || '/%'
            WHERE bad.access_date = CURRENT_DATE - 1
              AND ar.domain IS NOT NULL AND ar.domain <> 'uncategorized'
              AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
            GROUP BY bad.access_date, ar.domain, ar.subcategory, bad.bot_family
            ON CONFLICT (snapshot_date, domain, subcategory, bot_family)
            DO UPDATE SET
                hits = EXCLUDED.hits,
                unique_pages = EXCLUDED.unique_pages,
                unique_ips = EXCLUDED.unique_ips,
                revisit_ratio = EXCLUDED.revisit_ratio
        """))
        project_rows = result.rowcount
        conn.commit()

        # Aggregate category pages: extract domain+subcategory from URL
        result = conn.execute(text(f"""
            INSERT INTO bot_activity_daily
                (snapshot_date, domain, subcategory, bot_family,
                 hits, unique_pages, unique_ips, revisit_ratio)
            SELECT
                bad.access_date,
                {_PATH_DOMAIN_CASE} AS domain,
                REGEXP_REPLACE(
                    REGEXP_REPLACE(bad.path, '.*/categories/([^/]+)/?$', '\\1'),
                    '^/.*$', NULL
                ) AS subcategory,
                bad.bot_family,
                SUM(bad.hits),
                COUNT(DISTINCT bad.path),
                SUM(bad.unique_ips),
                CASE WHEN COUNT(DISTINCT bad.path) > 0
                     THEN ROUND(SUM(bad.hits)::numeric / COUNT(DISTINCT bad.path), 2)
                END
            FROM mv_access_bot_demand bad
            WHERE bad.access_date = CURRENT_DATE - 1
              AND bad.path LIKE '%/categories/%'
            GROUP BY bad.access_date,
                     {_PATH_DOMAIN_CASE},
                     REGEXP_REPLACE(
                         REGEXP_REPLACE(bad.path, '.*/categories/([^/]+)/?$', '\\1'),
                         '^/.*$', NULL
                     ),
                     bad.bot_family
            HAVING {_PATH_DOMAIN_CASE} IS NOT NULL
               AND REGEXP_REPLACE(
                       REGEXP_REPLACE(bad.path, '.*/categories/([^/]+)/?$', '\\1'),
                       '^/.*$', NULL
                   ) IS NOT NULL
            ON CONFLICT (snapshot_date, domain, subcategory, bot_family)
            DO UPDATE SET
                hits = bot_activity_daily.hits + EXCLUDED.hits,
                unique_pages = bot_activity_daily.unique_pages + EXCLUDED.unique_pages,
                unique_ips = bot_activity_daily.unique_ips + EXCLUDED.unique_ips,
                revisit_ratio = CASE
                    WHEN (bot_activity_daily.unique_pages + EXCLUDED.unique_pages) > 0
                    THEN ROUND(
                        (bot_activity_daily.hits + EXCLUDED.hits)::numeric
                        / (bot_activity_daily.unique_pages + EXCLUDED.unique_pages), 2)
                END
        """))
        category_rows = result.rowcount
        conn.commit()

        # Get final count
        total = conn.execute(text("""
            SELECT COUNT(*) FROM bot_activity_daily
            WHERE snapshot_date = CURRENT_DATE - 1
        """)).scalar()

    # Log to sync_log
    session = SessionLocal()
    try:
        log = SyncLog(
            sync_type="bot_activity_snapshot",
            status="success",
            records_written=total or 0,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        session.add(log)
        session.commit()
    finally:
        session.close()

    logger.info(
        f"Snapshotted bot activity: {project_rows} project rows, "
        f"{category_rows} category rows, {total} total for yesterday"
    )
    return {
        "status": "success",
        "project_rows": project_rows,
        "category_rows": category_rows,
        "total_rows": total,
    }


# Tier 1 AI user-action bot families
_TIER1_FAMILIES = (
    "ChatGPT-User", "Claude-Web", "Perplexity-User",
    "OAI-SearchBot", "Claude-SearchBot", "DuckAssistBot", "Claude-User",
)

# Bot classification CASE — same as migration 083, for Tier 1 only
_TIER1_CASE = """
    CASE
        WHEN user_agent ILIKE '%ChatGPT-User%'    THEN 'ChatGPT-User'
        WHEN user_agent ILIKE '%Claude-Web%'       THEN 'Claude-Web'
        WHEN user_agent ILIKE '%Perplexity-User%'  THEN 'Perplexity-User'
        WHEN user_agent ILIKE '%OAI-SearchBot%'    THEN 'OAI-SearchBot'
        WHEN user_agent ILIKE '%Claude-SearchBot%' THEN 'Claude-SearchBot'
        WHEN user_agent ILIKE '%DuckAssistBot%'    THEN 'DuckAssistBot'
        WHEN user_agent ILIKE '%Claude-User%'      THEN 'Claude-User'
    END"""

# Session gap threshold: requests more than 5 minutes apart = new session
_SESSION_GAP = timedelta(minutes=5)
# Fan-out window: OAI-SearchBot IPs hitting same subcategory within 30 seconds
_FANOUT_WINDOW = timedelta(seconds=30)


def _extract_domain_subcat(path: str) -> tuple[str | None, str | None]:
    """Extract (domain, subcategory) from a URL path."""
    parts = path.strip("/").split("/")
    if len(parts) < 2:
        return None, None
    domain = parts[0]
    # Category page: /domain/categories/subcategory/
    if len(parts) >= 3 and parts[1] == "categories":
        return domain, parts[2]
    # Project page: /domain/servers/owner/repo/
    # Subcategory comes from ai_repos lookup (handled separately)
    return domain, None


def _detect_sessions(requests: list[dict]) -> list[dict]:
    """Detect sessions from sorted Tier 1 bot requests.

    Two passes:
    1. Single-IP sessions: group by (client_ip, bot_family) with 5-min gap
    2. Fan-out merge: for OAI-SearchBot, merge sessions from different IPs
       when they overlap within 30 seconds and share a subcategory
    """
    # Pass 1: single-IP sessions
    raw_sessions = []
    # Group by (ip, bot_family)
    groups = defaultdict(list)
    for req in requests:
        groups[(req["client_ip"], req["bot_family"])].append(req)

    for (ip, bot_family), reqs in groups.items():
        reqs.sort(key=lambda r: r["ts"])
        session_reqs = [reqs[0]]
        for req in reqs[1:]:
            if req["ts"] - session_reqs[-1]["ts"] <= _SESSION_GAP:
                session_reqs.append(req)
            else:
                if len(session_reqs) >= 2:
                    raw_sessions.append({
                        "bot_family": bot_family,
                        "ips": {ip},
                        "reqs": session_reqs,
                        "start": session_reqs[0]["ts"],
                        "end": session_reqs[-1]["ts"],
                    })
                session_reqs = [req]
        if len(session_reqs) >= 2:
            raw_sessions.append({
                "bot_family": bot_family,
                "ips": {ip},
                "reqs": session_reqs,
                "start": session_reqs[0]["ts"],
                "end": session_reqs[-1]["ts"],
            })

    # Pass 2: fan-out merge for OAI-SearchBot
    oai_sessions = [s for s in raw_sessions if s["bot_family"] == "OAI-SearchBot"]
    other_sessions = [s for s in raw_sessions if s["bot_family"] != "OAI-SearchBot"]

    merged = []
    used = set()
    for i, s1 in enumerate(oai_sessions):
        if i in used:
            continue
        cluster = s1
        for j, s2 in enumerate(oai_sessions):
            if j <= i or j in used:
                continue
            # Check temporal overlap within fan-out window
            if (abs((s1["start"] - s2["start"]).total_seconds()) <= _FANOUT_WINDOW.total_seconds()
                    and s1["ips"] != s2["ips"]):
                # Merge: combine requests, IPs, expand time range
                cluster["reqs"].extend(s2["reqs"])
                cluster["ips"] |= s2["ips"]
                cluster["start"] = min(cluster["start"], s2["start"])
                cluster["end"] = max(cluster["end"], s2["end"])
                used.add(j)
        merged.append(cluster)

    all_sessions = other_sessions + merged

    # Build output
    results = []
    for sess in all_sessions:
        paths = [r["path"] for r in sess["reqs"]]
        domains = set()
        subcats = set()
        for r in sess["reqs"]:
            if r.get("domain"):
                domains.add(r["domain"])
            if r.get("subcategory"):
                subcats.add(r["subcategory"])
            d, s = _extract_domain_subcat(r["path"])
            if d:
                domains.add(d)
            if s:
                subcats.add(s)

        domains.discard(None)
        subcats.discard(None)
        domain_list = sorted(domains)
        subcat_list = sorted(subcats)
        duration = int((sess["end"] - sess["start"]).total_seconds())

        results.append({
            "session_date": sess["start"].date(),
            "bot_family": sess["bot_family"],
            "ip_count": len(sess["ips"]),
            "page_count": len(set(paths)),
            "duration_seconds": duration,
            "primary_domain": domain_list[0] if domain_list else None,
            "primary_subcategory": subcat_list[0] if subcat_list else None,
            "domains": domain_list or None,
            "subcategories": subcat_list or None,
            "is_deep_research": len(set(paths)) >= 10,
            "is_comparison": any("/compare/" in p for p in paths),
            "is_fan_out": len(sess["ips"]) > 1,
        })
    return results


async def handle_detect_bot_sessions(task: dict) -> dict:
    """Detect multi-page AI agent sessions from yesterday's raw access logs.

    Queries http_access_log directly (needs individual timestamps + IPs),
    classifies Tier 1 bots, runs session detection with fan-out merging,
    inserts into bot_sessions table.
    """
    started_at = datetime.now(timezone.utc)

    with engine.connect() as conn:
        # Check if sessions already detected for yesterday
        existing = conn.execute(text("""
            SELECT COUNT(*) FROM bot_sessions
            WHERE session_date = CURRENT_DATE - 1
        """)).scalar()
        if existing and existing > 0:
            logger.info(f"bot_sessions already has {existing} rows for yesterday, skipping")
            return {"status": "skipped", "existing_rows": existing}

        # Get yesterday's Tier 1 bot requests with subcategory from ai_repos
        rows = conn.execute(text(f"""
            SELECT
                h.created_at AS ts,
                h.client_ip,
                h.path,
                {_TIER1_CASE} AS bot_family,
                ar.domain,
                ar.subcategory
            FROM http_access_log h
            LEFT JOIN ai_repos ar ON h.path LIKE '%/servers/' || ar.full_name || '/%'
            WHERE h.created_at::date = CURRENT_DATE - 1
              AND h.status_code = 200
              AND ({_TIER1_CASE}) IS NOT NULL
            ORDER BY h.created_at
        """)).fetchall()

    if not rows:
        logger.info("No Tier 1 bot requests found for yesterday")
        return {"status": "no_data", "sessions": 0}

    requests = [
        {"ts": r.ts, "client_ip": r.client_ip, "path": r.path,
         "bot_family": r.bot_family, "domain": r.domain,
         "subcategory": r.subcategory}
        for r in rows
    ]

    sessions = _detect_sessions(requests)

    if sessions:
        with engine.connect() as conn:
            for s in sessions:
                conn.execute(text("""
                    INSERT INTO bot_sessions
                        (session_date, bot_family, ip_count, page_count,
                         duration_seconds, primary_domain, primary_subcategory,
                         domains, subcategories, is_deep_research,
                         is_comparison, is_fan_out)
                    VALUES
                        (:session_date, :bot_family, :ip_count, :page_count,
                         :duration_seconds, :primary_domain, :primary_subcategory,
                         :domains, :subcategories, :is_deep_research,
                         :is_comparison, :is_fan_out)
                """), s)
            conn.commit()

    # Log to sync_log
    session = SessionLocal()
    try:
        log = SyncLog(
            sync_type="bot_sessions",
            status="success",
            records_written=len(sessions),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        session.add(log)
        session.commit()
    finally:
        session.close()

    deep = sum(1 for s in sessions if s["is_deep_research"])
    fanout = sum(1 for s in sessions if s["is_fan_out"])
    logger.info(
        f"Detected {len(sessions)} bot sessions for yesterday "
        f"({deep} deep research, {fanout} fan-out)"
    )
    return {
        "status": "success",
        "sessions": len(sessions),
        "deep_research": deep,
        "fan_out": fanout,
        "total_requests": len(requests),
    }
