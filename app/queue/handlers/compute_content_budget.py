"""Compute task: recompute content budget from allocation scores.

Pure compute — reads from mv_allocation_scores, writes to content_budget.
No external API calls. Must run after MV refresh.
"""
import logging

logger = logging.getLogger(__name__)


async def handle_compute_content_budget(task: dict) -> dict:
    """Recompute the content budget allocation table.

    subject_id is unused (coarse-grained task).
    Runs in a thread so the event loop stays responsive.
    """
    import asyncio
    from app.allocation.budget import compute_and_write_budget
    from app.settings import settings
    result = await asyncio.to_thread(compute_and_write_budget, settings.LLM_BUDGET_MULTIPLIER)
    return result
