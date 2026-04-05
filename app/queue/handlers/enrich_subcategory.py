"""Enrich task: classify repos by subcategory (regex + LLM fallback).

Coarse-grained — delegates to the existing ingest_subcategories() (regex)
and classify_subcategory_llm() (LLM fallback, batches of 30) functions.
"""
import logging

logger = logging.getLogger(__name__)


async def handle_enrich_subcategory(task: dict) -> dict:
    """Run subcategory classification: regex pass then LLM fallback.

    subject_id is unused (coarse-grained task).
    """
    from app.ingest.ai_repo_subcategory import ingest_subcategories, classify_subcategory_llm

    regex_result = await ingest_subcategories()
    llm_result = await classify_subcategory_llm()

    return {"regex": regex_result, "llm": llm_result}
