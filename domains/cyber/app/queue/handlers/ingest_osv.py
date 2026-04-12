"""Handler: OSV.dev vulnerability data ingest."""

import logging

logger = logging.getLogger(__name__)


async def handle_ingest_osv(task: dict) -> dict:
    """Query OSV for fix information on CVEs."""
    logger.info("Running OSV ingest via task queue")
    from domains.cyber.app.ingest.osv import ingest_osv
    return await ingest_osv()
