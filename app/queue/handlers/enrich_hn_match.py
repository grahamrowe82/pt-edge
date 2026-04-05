"""Enrich task: match HN posts to projects/labs via Gemini.

Coarse-grained — delegates to the existing match_hn_posts_llm()
function which handles batching (20 per LLM call) internally.
"""
import logging

logger = logging.getLogger(__name__)


async def handle_enrich_hn_match(task: dict) -> dict:
    """Match unlinked HN posts to projects and labs via LLM.

    subject_id is unused (coarse-grained task).
    """
    from app.ingest.hn_llm_match import match_hn_posts_llm
    result = await match_hn_posts_llm()
    return result
