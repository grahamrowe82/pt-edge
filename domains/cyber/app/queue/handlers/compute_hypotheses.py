"""Handler: compute hypothesis engine insights."""

import logging

logger = logging.getLogger(__name__)


async def handle_compute_hypotheses(task: dict) -> dict:
    """Compute all 4 hypothesis types, score, and cache for site generation."""
    logger.info("Computing hypotheses via task queue")
    from domains.cyber.app.ingest.compute_hypotheses import compute_all_hypotheses
    return await compute_all_hypotheses()
