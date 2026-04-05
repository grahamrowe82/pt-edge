"""Legacy ingest runner — all jobs now delegated to the task queue.

This file is retained during the migration period so that ingest_all.py
and ingest_worker.py continue to work. All actual work is done by the
task queue (app/queue/). This runner just logs delegation messages and
writes sync_log entries for backwards compatibility.

Will be deleted in Wave 8 when ingest_worker.py is simplified to only
run the task queue.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [10, 30, 60]  # seconds — exponential-ish backoff
INGEST_LOCK_ID = 8675309  # Postgres advisory lock ID

# Held open for the duration of run_all() to keep the advisory lock alive.
_lock_conn = None


def acquire_ingest_lock() -> bool:
    """Try to acquire a Postgres advisory lock. Returns True if acquired."""
    global _lock_conn
    from sqlalchemy import text
    from app.db import engine

    _lock_conn = engine.connect()
    acquired = _lock_conn.execute(
        text("SELECT pg_try_advisory_lock(:id)"), {"id": INGEST_LOCK_ID}
    ).scalar()
    if not acquired:
        _lock_conn.close()
        _lock_conn = None
    return acquired


def release_ingest_lock():
    """Release the advisory lock by closing the dedicated connection."""
    global _lock_conn
    if _lock_conn is not None:
        _lock_conn.close()
        _lock_conn = None


async def run_all() -> dict:
    """Legacy entry point — all jobs are now handled by the task queue.

    This function exists only for backwards compatibility with
    ingest_all.py and ingest_worker.py. It logs that all jobs have
    been delegated and returns immediately.
    """
    results = {}

    logger.info("Legacy runner invoked — all jobs delegated to task queue")

    # All 49 jobs are now handled by the task queue worker.
    # See app/queue/handlers/ and docs/design/worker-architecture.md
    delegated_jobs = [
        "github", "downloads", "dockerhub", "vscode", "huggingface",
        "hn", "v2ex", "trending", "candidate_velocity",
        "hf_datasets", "hf_models", "public_apis", "api_specs",
        "package_deps", "dep_velocity", "builder_tools", "npm_mcp",
        "ai_repo_downloads", "ai_repo_commits", "candidate_watchlist",
        "ai_repo_package_detect", "newsletters", "releases",
        "gsc", "umami", "coview",
        "hn_backfill", "hn_lab_backfill", "hn_llm_match",
        "v2ex_lab_backfill",
        "subcategory", "subcategory_llm", "stack_layer",
        "domain_reassign", "project_linking", "models",
        "embeddings", "views", "content_budget",
        "ai_summaries", "comparison_sentences", "repo_briefs",
        "dataset_export", "project_briefs",
        "domain_briefs", "landscape_briefs",
        "briefing_refresh", "static_site",
        "ai_repo_created_at",
    ]

    for name in delegated_jobs:
        results[name] = {"status": "handled_by_task_queue"}

    logger.info(f"All {len(delegated_jobs)} jobs delegated to task queue")
    return results
