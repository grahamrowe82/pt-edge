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


def schedule_enrich_comparisons() -> int:
    """Create enrich_comparison tasks for pairs without sentences.

    Only creates tasks for pairs that:
    - Have no sentence yet (sentence IS NULL)
    - Are in the content_budget allocation for comparison_sentences
    - Don't already have a pending/claimed task (dedup index)
    """
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type,
                               estimated_cost_usd)
            SELECT 'enrich_comparison', cs.id::text, 9, 'gemini', 0.0001
            FROM comparison_sentences cs
            JOIN content_budget cb
                ON cb.pipeline = 'comparison_sentences'
                AND cb.domain = cs.domain
                AND cb.subcategory = cs.subcategory
            WHERE cs.sentence IS NULL
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info(f"Scheduled {count} enrich_comparison tasks")
        return count


def schedule_enrich_repo_briefs() -> int:
    """Create enrich_repo_brief tasks for repos without briefs.

    Only creates tasks for repos that:
    - Have a description
    - Are in the content_budget allocation for repo_briefs
    - Don't already have a repo_briefs row
    - Don't already have a pending/claimed task (dedup index)
    """
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type,
                               estimated_cost_usd)
            SELECT 'enrich_repo_brief', ar.id::text, 9, 'gemini', 0.0005
            FROM ai_repos ar
            JOIN content_budget cb
                ON cb.pipeline = 'repo_briefs'
                AND cb.domain = ar.domain
                AND cb.subcategory = ar.subcategory
            LEFT JOIN repo_briefs rb ON rb.ai_repo_id = ar.id
            WHERE rb.id IS NULL
              AND ar.is_active = true
              AND ar.description IS NOT NULL
              AND ar.description <> ''
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info(f"Scheduled {count} enrich_repo_brief tasks")
        return count


def schedule_enrich_project_briefs() -> int:
    """Create a single enrich_project_brief task if none is pending.

    Coarse-grained: the handler processes up to 100 projects internally.
    The scheduler just ensures a task exists when content_budget is fresh.
    """
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type,
                               estimated_cost_usd)
            SELECT 'enrich_project_brief', 'all', 7, 'gemini', 0.05
            WHERE NOT EXISTS (
                SELECT 1 FROM tasks
                WHERE task_type = 'enrich_project_brief'
                  AND state IN ('pending', 'claimed')
            )
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled enrich_project_brief task")
        return count


def schedule_enrich_domain_briefs() -> int:
    """Create enrich_domain_brief tasks for domains with stale or missing briefs.

    Staleness-driven: creates tasks when a domain's brief is >7 days old
    or missing entirely. NOT gated by day of week — this kills the
    Sunday concept.
    """
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type,
                               estimated_cost_usd)
            SELECT 'enrich_domain_brief', s.domain, 3, 'gemini', 0.001
            FROM (SELECT DISTINCT domain FROM mv_project_summary WHERE domain IS NOT NULL) s
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
    """Create a single enrich_landscape_brief task if any layer is stale.

    Coarse-grained: the handler processes all layers internally with its
    own staleness detection via generation_hash. The scheduler just
    ensures a task exists when any layer might be stale (>7 days).
    """
    with engine.connect() as conn:
        # Check if any layer is stale or missing
        stale = conn.execute(text("""
            SELECT 1
            WHERE EXISTS (
                SELECT 1 FROM (VALUES
                    ('mcp-gateway'), ('mcp-transport'), ('mcp-security'),
                    ('mcp-framework'), ('mcp-ide'), ('agents'),
                    ('ai-coding'), ('nlp'), ('llm-tools'), ('computer-vision')
                ) AS layers(name)
                LEFT JOIN landscape_briefs lb ON lb.layer = layers.name
                WHERE lb.layer IS NULL
                   OR lb.generated_at < now() - interval '7 days'
            )
        """)).fetchone()

        if not stale:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type,
                               estimated_cost_usd)
            SELECT 'enrich_landscape_brief', 'all', 3, 'gemini', 0.02
            WHERE NOT EXISTS (
                SELECT 1 FROM tasks
                WHERE task_type = 'enrich_landscape_brief'
                  AND state IN ('pending', 'claimed')
            )
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled enrich_landscape_brief task")
        return count


def schedule_backfill_created_at() -> int:
    """Create backfill_created_at tasks for repos missing created_at.

    Fine-grained: one task per repo. Creates batches of 1000, but only
    when fewer than 500 are already pending. This avoids flooding the
    table with 225K rows while keeping the queue fed.
    """
    with engine.connect() as conn:
        # Check how many are already pending
        pending = conn.execute(text("""
            SELECT count(*) FROM tasks
            WHERE task_type = 'backfill_created_at'
              AND state IN ('pending', 'claimed')
        """)).scalar() or 0

        if pending >= 500:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type)
            SELECT 'backfill_created_at', ar.id::text, 2, 'github_api'
            FROM ai_repos ar
            WHERE ar.created_at IS NULL
            ORDER BY ar.stars DESC NULLS LAST
            LIMIT 1000
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info(f"Scheduled {count} backfill_created_at tasks")
        return count


def schedule_fetch_github() -> int:
    """Create a fetch_github task if the last run was >24h ago.

    Coarse-grained: one task refreshes all ~800 project metadata.
    """
    with engine.connect() as conn:
        recent = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'github'
              AND status = 'success'
              AND started_at > now() - interval '24 hours'
            LIMIT 1
        """)).fetchone()

        if recent:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type)
            SELECT 'fetch_github', 'all', 7, 'github_api'
            WHERE NOT EXISTS (
                SELECT 1 FROM tasks
                WHERE task_type = 'fetch_github'
                  AND state IN ('pending', 'claimed')
            )
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled fetch_github task")
        return count


def schedule_fetch_releases() -> int:
    """Create a fetch_releases task if the last run was >24h ago.

    Coarse-grained: one task fetches releases + generates summaries
    for all projects.
    """
    with engine.connect() as conn:
        recent = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'releases'
              AND status = 'success'
              AND started_at > now() - interval '24 hours'
            LIMIT 1
        """)).fetchone()

        if recent:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type)
            SELECT 'fetch_releases', 'all', 6, 'github_api'
            WHERE NOT EXISTS (
                SELECT 1 FROM tasks
                WHERE task_type = 'fetch_releases'
                  AND state IN ('pending', 'claimed')
            )
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled fetch_releases task")
        return count


def schedule_all() -> dict:
    """Run all scheduling rules. Returns counts of tasks created."""
    counts = {}

    # Housekeeping first
    reap_stale_tasks()
    reset_expired_budgets()
    cleanup_old_tasks()

    # Budget-gated enrichment (needs content_budget computed today)
    if _budget_is_fresh():
        counts["fetch_readme"] = schedule_fetch_readmes()
        counts["enrich_summary"] = schedule_enrich_summaries()
        counts["enrich_comparison"] = schedule_enrich_comparisons()
        counts["enrich_repo_brief"] = schedule_enrich_repo_briefs()
        counts["enrich_project_brief"] = schedule_enrich_project_briefs()
    else:
        logger.info("Skipping budget-gated scheduling — content_budget not computed today")

    # Staleness-driven enrichment (no budget gate, no day-of-week gate)
    counts["enrich_domain_brief"] = schedule_enrich_domain_briefs()
    counts["enrich_landscape_brief"] = schedule_enrich_landscape_briefs()

    # Data freshness (sync_log staleness)
    counts["fetch_github"] = schedule_fetch_github()
    counts["fetch_releases"] = schedule_fetch_releases()

    # Backfill (lowest priority, creates tasks in batches)
    counts["backfill_created_at"] = schedule_backfill_created_at()

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
