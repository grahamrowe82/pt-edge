"""Enrich task: backfill embeddings for all tables via OpenAI.

Delegates to the existing backfill functions which handle candidate
selection (WHERE embedding IS NULL) and batch API calls internally.
Uses OpenAI API so resource_type is 'openai'.
"""
import logging

logger = logging.getLogger(__name__)


async def handle_compute_embeddings(task: dict) -> dict:
    """Backfill embeddings for all tables with missing embeddings.

    subject_id is unused (coarse-grained task).
    """
    from app.embeddings import is_enabled
    if not is_enabled():
        return {"status": "skipped", "reason": "no OPENAI_API_KEY"}

    from app.backfill_embeddings import (
        backfill_projects, backfill_methodology, backfill_ai_repos,
        backfill_public_apis, backfill_hf_datasets, backfill_hf_models,
    )

    results = {
        "projects": await backfill_projects(),
        "methodology": await backfill_methodology(),
        "ai_repos": await backfill_ai_repos(),
        "public_apis": await backfill_public_apis(),
        "hf_datasets": await backfill_hf_datasets(),
        "hf_models": await backfill_hf_models(),
    }
    return results
