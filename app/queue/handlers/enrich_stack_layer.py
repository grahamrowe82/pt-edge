"""Enrich task: classify repos by AI stack layer via Gemini.

Coarse-grained — delegates to the existing classify_stack_layers()
function which handles batching (30 per LLM call) internally.
"""
import logging

logger = logging.getLogger(__name__)


async def handle_enrich_stack_layer(task: dict) -> dict:
    """Classify repos by AI stack layer.

    subject_id is unused (coarse-grained task).
    """
    from app.ingest.stack_layer import classify_stack_layers
    result = await classify_stack_layers()
    return result
