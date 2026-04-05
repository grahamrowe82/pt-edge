"""Enrich task: generate project intelligence briefs via Gemini.

Delegates to the existing generate_project_briefs() function which is
already a pure enrich operation (reads DB, calls LLM, writes DB).

This is a coarse-grained task — one task generates briefs for up to
MAX_BRIEFS_PER_RUN projects (default 100) in batches of 10. The existing
function handles candidate selection, staleness detection via
generation_hash, and batch LLM calls internally.
"""
import logging

from app.settings import settings

logger = logging.getLogger(__name__)


async def handle_enrich_project_brief(task: dict) -> dict:
    """Generate project briefs for stale/missing projects.

    subject_id is unused (coarse-grained task).

    Returns the result dict from generate_project_briefs().
    Raises RuntimeError on failure.
    """
    if not settings.GEMINI_API_KEY:
        return {"status": "skipped", "reason": "no API key"}

    from app.ingest.project_briefs import generate_project_briefs
    result = await generate_project_briefs()
    return result
