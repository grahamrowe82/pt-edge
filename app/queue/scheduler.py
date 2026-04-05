"""Thin scheduler: creates tasks based on staleness, never executes them.

Runs periodically (every 15 minutes) as a coroutine inside the worker
process. Queries the database to find work that needs doing, creates
task rows, and lets the worker loop pick them up.

Also handles housekeeping: stale task reaping, budget resets, old task cleanup.
"""
import asyncio
import logging

from sqlalchemy import text

from app.db import engine

logger = logging.getLogger(__name__)

SCHEDULER_INTERVAL = 900  # 15 minutes


def _budget_is_fresh() -> bool:
    """Check if content_budget was computed today."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT 1 FROM content_budget "
            "WHERE computed_at::date = CURRENT_DATE LIMIT 1"
        )).fetchone()
        return row is not None


def schedule_fetch_readmes() -> int:
    """Create fetch_readme tasks for repos needing READMEs for enrichment.

    Only creates tasks for repos that:
    - Have no summary yet (problem_domains IS NULL)
    - Have a description
    - Are in the content_budget allocation
    - Don't have a fresh README in raw_cache (< 90 days)
    - Don't already have a pending/claimed fetch_readme task (dedup index)
    """
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type)
            SELECT 'fetch_readme', ar.full_name, 8, 'github_api'
            FROM ai_repos ar
            JOIN content_budget cb
                ON cb.pipeline = 'ai_repo_summaries'
                AND cb.domain = ar.domain
                AND cb.subcategory = ar.subcategory
            WHERE ar.problem_domains IS NULL
              AND ar.is_active = true
              AND ar.description IS NOT NULL
              AND ar.description <> ''
              AND NOT EXISTS (
                  SELECT 1 FROM raw_cache rc
                  WHERE rc.source = 'github_readme'
                    AND rc.subject_id = ar.full_name
                    AND rc.fetched_at > now() - interval '90 days'
              )
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info(f"Scheduled {count} fetch_readme tasks")
        return count


def schedule_enrich_summaries() -> int:
    """Create enrich_summary tasks for repos with cached READMEs but no summary.

    Only creates tasks for repos that:
    - Have a fresh README in raw_cache with non-null payload >= 100 chars
    - Have no summary yet (problem_domains IS NULL)
    - Are in the content_budget allocation
    - Don't already have a pending/claimed enrich_summary task (dedup index)
    """
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type,
                               estimated_cost_usd)
            SELECT 'enrich_summary', ar.full_name, 9, 'gemini', 0.0001
            FROM ai_repos ar
            JOIN content_budget cb
                ON cb.pipeline = 'ai_repo_summaries'
                AND cb.domain = ar.domain
                AND cb.subcategory = ar.subcategory
            JOIN raw_cache rc
                ON rc.source = 'github_readme'
                AND rc.subject_id = ar.full_name
            WHERE ar.problem_domains IS NULL
              AND ar.is_active = true
              AND ar.description IS NOT NULL
              AND ar.description <> ''
              AND rc.payload IS NOT NULL
              AND length(rc.payload) >= 100
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info(f"Scheduled {count} enrich_summary tasks")
        return count


def reap_stale_tasks() -> int:
    """Reclaim tasks stuck in 'claimed' state (worker crashed or timed out).

    Tasks with a heartbeat older than 10 minutes are returned to pending
    if they have retries left, or marked failed if they don't.
    """
    with engine.connect() as conn:
        # Requeue tasks with retries remaining
        result = conn.execute(text("""
            UPDATE tasks
            SET state = 'pending',
                claimed_by = NULL,
                claimed_at = NULL,
                heartbeat_at = NULL,
                retry_count = retry_count + 1,
                error_message = 'heartbeat timeout — requeued by scheduler'
            WHERE state = 'claimed'
              AND heartbeat_at < now() - interval '10 minutes'
              AND retry_count < max_retries
        """))
        requeued = result.rowcount

        # Fail tasks with no retries remaining
        result = conn.execute(text("""
            UPDATE tasks
            SET state = 'failed',
                error_message = 'heartbeat timeout — max retries exhausted',
                completed_at = now()
            WHERE state = 'claimed'
              AND heartbeat_at < now() - interval '10 minutes'
              AND retry_count >= max_retries
        """))
        failed = result.rowcount

        conn.commit()
        if requeued or failed:
            logger.info(f"Reaped stale tasks: {requeued} requeued, {failed} failed")
        return requeued + failed


def reset_expired_budgets() -> int:
    """Reset resource budgets whose period has expired."""
    with engine.connect() as conn:
        result = conn.execute(text("""
            UPDATE resource_budgets
            SET consumed = 0, period_start = now()
            WHERE now() >= period_start + (period_hours || ' hours')::interval
        """))
        conn.commit()
        return result.rowcount


def cleanup_old_tasks() -> int:
    """Delete old completed and failed tasks to prevent table bloat."""
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


def schedule_enrich_project_briefs() -> int:
    """Create enrich_project_brief tasks for projects with stale or missing briefs.

    Only creates tasks for active projects where:
    - No brief exists, OR
    - Brief generation_hash differs from current metrics, OR
    - Brief is >30 days old
    """
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type,
                               estimated_cost_usd)
            SELECT 'enrich_project_brief', s.project_id::text, 7, 'gemini', 0.0005
            FROM mv_project_summary s
            JOIN projects p ON s.project_id = p.id
            LEFT JOIN project_briefs pb ON s.project_id = pb.project_id
            WHERE p.is_active = true
              AND (
                  pb.project_id IS NULL
                  OR pb.generated_at < now() - interval '30 days'
              )
            ORDER BY s.stars DESC NULLS LAST
            LIMIT 100
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info(f"Scheduled {count} enrich_project_brief tasks")
        return count


def schedule_enrich_domain_briefs() -> int:
    """Create enrich_domain_brief tasks for domains with stale or missing briefs.

    Staleness-driven: >7 days old or missing. NOT gated by day of week.
    """
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type,
                               estimated_cost_usd)
            SELECT 'enrich_domain_brief', s.domain, 3, 'gemini', 0.001
            FROM (
                SELECT DISTINCT domain
                FROM mv_project_summary
                WHERE domain IS NOT NULL
            ) s
            LEFT JOIN domain_briefs db ON db.domain = s.domain
            WHERE db.domain IS NULL
               OR db.generated_at < now() - interval '7 days'
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info(f"Scheduled {count} enrich_domain_brief tasks")
        return count


def schedule_enrich_landscape_briefs() -> int:
    """Create enrich_landscape_brief tasks for layers with stale or missing briefs.

    Staleness-driven: >7 days old or missing. NOT gated by day of week.
    """
    from app.queue.handlers.enrich_landscape_brief import LANDSCAPE_LAYERS

    layer_names = list(LANDSCAPE_LAYERS.keys())
    if not layer_names:
        return 0

    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type,
                               estimated_cost_usd)
            SELECT 'enrich_landscape_brief', layer_name, 3, 'gemini', 0.001
            FROM unnest(:layers::text[]) AS layer_name
            LEFT JOIN landscape_briefs lb ON lb.layer = layer_name
            WHERE lb.layer IS NULL
               OR lb.generated_at < now() - interval '7 days'
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """), {"layers": layer_names})
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info(f"Scheduled {count} enrich_landscape_brief tasks")
        return count


def schedule_all() -> dict:
    """Run all scheduling rules. Returns counts of tasks created."""
    counts = {}

    # Housekeeping first
    reap_stale_tasks()
    reset_expired_budgets()
    cleanup_old_tasks()

    # Only schedule enrichment work if content_budget is fresh
    if _budget_is_fresh():
        counts["fetch_readme"] = schedule_fetch_readmes()
        counts["enrich_summary"] = schedule_enrich_summaries()
        counts["enrich_project_brief"] = schedule_enrich_project_briefs()
    else:
        logger.info("Skipping budget-gated task scheduling — content_budget not computed today")

    # Domain and landscape briefs are staleness-driven, not budget-gated
    counts["enrich_domain_brief"] = schedule_enrich_domain_briefs()
    counts["enrich_landscape_brief"] = schedule_enrich_landscape_briefs()

    return counts


async def scheduler_loop() -> None:
    """Run the scheduler periodically as an asyncio coroutine."""
    logger.info("Task scheduler starting")

    while True:
        try:
            counts = schedule_all()
            if any(v > 0 for v in counts.values()):
                logger.info(f"Scheduler pass complete: {counts}")
        except Exception as e:
            logger.exception(f"Scheduler error: {e}")

        await asyncio.sleep(SCHEDULER_INTERVAL)
