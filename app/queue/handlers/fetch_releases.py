"""Fetch task: fetch releases and generate summaries for all projects.

Coarse-grained — delegates to the existing ingest_releases() function
which handles GitHub API fetching, deduplication, LLM summarisation,
and embedding internally.
"""
import logging

logger = logging.getLogger(__name__)


async def handle_fetch_releases(task: dict) -> dict:
    """Fetch releases and generate summaries for all projects.

    subject_id is unused (coarse-grained task).
    """
    from app.ingest.releases import ingest_releases
    result = await ingest_releases()
    return result
