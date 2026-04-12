"""Handler: bulk NVD CVE ingest (CVEs, software, vendors, weakness links)."""

import logging

logger = logging.getLogger(__name__)


async def handle_ingest_nvd(task: dict) -> dict:
    """Run full NVD ingest. Detects bootstrap vs incremental."""
    logger.info("Running NVD ingest via task queue")
    from domains.cyber.app.ingest.nvd import ingest_nvd
    return await ingest_nvd()
