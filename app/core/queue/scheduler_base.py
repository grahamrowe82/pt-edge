"""Generic scheduler helpers for task queue housekeeping.

Domain-specific scheduling functions (schedule_fetch_*, schedule_enrich_*)
live in the domain's scheduler module. This module provides only the
shared infrastructure: stale task reaping, budget resets, failure reporting,
and constants.
"""
import logging

from sqlalchemy import text

from app.db import engine

logger = logging.getLogger(__name__)

PENDING_CAP = 5000      # max pending fine-grained tasks before scheduler stops adding
BATCH_LIMIT = 5000      # max tasks to create per scheduler pass


def _pending_count(conn, task_type: str) -> int:
    """Count pending tasks for a given type."""
    row = conn.execute(text("""
        SELECT count(*) FROM tasks
        WHERE task_type = :tt AND state IN ('pending', 'claimed')
    """), {"tt": task_type}).fetchone()
    return row[0] if row else 0


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
