"""Thin scheduler: creates tasks based on staleness, never executes them.

Runs periodically (every 15 minutes) as a coroutine inside the worker
process. Queries the database to find work that needs doing, creates
task rows, and lets the worker loop pick them up.

Also handles housekeeping: stale task reaping, budget resets, old task cleanup.
"""
import asyncio
import logging

from sqlalchemy import text

from domains.cyber.app.db import engine

logger = logging.getLogger(__name__)

SCHEDULER_INTERVAL = 900  # 15 minutes

# Minimum row count in cves table before supplementary sources should run.
# Prevents enrichment tasks from running against an empty/bootstrapping DB
# and caching empty results.
_CVE_READINESS_THRESHOLD = 1000


def _cves_ready() -> bool:
    """Check whether the cves table has enough data for enrichment tasks."""
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM cves"
        )).scalar()
    return count >= _CVE_READINESS_THRESHOLD


# ---------------------------------------------------------------------------
# Coarse-grained schedulers (one task per ingest source)
# ---------------------------------------------------------------------------


def schedule_ingest_nvd() -> int:
    """Create ingest_nvd task if not run today."""
    with engine.connect() as conn:
        ran_today = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'nvd'
              AND status IN ('success', 'partial')
              AND started_at::date = CURRENT_DATE
            LIMIT 1
        """)).fetchone()
        if ran_today:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, priority, resource_type)
            VALUES ('ingest_nvd', 9, 'nvd')
            ON CONFLICT (task_type, COALESCE(subject_id, ''))
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled ingest_nvd")
        return count


def schedule_refresh_views() -> int:
    """Create refresh_views task if views are stale.

    Triggers when:
    1. An ingest completed today but views haven't refreshed since, OR
    2. Views haven't been refreshed at all today
    """
    with engine.connect() as conn:
        refreshed_today = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'views'
              AND status = 'success'
              AND started_at::date = CURRENT_DATE
            LIMIT 1
        """)).fetchone()

        if refreshed_today:
            last_ingest = conn.execute(text("""
                SELECT MAX(finished_at) FROM sync_log
                WHERE sync_type IN ('nvd', 'kev', 'epss', 'mitre_cwe', 'mitre_capec', 'mitre_attack', 'osv', 'ghsa', 'exploit_db')
                  AND status IN ('success', 'partial')
                  AND started_at::date = CURRENT_DATE
            """)).scalar()

            if not last_ingest:
                return 0

            views_after_ingest = conn.execute(text("""
                SELECT 1 FROM sync_log
                WHERE sync_type = 'views'
                  AND status = 'success'
                  AND finished_at > :last_ingest
                LIMIT 1
            """), {"last_ingest": last_ingest}).fetchone()

            if views_after_ingest:
                return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, priority, resource_type)
            VALUES ('refresh_views', 8, 'db_only')
            ON CONFLICT (task_type, COALESCE(subject_id, ''))
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled refresh_views")
        return count


def schedule_ingest_kev() -> int:
    """Create ingest_kev task if not run today. Requires CVE data."""
    if not _cves_ready():
        return 0
    with engine.connect() as conn:
        ran_today = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'kev'
              AND status IN ('success', 'partial')
              AND started_at::date = CURRENT_DATE
            LIMIT 1
        """)).fetchone()
        if ran_today:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, priority, resource_type)
            VALUES ('ingest_kev', 8, 'db_only')
            ON CONFLICT (task_type, COALESCE(subject_id, ''))
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled ingest_kev")
        return count


def schedule_ingest_epss() -> int:
    """Create ingest_epss task if not run today. Requires CVE data."""
    if not _cves_ready():
        return 0
    with engine.connect() as conn:
        ran_today = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'epss'
              AND status IN ('success', 'partial')
              AND started_at::date = CURRENT_DATE
            LIMIT 1
        """)).fetchone()
        if ran_today:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, priority, resource_type)
            VALUES ('ingest_epss', 8, 'db_only')
            ON CONFLICT (task_type, COALESCE(subject_id, ''))
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled ingest_epss")
        return count


def schedule_ingest_mitre() -> int:
    """Create ingest_mitre task if not run in the last 7 days.

    MITRE frameworks (CWE, CAPEC, ATT&CK) update quarterly, but we check
    weekly to catch any intermediate releases and keep data fresh.
    """
    with engine.connect() as conn:
        ran_recently = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'mitre_attack'
              AND status IN ('success', 'partial')
              AND started_at > now() - interval '7 days'
            LIMIT 1
        """)).fetchone()
        if ran_recently:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, priority, resource_type)
            VALUES ('ingest_mitre', 7, 'db_only')
            ON CONFLICT (task_type, COALESCE(subject_id, ''))
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled ingest_mitre")
        return count


def schedule_compute_embeddings() -> int:
    """Create compute_embeddings task if not run in last 24 hours and entities need embedding."""
    with engine.connect() as conn:
        recent = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'embed_entities'
              AND status = 'success'
              AND started_at > now() - interval '24 hours'
            LIMIT 1
        """)).fetchone()
        if recent:
            return 0

        # Only schedule if there are entities with NULL embeddings
        has_work = conn.execute(text("""
            SELECT EXISTS(SELECT 1 FROM cves WHERE embedding IS NULL AND cvss_base_score IS NOT NULL LIMIT 1)
                OR EXISTS(SELECT 1 FROM software WHERE embedding IS NULL LIMIT 1)
                OR EXISTS(SELECT 1 FROM vendors WHERE embedding IS NULL LIMIT 1)
                OR EXISTS(SELECT 1 FROM weaknesses WHERE embedding IS NULL LIMIT 1)
                OR EXISTS(SELECT 1 FROM techniques WHERE embedding IS NULL LIMIT 1)
                OR EXISTS(SELECT 1 FROM attack_patterns WHERE embedding IS NULL LIMIT 1)
        """)).scalar()
        if not has_work:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type)
            VALUES ('compute_embeddings', 'all', 6, 'openai')
            ON CONFLICT (task_type, COALESCE(subject_id, ''))
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled compute_embeddings")
        return count


def schedule_ingest_osv() -> int:
    """Create ingest_osv task if not run today. Requires CVE data."""
    if not _cves_ready():
        return 0
    with engine.connect() as conn:
        ran_today = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'osv'
              AND status IN ('success', 'partial')
              AND started_at::date = CURRENT_DATE
            LIMIT 1
        """)).fetchone()
        if ran_today:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, priority, resource_type)
            VALUES ('ingest_osv', 7, 'osv_ghsa')
            ON CONFLICT (task_type, COALESCE(subject_id, ''))
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled ingest_osv")
        return count


def schedule_ingest_ghsa() -> int:
    """Create ingest_ghsa task if not run today. Requires CVE data."""
    if not _cves_ready():
        return 0
    with engine.connect() as conn:
        ran_today = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'ghsa'
              AND status IN ('success', 'partial')
              AND started_at::date = CURRENT_DATE
            LIMIT 1
        """)).fetchone()
        if ran_today:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, priority, resource_type)
            VALUES ('ingest_ghsa', 7, 'osv_ghsa')
            ON CONFLICT (task_type, COALESCE(subject_id, ''))
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled ingest_ghsa")
        return count


def schedule_ingest_exploit_db() -> int:
    """Create ingest_exploit_db task if not run today. Requires CVE data."""
    if not _cves_ready():
        return 0
    with engine.connect() as conn:
        ran_today = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'exploit_db'
              AND status IN ('success', 'partial')
              AND started_at::date = CURRENT_DATE
            LIMIT 1
        """)).fetchone()
        if ran_today:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, priority, resource_type)
            VALUES ('ingest_exploit_db', 7, 'exploit_db')
            ON CONFLICT (task_type, COALESCE(subject_id, ''))
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled ingest_exploit_db")
        return count


def schedule_compute_pairs() -> int:
    """Create compute_pairs task if not run in the last 7 days. Requires CVE data."""
    if not _cves_ready():
        return 0
    with engine.connect() as conn:
        recent = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'compute_pairs'
              AND status = 'success'
              AND started_at > now() - interval '7 days'
            LIMIT 1
        """)).fetchone()
        if recent:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type)
            VALUES ('compute_pairs', 'all', 6, 'db_only')
            ON CONFLICT (task_type, COALESCE(subject_id, ''))
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled compute_pairs")
        return count


def schedule_compute_hypotheses() -> int:
    """Create compute_hypotheses task if not run in the last 7 days. Requires CVE data."""
    if not _cves_ready():
        return 0
    with engine.connect() as conn:
        recent = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'compute_hypotheses'
              AND status = 'success'
              AND started_at > now() - interval '7 days'
            LIMIT 1
        """)).fetchone()
        if recent:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type)
            VALUES ('compute_hypotheses', 'all', 5, 'db_only')
            ON CONFLICT (task_type, COALESCE(subject_id, ''))
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled compute_hypotheses")
        return count


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------


def reap_stale_tasks() -> int:
    """Requeue tasks stuck in 'claimed' state with no heartbeat for >10 minutes."""
    with engine.connect() as conn:
        result = conn.execute(text("""
            UPDATE tasks
            SET state = CASE
                    WHEN retry_count < max_retries THEN 'pending'
                    ELSE 'failed'
                END,
                error_message = 'heartbeat timeout — requeued by scheduler',
                retry_count = CASE
                    WHEN retry_count < max_retries THEN retry_count + 1
                    ELSE retry_count
                END,
                claimed_by = NULL,
                claimed_at = NULL,
                heartbeat_at = NULL,
                completed_at = CASE
                    WHEN retry_count >= max_retries THEN now()
                    ELSE NULL
                END
            WHERE state = 'claimed'
              AND heartbeat_at < now() - interval '10 minutes'
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.warning(f"Reaped {count} stale tasks")
        return count


def reset_expired_budgets() -> int:
    """Reset consumed=0 for budgets whose period has expired."""
    with engine.connect() as conn:
        result = conn.execute(text("""
            UPDATE resource_budgets
            SET consumed = 0,
                period_start = now()
            WHERE reset_mode = 'rolling'
              AND now() >= period_start + (period_hours || ' hours')::interval
              AND consumed > 0
        """))
        rolling = result.rowcount

        result = conn.execute(text("""
            UPDATE resource_budgets
            SET consumed = 0,
                period_start = (
                    date_trunc('day', now() AT TIME ZONE reset_tz)
                    + (reset_hour || ' hours')::interval
                ) AT TIME ZONE reset_tz
            WHERE reset_mode = 'calendar'
              AND period_start < (
                  date_trunc('day', now() AT TIME ZONE reset_tz)
                  + (reset_hour || ' hours')::interval
              ) AT TIME ZONE reset_tz
              AND now() >= (
                  date_trunc('day', now() AT TIME ZONE reset_tz)
                  + (reset_hour || ' hours')::interval
              ) AT TIME ZONE reset_tz
              AND consumed > 0
        """))
        calendar = result.rowcount

        conn.commit()
        total = rolling + calendar
        if total > 0:
            logger.info(f"Reset {total} expired budgets ({rolling} rolling, {calendar} calendar)")
        return total


def cleanup_old_tasks() -> int:
    """Delete old completed/failed tasks to prevent table bloat."""
    with engine.connect() as conn:
        result = conn.execute(text("""
            DELETE FROM tasks
            WHERE (state = 'done' AND completed_at < now() - interval '7 days')
               OR (state = 'failed' AND completed_at < now() - interval '30 days')
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info(f"Cleaned up {count} old tasks")
        return count


# ---------------------------------------------------------------------------
# Product embedding + guidance + CVE enrichment
# ---------------------------------------------------------------------------


def schedule_embed_products() -> int:
    """Create embed_products task if not run in last 24h and products need embedding."""
    with engine.connect() as conn:
        recent = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'embed_products' AND status = 'success'
              AND started_at > now() - interval '24 hours'
            LIMIT 1
        """)).fetchone()
        if recent:
            return 0
        has_work = conn.execute(text("""
            SELECT EXISTS(
                SELECT 1 FROM mv_product_scores p
                LEFT JOIN product_metadata pm ON pm.vendor_key = p.vendor_key AND pm.product_key = p.product_key
                WHERE pm.embedding IS NULL AND (p.composite_score >= 1 OR p.cve_count >= 5)
                LIMIT 1
            )
        """)).scalar()
        if not has_work:
            return 0
        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, status, created_at)
            SELECT 'embed_products', 'batch', 'pending', now()
            WHERE NOT EXISTS (SELECT 1 FROM tasks WHERE task_type = 'embed_products' AND status IN ('pending', 'claimed'))
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled embed_products")
        return count


def schedule_product_guidance() -> int:
    """Create product_guidance task if products have embeddings but no categories."""
    with engine.connect() as conn:
        recent = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'product_guidance' AND status = 'success'
              AND started_at > now() - interval '24 hours'
            LIMIT 1
        """)).fetchone()
        if recent:
            return 0
        has_work = conn.execute(text("""
            SELECT EXISTS(
                SELECT 1 FROM product_metadata
                WHERE embedding IS NOT NULL AND category IS NULL
                LIMIT 1
            )
        """)).scalar()
        if not has_work:
            return 0
        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, status, created_at)
            SELECT 'product_guidance', 'batch', 'pending', now()
            WHERE NOT EXISTS (SELECT 1 FROM tasks WHERE task_type = 'product_guidance' AND status IN ('pending', 'claimed'))
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled product_guidance")
        return count


def schedule_enrich_cve_summaries() -> int:
    """Create enrich_cve_summaries task if CVEs lack Gemini summaries."""
    with engine.connect() as conn:
        recent = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'enrich_cve_summaries' AND status = 'success'
              AND started_at > now() - interval '24 hours'
            LIMIT 1
        """)).fetchone()
        if recent:
            return 0
        has_work = conn.execute(text("""
            SELECT EXISTS(
                SELECT 1 FROM cves c
                LEFT JOIN cve_metadata cm ON cm.cve_id = c.id
                WHERE c.cvss_base_score IS NOT NULL AND cm.cve_id IS NULL
                LIMIT 1
            )
        """)).scalar()
        if not has_work:
            return 0
        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, status, created_at)
            SELECT 'enrich_cve_summaries', 'batch', 'pending', now()
            WHERE NOT EXISTS (SELECT 1 FROM tasks WHERE task_type = 'enrich_cve_summaries' AND status IN ('pending', 'claimed'))
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled enrich_cve_summaries")
        return count


# ---------------------------------------------------------------------------
# Main scheduler
# ---------------------------------------------------------------------------


def schedule_all() -> dict:
    """Run all scheduling rules. Returns dict of task counts created."""
    counts = {}

    # Housekeeping (every pass)
    counts["reaped"] = reap_stale_tasks()
    counts["budgets_reset"] = reset_expired_budgets()
    counts["cleaned"] = cleanup_old_tasks()

    # Coarse-grained ingests
    counts["nvd"] = schedule_ingest_nvd()
    counts["kev"] = schedule_ingest_kev()
    counts["epss"] = schedule_ingest_epss()
    counts["mitre"] = schedule_ingest_mitre()
    counts["osv"] = schedule_ingest_osv()
    counts["ghsa"] = schedule_ingest_ghsa()
    counts["exploit_db"] = schedule_ingest_exploit_db()
    # Disabled: compute_pairs and compute_hypotheses run queries too heavy
    # for the 1GB basic Postgres instance (window functions over 2.3M rows,
    # multi-table aggregations). They crash the DB and take the worker down.
    # Re-enable after DB upgrade or query optimisation.
    # counts["pairs"] = schedule_compute_pairs()
    # counts["hypotheses"] = schedule_compute_hypotheses()
    counts["embeddings"] = schedule_compute_embeddings()
    counts["views"] = schedule_refresh_views()

    # Product enrichment + Gemini CVE summaries (run after views refresh)
    counts["embed_products"] = schedule_embed_products()
    counts["product_guidance"] = schedule_product_guidance()
    counts["enrich_cve_summaries"] = schedule_enrich_cve_summaries()

    return counts


async def scheduler_loop() -> None:
    """Run scheduler every 15 minutes."""
    logger.info("Task scheduler starting")
    while True:
        try:
            counts = schedule_all()
            if any(v > 0 for v in counts.values()):
                logger.info(f"Scheduler pass complete: {counts}")
        except Exception:
            logger.exception("Scheduler error")
        await asyncio.sleep(SCHEDULER_INTERVAL)
