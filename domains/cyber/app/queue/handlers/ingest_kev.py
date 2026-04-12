"""Handler: CISA KEV catalog ingest."""

import logging

logger = logging.getLogger(__name__)


async def handle_ingest_kev(task: dict) -> dict:
    """Download CISA KEV catalog and mark matching CVEs."""
    logger.info("Running KEV ingest via task queue")
    from domains.cyber.app.ingest.kev import ingest_kev
    return await ingest_kev()
