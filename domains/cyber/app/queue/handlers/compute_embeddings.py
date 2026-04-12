"""Handler: compute embeddings for all entity types + auto-categorize."""

import logging

logger = logging.getLogger(__name__)


async def handle_compute_embeddings(task: dict) -> dict:
    """Backfill embeddings for entities with NULL embedding, then run clustering."""
    logger.info("Computing embeddings via task queue")

    from domains.cyber.app.backfill_embeddings import backfill_all
    embed_results = await backfill_all()

    # Only run categorization if we actually embedded something
    cat_results = {}
    if embed_results.get("total", 0) > 0:
        logger.info("Running auto-categorization on freshly embedded entities")
        from domains.cyber.app.ingest.categorize import categorize_entities
        cat_results = await categorize_entities()

    return {
        "embeddings": embed_results,
        "categorization": cat_results,
    }
