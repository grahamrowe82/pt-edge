"""Handler: EPSS daily scores ingest."""

import logging

logger = logging.getLogger(__name__)


async def handle_ingest_epss(task: dict) -> dict:
    """Download EPSS scores and update all CVEs."""
    logger.info("Running EPSS ingest via task queue")
    from domains.cyber.app.ingest.epss import ingest_epss
    return await ingest_epss()
