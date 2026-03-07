import asyncio
import logging

from app.ingest.downloads import ingest_downloads
from app.ingest.github import ingest_github
from app.ingest.hn import ingest_hn
from app.ingest.releases import ingest_releases

logger = logging.getLogger(__name__)


async def run_all() -> dict:
    """Run all ingest jobs sequentially."""
    results = {}

    logger.info("Starting full ingest cycle")

    for name, coro in [
        ("github", ingest_github()),
        ("downloads", ingest_downloads()),
        ("releases", ingest_releases()),
        ("hn", ingest_hn()),
    ]:
        try:
            results[name] = await coro
            logger.info(f"{name}: {results[name]}")
        except Exception as e:
            logger.exception(f"{name} failed: {e}")
            results[name] = {"error": str(e)}

    logger.info(f"Full ingest complete: {results}")
    return results
