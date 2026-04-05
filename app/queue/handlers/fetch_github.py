"""Fetch task: refresh GitHub metadata for all active projects.

Coarse-grained — delegates to the existing ingest_github() function
which handles concurrency (semaphore 5), rate limit pre-flight checks,
and batch writes internally. Completes in ~5 minutes.
"""
import logging

logger = logging.getLogger(__name__)


async def handle_fetch_github(task: dict) -> dict:
    """Refresh GitHub metadata for all active projects.

    subject_id is unused (coarse-grained task).
    """
    from app.ingest.github import ingest_github
    result = await ingest_github()
    return result
