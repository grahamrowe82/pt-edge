"""Demand Radar compute handlers.

Coarse-grained COMPUTE tasks (db_only) that aggregate access log
signals into snapshot tables for ML training data.
"""
import logging
from datetime import datetime, timezone

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
