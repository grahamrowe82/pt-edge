"""Handler: pre-compute relationship pairs for static site generation."""

import logging

logger = logging.getLogger(__name__)


async def handle_compute_pairs(task: dict) -> dict:
    """Pre-compute CVE-software, vendor-weakness, and kill chain pairs."""
    logger.info("Computing relationship pairs via task queue")
    from domains.cyber.app.ingest.compute_pairs import compute_all_pairs
    return await compute_all_pairs()
