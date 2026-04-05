"""Stateless task queue worker.

Claims the highest-priority affordable task, executes it, writes the
result back to the database. Repeat. If there's no work, sleep briefly.

The worker is stateless — it reads inputs from the database and writes
outputs to the database. If it crashes, uncompleted tasks are reclaimed
by the scheduler's stale task reaper.
"""
import asyncio
import logging
import os
import socket

from sqlalchemy import text

from app.db import engine

logger = logging.getLogger(__name__)

WORKER_ID = f"worker-{os.getpid()}-{socket.gethostname()}"
POLL_INTERVAL = 5       # seconds between claim attempts when idle
HEARTBEAT_INTERVAL = 60  # seconds between heartbeats during execution

# SQL: claim the highest-priority pending task with available budget.
# Uses FOR UPDATE SKIP LOCKED so multiple workers don't block each other.
# Handles budget period expiry inline.
_CLAIM_SQL = text("""
    WITH budget_check AS (
        SELECT resource_type,
               CASE WHEN now() >= period_start + (period_hours || ' hours')::interval
                    THEN budget
                    ELSE budget - consumed
               END AS remaining
        FROM resource_budgets
    ),
    next_task AS (
        SELECT t.id
        FROM tasks t
        LEFT JOIN budget_check bc ON bc.resource_type = t.resource_type
        WHERE t.state = 'pending'
          AND (t.resource_type IS NULL OR bc.remaining > 0)
        ORDER BY t.priority DESC, t.created_at ASC
        LIMIT 1
        FOR UPDATE OF t SKIP LOCKED
    )
    UPDATE tasks
    SET state = 'claimed',
        claimed_by = :worker_id,
        claimed_at = now(),
        heartbeat_at = now()
    WHERE id = (SELECT id FROM next_task)
    RETURNING id, task_type, subject_id, priority, resource_type,
              retry_count, max_retries
""")

# SQL: decrement resource budget after claiming a task.
# Resets the period if it has expired.
_DECREMENT_BUDGET_SQL = text("""
    UPDATE resource_budgets
    SET consumed = CASE
            WHEN now() >= period_start + (period_hours || ' hours')::interval
            THEN 1
            ELSE consumed + 1
        END,
        period_start = CASE
            WHEN now() >= period_start + (period_hours || ' hours')::interval
            THEN now()
            ELSE period_start
        END
    WHERE resource_type = :resource_type
""")


def claim_next_task(worker_id: str) -> dict | None:
    """Claim the next available task. Returns task dict or None."""
    with engine.connect() as conn:
        row = conn.execute(_CLAIM_SQL, {"worker_id": worker_id}).mappings().fetchone()
        if row is None:
            conn.commit()
            return None
        task = dict(row)
        if task.get("resource_type"):
            conn.execute(_DECREMENT_BUDGET_SQL, {"resource_type": task["resource_type"]})
        conn.commit()
        return task


def mark_done(task_id: int, result: dict | None = None) -> None:
    """Mark a task as successfully completed."""
    import json
    result_json = json.dumps(result) if result is not None else None
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE tasks
            SET state = 'done', completed_at = now(), result = :result::jsonb
            WHERE id = :id
        """), {"id": task_id, "result": result_json})
        conn.commit()


def mark_failed(task_id: int, error: str) -> None:
    """Mark a task as permanently failed."""
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE tasks
            SET state = 'failed', error_message = :error, completed_at = now()
            WHERE id = :id
        """), {"id": task_id, "error": error[:2000]})
        conn.commit()


def requeue(task_id: int, error: str) -> None:
    """Return a task to pending state for retry."""
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE tasks
            SET state = 'pending',
                retry_count = retry_count + 1,
                error_message = :error,
                claimed_by = NULL,
                claimed_at = NULL,
                heartbeat_at = NULL
            WHERE id = :id
        """), {"id": task_id, "error": error[:2000]})
        conn.commit()


def heartbeat(task_id: int) -> None:
    """Update heartbeat timestamp to signal the worker is still alive."""
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE tasks SET heartbeat_at = now() WHERE id = :id
        """), {"id": task_id})
        conn.commit()


async def worker_loop() -> None:
    """Main worker loop. Claims and executes tasks continuously."""
    from app.queue.handlers import TASK_HANDLERS

    logger.info(f"Task queue worker starting: {WORKER_ID}")

    while True:
        task = claim_next_task(WORKER_ID)
        if task is None:
            await asyncio.sleep(POLL_INTERVAL)
            continue

        task_id = task["id"]
        task_type = task["task_type"]
        subject = task.get("subject_id", "")
        logger.info(f"Claimed task {task_id}: {task_type} {subject}")

        handler = TASK_HANDLERS.get(task_type)
        if handler is None:
            mark_failed(task_id, f"Unknown task type: {task_type}")
            logger.error(f"Unknown task type: {task_type}")
            continue

        try:
            result = await handler(task)
            mark_done(task_id, result)
            logger.info(f"Completed task {task_id}: {task_type} {subject} -> {result}")
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            if task["retry_count"] < task["max_retries"]:
                requeue(task_id, error_msg)
                logger.warning(
                    f"Task {task_id} failed (attempt {task['retry_count'] + 1}/"
                    f"{task['max_retries']}), requeued: {error_msg}"
                )
            else:
                mark_failed(task_id, error_msg)
                logger.error(
                    f"Task {task_id} permanently failed after "
                    f"{task['max_retries']} attempts: {error_msg}"
                )
