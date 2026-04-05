"""Enrich task: detect package names for repos via Gemini + registry verification.

Coarse-grained — delegates to the existing detect_packages_llm()
function which handles batching (20 per LLM call) and registry
verification (PyPI/npm/crates.io) internally.
"""
import logging

logger = logging.getLogger(__name__)


async def handle_enrich_package_detect(task: dict) -> dict:
    """Detect package names for repos via LLM prediction + registry check.

    subject_id is unused (coarse-grained task).
    """
    from app.ingest.ai_repo_package_detect import detect_packages_llm
    result = await detect_packages_llm()
    return result
