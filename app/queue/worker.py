"""Stateless task queue worker with resource-aware concurrency.

Runs multiple tasks concurrently when they use different resources.
A GitHub task and a Gemini task don't compete -- they run in parallel.
Tasks sharing a resource type are serialised by the claim query.

The worker maintains one active task per resource type. When a task
completes, it immediately claims the next one for that resource slot.
"""
import asyncio
import logging

from app.core.queue.worker import (  # noqa: F401
    WORKER_ID,
    POLL_INTERVAL,
    HEARTBEAT_INTERVAL,
    claim_next_task,
    mark_done,
    mark_failed,
    requeue,
    heartbeat,
    _heartbeat_loop,
    _execute_task,
    run_worker_loop,
)
from app.github_client import GitHubRateLimitError
from app.ingest.budget import record_throttle

logger = logging.getLogger(__name__)

# Resource types that can run concurrently. Each gets its own slot.
# Tasks sharing a resource type are serialised (only one active at a time).
CONCURRENT_RESOURCES = [
    "github_api",
    "github_search",
    "github_graphql",
    "gemini",
    "openai",
    "pypi",
    "npm",
    "huggingface",
    "dockerhub",
    "hn_algolia",
    "db_only",
    "vscode",
    "v2ex",
    "crates",
]


async def worker_loop() -> None:
    """Main worker loop with resource-aware concurrency.

    Maintains one active task per resource type. When a resource slot
    is free, claims the highest-priority task for that resource.
    Different resources run in parallel.
    """
    from app.queue.handlers import TASK_HANDLERS
    await run_worker_loop(TASK_HANDLERS, CONCURRENT_RESOURCES)
