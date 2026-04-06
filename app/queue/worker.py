"""Stateless task queue worker with resource-aware concurrency.

Runs multiple tasks concurrently when they use different resources.
A GitHub task and a Gemini task don't compete — they run in parallel.
Tasks sharing a resource type are serialised by the claim query.

The worker maintains one active task per resource type. When a task
completes, it immediately claims the next one for that resource slot.
"""
import asyncio
import json
import logging
import os
import socket

from sqlalchemy import text

from app.db import engine
from app.ingest.budget import ResourceExhaustedError, ResourceThrottledError

logger = logging.getLogger(__name__)

WORKER_ID = f"worker-{os.getpid()}-{socket.gethostname()}"
POLL_INTERVAL = 5       # seconds between claim attempts when idle
HEARTBEAT_INTERVAL = 60  # seconds between heartbeats during execution

# SQL: claim the highest-priority pending task for a specific resource type.
# Checks budget remaining (rolling or calendar reset) and backoff state.
_CLAIM_FOR_RESOURCE_SQL = text("""
    WITH budget_check AS (
        SELECT resource_type,
               CASE
                 -- Backed off: no remaining budget
                 WHEN backoff_until IS NOT NULL AND now() < backoff_until
                 THEN 0
                 -- Rolling: period expired, full budget available
                 WHEN reset_mode = 'rolling'
                   AND now() >= period_start + (period_hours || ' hours')::interval
                 THEN budget
                 -- Calendar: period expired, full budget available
                 WHEN reset_mode = 'calendar'
                   AND period_start < (
                     date_trunc('day', now() AT TIME ZONE reset_tz)
                     + (reset_hour || ' hours')::interval
                   ) AT TIME ZONE reset_tz
                   AND now() >= (
                     date_trunc('day', now() AT TIME ZONE reset_tz)
                     + (reset_hour || ' hours')::interval
                   ) AT TIME ZONE reset_tz
                 THEN budget
                 -- Window still active
                 ELSE budget - consumed
               END AS remaining
        FROM resource_budgets
    ),
    next_task AS (
        SELECT t.id
        FROM tasks t
        LEFT JOIN budget_check bc ON bc.resource_type = t.resource_type
        WHERE t.state = 'pending'
          AND t.resource_type = :target_resource
          AND bc.remaining > 0
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

# SQL: claim any pending task (for tasks with NULL resource_type, or fallback)
_CLAIM_ANY_SQL = text("""
    WITH budget_check AS (
        SELECT resource_type,
               CASE
                 WHEN backoff_until IS NOT NULL AND now() < backoff_until
                 THEN 0
                 WHEN reset_mode = 'rolling'
                   AND now() >= period_start + (period_hours || ' hours')::interval
                 THEN budget
                 WHEN reset_mode = 'calendar'
                   AND period_start < (
                     date_trunc('day', now() AT TIME ZONE reset_tz)
                     + (reset_hour || ' hours')::interval
                   ) AT TIME ZONE reset_tz
                   AND now() >= (
                     date_trunc('day', now() AT TIME ZONE reset_tz)
                     + (reset_hour || ' hours')::interval
                   ) AT TIME ZONE reset_tz
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

def claim_next_task(worker_id: str, resource_type: str | None = None) -> dict | None:
    """Claim the next available task, optionally for a specific resource type.

    Budget is NOT decremented here — it is tracked per actual API call
    at the call site via acquire_budget(). The claim query only checks
    remaining budget as a gate to avoid claiming work we can't execute.
    """
    with engine.connect() as conn:
        if resource_type:
            row = conn.execute(
                _CLAIM_FOR_RESOURCE_SQL,
                {"worker_id": worker_id, "target_resource": resource_type},
            ).mappings().fetchone()
        else:
            row = conn.execute(
                _CLAIM_ANY_SQL, {"worker_id": worker_id},
            ).mappings().fetchone()
        if row is None:
            conn.commit()
            return None
        task = dict(row)
        conn.commit()
        return task


def mark_done(task_id: int, result: dict | None = None) -> None:
    """Mark a task as successfully completed."""
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


async def _heartbeat_loop(task_id: int) -> None:
    """Background coroutine that heartbeats a task every 60 seconds."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        try:
            heartbeat(task_id)
        except Exception:
            pass


async def _execute_task(task: dict, handlers: dict) -> None:
    """Execute a single task with heartbeating, error handling, and logging."""
    task_id = task["id"]
    task_type = task["task_type"]
    subject = task.get("subject_id", "")

    handler = handlers.get(task_type)
    if handler is None:
        mark_failed(task_id, f"Unknown task type: {task_type}")
        logger.error(f"Unknown task type: {task_type}")
        return

    hb_task = asyncio.create_task(_heartbeat_loop(task_id))
    try:
        result = await handler(task)
        mark_done(task_id, result)
        logger.info(f"Completed task {task_id}: {task_type} {subject} -> {result}")
    except (ResourceExhaustedError, ResourceThrottledError) as e:
        # Infrastructure signals — requeue without counting as a retry.
        # The worker will stop claiming tasks for this resource until
        # the budget resets or backoff expires.
        requeue(task_id, str(e))
        logger.info(f"Task {task_id} requeued ({type(e).__name__}): {e}")
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
    finally:
        hb_task.cancel()


# Resource types that can run concurrently. Each gets its own slot.
# Tasks sharing a resource type are serialised (only one active at a time).
CONCURRENT_RESOURCES = [
    "github_api",
    "gemini",
    "openai",
    "pypi",
    "npm",
    "huggingface",
    "dockerhub",
    "hn_algolia",
    "db_only",
]


async def worker_loop() -> None:
    """Main worker loop with resource-aware concurrency.

    Maintains one active task per resource type. When a resource slot
    is free, claims the highest-priority task for that resource.
    Different resources run in parallel.
    """
    from app.queue.handlers import TASK_HANDLERS

    logger.info(f"Task queue worker starting: {WORKER_ID} "
                f"({len(CONCURRENT_RESOURCES)} resource slots)")

    # Track running tasks: resource_type -> asyncio.Task
    running: dict[str, asyncio.Task] = {}

    while True:
        # Try to fill empty resource slots
        claimed_any = False
        for resource in CONCURRENT_RESOURCES:
            if resource in running and not running[resource].done():
                continue  # slot occupied

            # Clean up finished slot
            if resource in running:
                del running[resource]

            task = claim_next_task(WORKER_ID, resource_type=resource)
            if task:
                logger.info(
                    f"Claimed task {task['id']}: {task['task_type']} "
                    f"{task.get('subject_id', '')} [resource={resource}]"
                )
                running[resource] = asyncio.create_task(
                    _execute_task(task, TASK_HANDLERS)
                )
                claimed_any = True

        if not claimed_any and not running:
            # Nothing running, nothing to claim — sleep
            await asyncio.sleep(POLL_INTERVAL)
        elif running:
            # Wait for any task to complete, then loop to refill slots
            done, _ = await asyncio.wait(
                running.values(),
                timeout=POLL_INTERVAL,
                return_when=asyncio.FIRST_COMPLETED,
            )
            # Clean up completed slots
            for resource in list(running):
                if running[resource].done():
                    del running[resource]
        else:
            # Nothing running but we claimed something — tasks are starting
            await asyncio.sleep(0.1)
