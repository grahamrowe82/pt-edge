"""Compute task: refresh all materialized views.

Pure compute — reads from data tables, writes to materialized views.
No external API calls. Takes 1-3 minutes for all 35 views.
"""
import logging

logger = logging.getLogger(__name__)


async def handle_compute_mv_refresh(task: dict) -> dict:
    """Refresh all materialized views in dependency order.

    subject_id is unused (coarse-grained task).
    Runs in a thread so the event loop stays responsive (1-3 minutes).
    """
    import asyncio
    from app.views.refresh import refresh_all_views
    result = await asyncio.to_thread(refresh_all_views)
    return result
