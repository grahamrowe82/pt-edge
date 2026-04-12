"""Cyber-domain task queue worker with resource-aware concurrency.

Patches app.db to point at the cyber database before importing the core
worker loop, so that task claiming and heartbeats hit the right DB.
"""
import logging

# CRITICAL: patch app.db before importing the core worker so that
# claim_next_task / mark_done / heartbeat use the cyber database.
import app.db as _app_db
from domains.cyber.app.db import engine, SessionLocal, readonly_engine

_app_db.engine = engine
_app_db.SessionLocal = SessionLocal
_app_db.readonly_engine = readonly_engine

from app.core.queue.worker import run_worker_loop  # noqa: E402

logger = logging.getLogger(__name__)

# Resource types that can run concurrently for cyber domain.
CONCURRENT_RESOURCES = [
    "nvd",
    "osv_ghsa",
    "exploit_db",
    "openai",
    "db_only",
]


async def worker_loop() -> None:
    """Main worker loop for cyber domain."""
    from domains.cyber.app.queue.handlers import TASK_HANDLERS
    await run_worker_loop(TASK_HANDLERS, CONCURRENT_RESOURCES)
