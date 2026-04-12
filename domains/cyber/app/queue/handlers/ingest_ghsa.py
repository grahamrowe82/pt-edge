"""Handler: GitHub Security Advisories ingest."""

import logging

logger = logging.getLogger(__name__)


async def handle_ingest_ghsa(task: dict) -> dict:
    """Paginate GitHub Security Advisories for fix versions."""
    logger.info("Running GHSA ingest via task queue")
    from domains.cyber.app.ingest.ghsa import ingest_ghsa
    return await ingest_ghsa()
