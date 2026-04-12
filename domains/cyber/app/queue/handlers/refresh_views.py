"""Handler: refresh all materialized views and capture score snapshots."""

import logging

logger = logging.getLogger(__name__)


async def handle_refresh_views(task: dict) -> dict:
    """Refresh all materialized views and capture daily score snapshots."""
    logger.info("Refreshing materialized views via task queue")
    from domains.cyber.app.views.refresh import refresh_all_views
    refresh_all_views()
    return {"status": "refreshed"}
