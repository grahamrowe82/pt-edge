"""Enrich task: generate a landscape brief for an ecosystem layer via Gemini.

Delegates to the existing generate_landscape_briefs() function which
handles all layers in one pass with staleness detection via
generation_hash.

Previously ran only on Sundays. Now staleness-driven: the scheduler
creates a task when any layer's brief is >7 days old or missing.
This is a coarse-grained task — one task processes all 10 layers.
"""
import logging

from app.settings import settings

logger = logging.getLogger(__name__)


async def handle_enrich_landscape_brief(task: dict) -> dict:
    """Generate landscape briefs for all ecosystem layers.

    subject_id is unused (coarse-grained task — processes all layers).
    The existing function handles staleness via generation_hash internally.

    Returns the result dict from generate_landscape_briefs().
    Raises RuntimeError on failure.
    """
    if not settings.GEMINI_API_KEY:
        return {"status": "skipped", "reason": "no API key"}

    from app.ingest.landscape_briefs import generate_landscape_briefs
    result = await generate_landscape_briefs()
    return result
