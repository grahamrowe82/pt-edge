"""Generic embedding service for *-edge semantic search.

Thin async module wrapping OpenAI text-embedding-3-large.
All errors return None -- never raises. DB is the cache.

Domain-specific build_*_text() helpers live in the domain's embeddings module.
"""

import logging
from typing import Optional

from app.settings import settings

logger = logging.getLogger(__name__)

MODEL = "text-embedding-3-large"
DIMENSIONS = 1536  # truncate to match existing pgvector columns
MAX_BATCH_SIZE = 2048  # OpenAI batch limit
MAX_TEXT_CHARS = 6000  # ~8191 tokens ~ 6K chars conservative limit


def is_enabled() -> bool:
    """True if OPENAI_API_KEY is set."""
    return bool(settings.OPENAI_API_KEY)


async def embed_one(text: str, dimensions: int = DIMENSIONS) -> Optional[list[float]]:
    """Embed a single text. Returns None if disabled or on error."""
    if not is_enabled():
        return None
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        resp = await client.embeddings.create(input=[text], model=MODEL, dimensions=dimensions)
        return resp.data[0].embedding
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        return None


async def embed_batch(texts: list[str], dimensions: int = DIMENSIONS) -> list[Optional[list[float]]]:
    """Embed multiple texts. Chunks to MAX_BATCH_SIZE. Returns aligned list.

    Truncates texts beyond MAX_TEXT_CHARS. On chunk failure, retries
    individually so only truly problematic texts get None.
    """
    if not is_enabled():
        return [None] * len(texts)

    # Truncate overly long texts to avoid token limit errors
    safe_texts = [t[:MAX_TEXT_CHARS] if len(t) > MAX_TEXT_CHARS else t for t in texts]

    results: list[Optional[list[float]]] = [None] * len(safe_texts)

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    from app.core.ingest.budget import acquire_budget, record_call, ResourceExhaustedError

    for start in range(0, len(safe_texts), MAX_BATCH_SIZE):
        chunk = safe_texts[start:start + MAX_BATCH_SIZE]
        try:
            if not await acquire_budget("openai"):
                raise ResourceExhaustedError("openai")
            resp = await client.embeddings.create(input=chunk, model=MODEL, dimensions=dimensions)
            await record_call("openai")
            for item in resp.data:
                results[start + item.index] = item.embedding
        except Exception as e:
            logger.warning(f"Batch chunk failed (offset {start}, size {len(chunk)}): {e}")
            # Retry individually -- isolate the bad text(s)
            for i, t in enumerate(chunk):
                try:
                    if not await acquire_budget("openai"):
                        raise ResourceExhaustedError("openai")
                    resp = await client.embeddings.create(
                        input=[t], model=MODEL, dimensions=dimensions,
                    )
                    await record_call("openai")
                    results[start + i] = resp.data[0].embedding
                except Exception as e2:
                    logger.warning(f"Individual embed failed (index {start + i}): {e2}")
                    # This text is truly un-embeddable -- leave as None

    return results
