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


PENDING_CAP = 5000      # max pending fine-grained tasks before scheduler stops adding
BATCH_LIMIT = 5000      # max tasks to create per scheduler pass


def _pending_count(conn, task_type: str) -> int:
    """Count pending tasks for a given type."""
    row = conn.execute(text("""
        SELECT count(*) FROM tasks
        WHERE task_type = :tt AND state IN ('pending', 'claimed')
    """), {"tt": task_type}).fetchone()
    return row[0] if row else 0


def schedule_fetch_readmes() -> int:
    """Create fetch_readme tasks for repos needing READMEs for enrichment.

    Caps at PENDING_CAP pending tasks, creates up to BATCH_LIMIT per pass.
    """
    with engine.connect() as conn:
        if _pending_count(conn, "fetch_readme") >= PENDING_CAP:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type)
            SELECT 'fetch_readme', ar.full_name, 8, 'github_api'
            FROM ai_repos ar
            JOIN content_budget cb
                ON cb.pipeline = 'ai_repo_summaries'
                AND cb.domain = ar.domain
                AND cb.subcategory = ar.subcategory
            WHERE ar.problem_domains IS NULL
              AND ar.archived = false
              AND ar.description IS NOT NULL
              AND ar.description <> ''
              AND NOT EXISTS (
                  SELECT 1 FROM raw_cache rc
                  WHERE rc.source = 'github_readme'
                    AND rc.subject_id = ar.full_name
                    AND rc.fetched_at > now() - interval '90 days'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM tasks t
                  WHERE t.task_type = 'fetch_readme'
                    AND t.subject_id = ar.full_name
                    AND t.state = 'failed'
                    AND t.completed_at > now() - interval '7 days'
              )
            ORDER BY ar.stars DESC NULLS LAST
            LIMIT :lim
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """), {"lim": BATCH_LIMIT})
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info(f"Scheduled {count} fetch_readme tasks")
        return count


def schedule_enrich_summaries() -> int:
    """Create enrich_summary tasks for repos with cached READMEs but no summary.

    Caps at PENDING_CAP pending tasks, creates up to BATCH_LIMIT per pass.
    """
    with engine.connect() as conn:
        if _pending_count(conn, "enrich_summary") >= PENDING_CAP:
            return 0

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
              AND ar.archived = false
              AND ar.description IS NOT NULL
              AND ar.description <> ''
              AND rc.payload IS NOT NULL
              AND length(rc.payload) >= 100
              AND NOT EXISTS (
                  SELECT 1 FROM tasks t
                  WHERE t.task_type = 'enrich_summary'
                    AND t.subject_id = ar.full_name
                    AND t.state = 'failed'
                    AND t.completed_at > now() - interval '7 days'
              )
            ORDER BY ar.stars DESC NULLS LAST
            LIMIT :lim
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """), {"lim": BATCH_LIMIT})
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
    """Reset resource budgets whose period has expired.

    Handles both rolling (period_start + period_hours) and calendar
    (reset at reset_hour in reset_tz) modes.
    """
    with engine.connect() as conn:
        # Rolling resets
        r1 = conn.execute(text("""
            UPDATE resource_budgets
            SET consumed = 0, period_start = now()
            WHERE reset_mode = 'rolling'
              AND now() >= period_start + (period_hours || ' hours')::interval
        """))
        # Calendar resets
        r2 = conn.execute(text("""
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
        """))
        conn.commit()
        return r1.rowcount + r2.rowcount


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

    Caps at PENDING_CAP pending tasks, creates up to BATCH_LIMIT per pass.
    """
    with engine.connect() as conn:
        if _pending_count(conn, "enrich_comparison") >= PENDING_CAP:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type,
                               estimated_cost_usd)
            SELECT 'enrich_comparison', cs.id::text, 7, 'gemini', 0.0001
            FROM comparison_sentences cs
            JOIN content_budget cb
                ON cb.pipeline = 'comparison_sentences'
                AND cb.domain = cs.domain
                AND cb.subcategory = cs.subcategory
            WHERE cs.sentence IS NULL
            ORDER BY GREATEST(cs.repo_a_id, cs.repo_b_id) DESC
            LIMIT :lim
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """), {"lim": BATCH_LIMIT})
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info(f"Scheduled {count} enrich_comparison tasks")
        return count


def schedule_enrich_repo_briefs() -> int:
    """Create enrich_repo_brief tasks for repos without briefs.

    Requires ai_summary to exist (prerequisite — briefs need enriched data).
    Caps at PENDING_CAP pending tasks, creates up to BATCH_LIMIT per pass.
    """
    with engine.connect() as conn:
        if _pending_count(conn, "enrich_repo_brief") >= PENDING_CAP:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type,
                               estimated_cost_usd)
            SELECT 'enrich_repo_brief', ar.id::text, 10, 'gemini', 0.0005
            FROM ai_repos ar
            JOIN content_budget cb
                ON cb.pipeline = 'repo_briefs'
                AND cb.domain = ar.domain
                AND cb.subcategory = ar.subcategory
            LEFT JOIN repo_briefs rb ON rb.ai_repo_id = ar.id
            WHERE rb.id IS NULL
              AND ar.archived = false
              AND ar.description IS NOT NULL
              AND ar.description <> ''
              AND ar.ai_summary IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM tasks t
                  WHERE t.task_type = 'enrich_repo_brief'
                    AND t.subject_id = ar.id::text
                    AND t.state = 'failed'
                    AND t.completed_at > now() - interval '7 days'
              )
            ORDER BY ar.stars DESC NULLS LAST
            LIMIT :lim
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """), {"lim": BATCH_LIMIT})
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
            SELECT 'enrich_project_brief', 'all', 8, 'gemini', 0.05
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


def _schedule_coarse_task(task_type: str, sync_type: str, priority: int,
                          resource_type: str | None,
                          staleness_hours: int = 24) -> int:
    """Generic scheduler for coarse-grained tasks: create one task if last
    sync_log entry for sync_type is older than staleness_hours and no task
    is pending."""
    with engine.connect() as conn:
        recent = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = :sync_type
              AND status IN ('success', 'partial')
              AND started_at > now() - (:hours || ' hours')::interval
            LIMIT 1
        """), {"sync_type": sync_type, "hours": staleness_hours}).fetchone()

        if recent:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type)
            SELECT :task_type, 'all', :priority, :resource_type
            WHERE NOT EXISTS (
                SELECT 1 FROM tasks
                WHERE task_type = :task_type
                  AND state IN ('pending', 'claimed')
            )
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """), {
            "task_type": task_type,
            "priority": priority,
            "resource_type": resource_type,
        })
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info(f"Scheduled {task_type} task")
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
              AND ar.archived = false
              AND NOT EXISTS (
                  SELECT 1 FROM tasks t
                  WHERE t.task_type = 'backfill_created_at'
                    AND t.subject_id = ar.id::text
                    AND t.state = 'failed'
                    AND t.completed_at > now() - interval '7 days'
              )
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


def schedule_compute_embeddings() -> int:
    """Create a compute_embeddings task if the last run was >24h ago."""
    with engine.connect() as conn:
        recent = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type IN ('embed_projects', 'embed_ai_repos')
              AND status = 'success'
              AND started_at > now() - interval '24 hours'
            LIMIT 1
        """)).fetchone()

        if recent:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type)
            SELECT 'compute_embeddings', 'all', 5, 'openai'
            WHERE NOT EXISTS (
                SELECT 1 FROM tasks
                WHERE task_type = 'compute_embeddings'
                  AND state IN ('pending', 'claimed')
            )
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled compute_embeddings task")
        return count


def schedule_compute_mv_refresh() -> int:
    """Create a compute_mv_refresh task if the last refresh was >6h ago."""
    with engine.connect() as conn:
        recent = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'views'
              AND status IN ('success', 'partial')
              AND started_at > now() - interval '6 hours'
            LIMIT 1
        """)).fetchone()

        if recent:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type)
            SELECT 'compute_mv_refresh', 'all', 5, NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM tasks
                WHERE task_type = 'compute_mv_refresh'
                  AND state IN ('pending', 'claimed')
            )
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled compute_mv_refresh task")
        return count


def schedule_compute_content_budget() -> int:
    """Create a compute_content_budget task if the budget is stale.

    Depends on MV refresh having run — checks that views were refreshed
    more recently than the current content_budget computation.
    """
    with engine.connect() as conn:
        # Only schedule if MVs were refreshed today but budget is stale
        mv_fresh = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'views'
              AND status IN ('success', 'partial')
              AND started_at::date = CURRENT_DATE
            LIMIT 1
        """)).fetchone()

        if not mv_fresh:
            return 0

        if _budget_is_fresh():
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type)
            SELECT 'compute_content_budget', 'all', 5, NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM tasks
                WHERE task_type = 'compute_content_budget'
                  AND state IN ('pending', 'claimed')
            )
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled compute_content_budget task")
        return count


def schedule_export_static_site() -> int:
    """Create an export_static_site task if MVs were refreshed today
    but the site hasn't been deployed since.
    """
    with engine.connect() as conn:
        # Check if MVs were refreshed today
        mv_refresh = conn.execute(text("""
            SELECT started_at FROM sync_log
            WHERE sync_type = 'views'
              AND status IN ('success', 'partial')
              AND started_at::date = CURRENT_DATE
            ORDER BY started_at DESC
            LIMIT 1
        """)).fetchone()

        if not mv_refresh:
            return 0

        # Check if site was already deployed after this refresh
        last_deploy = conn.execute(text("""
            SELECT 1 FROM sync_log
            WHERE sync_type = 'static_site'
              AND status = 'success'
              AND started_at > :mv_time
            LIMIT 1
        """), {"mv_time": mv_refresh[0]}).fetchone()

        if last_deploy:
            return 0

        result = conn.execute(text("""
            INSERT INTO tasks (task_type, subject_id, priority, resource_type)
            SELECT 'export_static_site', 'all', 4, NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM tasks
                WHERE task_type = 'export_static_site'
                  AND state IN ('pending', 'claimed')
            )
            ON CONFLICT (task_type, subject_id)
                WHERE state IN ('pending', 'claimed')
            DO NOTHING
        """))
        conn.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Scheduled export_static_site task")
        return count


def check_task_health() -> None:
    """Log ERROR if any task type has 100% failure rate in the last hour."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT task_type,
                   count(*) FILTER (WHERE state = 'done') as done,
                   count(*) FILTER (WHERE state = 'failed') as failed,
                   max(error_message) as last_error
            FROM tasks
            WHERE completed_at > now() - interval '1 hour'
            GROUP BY task_type
            HAVING count(*) FILTER (WHERE state = 'done') = 0
               AND count(*) FILTER (WHERE state = 'failed') > 2
        """)).fetchall()
    for row in rows:
        logger.error(
            f"HEALTH: {row.task_type} has 0 successes and {row.failed} failures "
            f"in the last hour. Last error: {row.last_error[:200] if row.last_error else 'unknown'}"
        )


def check_orphaned_tasks() -> None:
    """Log ERROR if any tasks are stuck in pending and never claimed.

    A task pending for >1 hour with retry_count=0 has never been picked
    up by the worker. Common causes: resource_type mismatch between
    scheduler and worker, or a handler that was removed but tasks remain.
    """
    from app.queue.worker import CONCURRENT_RESOURCES

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT task_type, resource_type, count(*) AS n,
                   min(created_at) AS oldest
            FROM tasks
            WHERE state = 'pending'
              AND created_at < now() - interval '1 hour'
              AND retry_count = 0
            GROUP BY 1, 2
        """)).fetchall()

    valid_resources = set(CONCURRENT_RESOURCES) | {None}
    for row in rows:
        reason = ""
        if row.resource_type not in valid_resources:
            reason = f" (resource_type '{row.resource_type}' not in worker's CONCURRENT_RESOURCES)"
        logger.error(
            f"HEALTH: {row.n} orphaned {row.task_type} tasks pending since "
            f"{row.oldest.strftime('%Y-%m-%d %H:%M') if row.oldest else '?'}, "
            f"never claimed{reason}"
        )


def check_pipeline_freshness() -> None:
    """Log ERROR if critical pipeline outputs are stale."""
    with engine.connect() as conn:
        checks = [
            ("MV refresh", """
                SELECT 1 FROM sync_log
                WHERE sync_type = 'views'
                  AND status IN ('success', 'partial')
                  AND started_at > now() - interval '24 hours'
                LIMIT 1
            """),
            ("Site export", """
                SELECT 1 FROM sync_log
                WHERE sync_type = 'static_site'
                  AND status = 'success'
                  AND started_at > now() - interval '24 hours'
                LIMIT 1
            """),
            ("Content budget", """
                SELECT 1 FROM content_budget
                WHERE computed_at::date = CURRENT_DATE
                LIMIT 1
            """),
        ]
        for name, sql in checks:
            row = conn.execute(text(sql)).fetchone()
            if row is None:
                logger.error(f"HEALTH: {name} is stale — no successful run in the last 24 hours")


def report_failure_summary() -> None:
    """Log a summary of task failures in the last 24 hours.

    Groups by task_type and error class so repeated failures are visible
    as a pattern, not buried in individual log lines.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT task_type,
                   substring(error_message from 1 for 80) AS error_class,
                   count(*) AS n,
                   count(DISTINCT subject_id) AS unique_subjects
            FROM tasks
            WHERE state = 'failed'
              AND completed_at > now() - interval '24 hours'
            GROUP BY 1, 2
            ORDER BY n DESC
            LIMIT 20
        """)).fetchall()

    if not rows:
        logger.info("Task failure summary: 0 failures in the last 24h")
        return

    total = sum(r.n for r in rows)
    lines = [f"Task failure summary: {total} failures in the last 24h"]
    for r in rows:
        lines.append(
            f"  {r.n:>5d} failures ({r.unique_subjects} subjects) "
            f"{r.task_type}: {r.error_class}"
        )
    logger.warning("\n".join(lines))


def schedule_all() -> dict:
    """Run all scheduling rules. Returns counts of tasks created."""
    counts = {}

    # Health checks first
    check_task_health()
    check_pipeline_freshness()
    check_orphaned_tasks()
    report_failure_summary()

    # Housekeeping
    reap_stale_tasks()
    reset_expired_budgets()
    cleanup_old_tasks()

    # Infrastructure (embeddings before MVs, MVs before budget, budget before enrichment)
    counts["compute_embeddings"] = schedule_compute_embeddings()
    counts["compute_mv_refresh"] = schedule_compute_mv_refresh()
    counts["compute_content_budget"] = schedule_compute_content_budget()
    counts["export_static_site"] = schedule_export_static_site()

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

    # LLM classification tasks (sync_log staleness)
    counts["enrich_subcategory"] = _schedule_coarse_task("enrich_subcategory", "subcategory_llm", 4, "gemini")
    counts["enrich_stack_layer"] = _schedule_coarse_task("enrich_stack_layer", "stack_layer", 4, "gemini")
    counts["enrich_hn_match"] = _schedule_coarse_task("enrich_hn_match", "hn_llm_match", 4, "gemini")
    counts["enrich_package_detect"] = _schedule_coarse_task("enrich_package_detect", "ai_repo_package_detect", 4, "gemini")

    # Data freshness — all coarse-grained, sync_log staleness
    counts["fetch_github"] = schedule_fetch_github()
    counts["fetch_releases"] = schedule_fetch_releases()

    # Data ingestion — resource types enable concurrent execution
    counts["fetch_downloads"] = _schedule_coarse_task("fetch_downloads", "downloads", 7, "pypi")
    counts["fetch_dockerhub"] = _schedule_coarse_task("fetch_dockerhub", "dockerhub", 7, "dockerhub")
    counts["fetch_vscode"] = _schedule_coarse_task("fetch_vscode", "vscode", 7, "vscode")
    counts["fetch_huggingface"] = _schedule_coarse_task("fetch_huggingface", "huggingface", 7, "huggingface")
    counts["fetch_hn"] = _schedule_coarse_task("fetch_hn", "hn", 6, "hn_algolia")
    counts["fetch_v2ex"] = _schedule_coarse_task("fetch_v2ex", "v2ex", 6, "v2ex")
    counts["fetch_trending"] = _schedule_coarse_task("fetch_trending", "trending", 7, "github_search")
    counts["fetch_candidates"] = _schedule_coarse_task("fetch_candidates", "candidate_velocity", 4, "github_api")
    counts["fetch_candidate_watchlist"] = _schedule_coarse_task("fetch_candidate_watchlist", "candidate_watchlist", 4, "db_only")
    counts["fetch_hf_datasets"] = _schedule_coarse_task("fetch_hf_datasets", "hf_datasets", 5, "huggingface")
    counts["fetch_hf_models"] = _schedule_coarse_task("fetch_hf_models", "hf_models", 5, "huggingface")
    counts["fetch_public_apis"] = _schedule_coarse_task("fetch_public_apis", "public_apis", 5, "db_only")
    counts["fetch_api_specs"] = _schedule_coarse_task("fetch_api_specs", "api_specs", 5, "db_only")
    counts["fetch_package_deps"] = _schedule_coarse_task("fetch_package_deps", "package_deps", 5, "npm")
    counts["compute_dep_velocity"] = _schedule_coarse_task("compute_dep_velocity", "dep_velocity", 5, "db_only")
    counts["fetch_builder_tools"] = _schedule_coarse_task("fetch_builder_tools", "builder_tools", 5, "db_only")
    counts["fetch_npm_mcp"] = _schedule_coarse_task("fetch_npm_mcp", "npm_mcp", 5, "npm")
    counts["fetch_ai_repo_downloads"] = _schedule_coarse_task("fetch_ai_repo_downloads", "ai_repo_downloads", 5, "pypi")
    counts["fetch_ai_repo_commits"] = _schedule_coarse_task("fetch_ai_repo_commits", "ai_repo_commits", 5, "github_graphql")
    counts["fetch_newsletters"] = _schedule_coarse_task("fetch_newsletters", "newsletters", 6, "gemini")
    counts["fetch_models"] = _schedule_coarse_task("fetch_models", "models", 5, "db_only")

    # Analytics + post-processing
    counts["import_gsc"] = _schedule_coarse_task("import_gsc", "gsc", 6, "db_only")
    counts["import_umami"] = _schedule_coarse_task("import_umami", "umami", 6, "db_only")
    counts["compute_coview"] = _schedule_coarse_task("compute_coview", "coview", 5, "db_only")
    counts["compute_hn_backfill"] = _schedule_coarse_task("compute_hn_backfill", "hn_backfill", 5, "db_only")
    counts["compute_hn_lab_backfill"] = _schedule_coarse_task("compute_hn_lab_backfill", "hn_lab_backfill", 5, "db_only")
    counts["compute_v2ex_lab_backfill"] = _schedule_coarse_task("compute_v2ex_lab_backfill", "v2ex_lab_backfill", 5, "db_only")
    counts["compute_domain_reassign"] = _schedule_coarse_task("compute_domain_reassign", "domain_reassign", 5, "db_only")
    counts["compute_project_linking"] = _schedule_coarse_task("compute_project_linking", "project_linking", 5, "db_only")
    counts["compute_briefing_refresh"] = _schedule_coarse_task("compute_briefing_refresh", "briefing_refresh", 5, "db_only")
    counts["export_dataset"] = _schedule_coarse_task("export_dataset", "dataset_export", 4, "github_api")

    # Demand Radar (daily, after MV refresh)
    counts["snapshot_bot_activity"] = _schedule_coarse_task(
        "snapshot_bot_activity", "bot_activity_snapshot", 5, "db_only", staleness_hours=20)
    counts["detect_bot_sessions"] = _schedule_coarse_task(
        "detect_bot_sessions", "bot_sessions", 5, "db_only", staleness_hours=20)

    # Discovery (daily) and structural (weekly)
    counts["discover_ai_repos"] = _schedule_coarse_task("discover_ai_repos", "ai_repos", 4, "github_search", staleness_hours=24)
    counts["compute_structural"] = _schedule_coarse_task("compute_structural", "weekly_structural", 3, "db_only", staleness_hours=168)

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
