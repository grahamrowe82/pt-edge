"""Embedding service for PT-Edge semantic search.

Thin async module wrapping OpenAI text-embedding-3-small.
All errors return None — never raises. DB is the cache.

Usage:
    from app.embeddings import embed_one, embed_batch, build_project_text, is_enabled

    if is_enabled():
        text = build_project_text(name, description, topics, category, language)
        vec = await embed_one(text)
"""

import logging
from typing import Optional

from app.settings import settings

logger = logging.getLogger(__name__)

MODEL = "text-embedding-3-small"
MAX_BATCH_SIZE = 2048  # OpenAI batch limit


def is_enabled() -> bool:
    """True if OPENAI_API_KEY is set."""
    return bool(settings.OPENAI_API_KEY)


def build_project_text(
    name: str,
    description: str | None,
    topics: list[str] | None,
    category: str | None,
    language: str | None,
) -> str:
    """Single source of truth for what goes into a project embedding.

    Changing this format = need to regenerate all embeddings.
    """
    parts = [name or ""]
    if description:
        parts[0] += f": {description}"
    if topics:
        parts.append(f"Topics: {', '.join(topics)}")
    if category:
        parts.append(f"Category: {category}")
    if language:
        parts.append(f"Language: {language}")
    return ". ".join(parts) + "."


def build_methodology_text(
    topic: str,
    title: str,
    summary: str,
    category: str,
) -> str:
    """What goes into a methodology embedding. Uses summary, not full detail."""
    return f"{title}. {summary}. Category: {category}. Topic: {topic}."


async def embed_one(text: str) -> Optional[list[float]]:
    """Embed a single text. Returns None if disabled or on error."""
    if not is_enabled():
        return None
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        resp = await client.embeddings.create(input=[text], model=MODEL)
        return resp.data[0].embedding
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        return None


async def embed_batch(texts: list[str]) -> list[Optional[list[float]]]:
    """Embed multiple texts. Chunks to MAX_BATCH_SIZE. Returns aligned list."""
    if not is_enabled():
        return [None] * len(texts)

    results: list[Optional[list[float]]] = [None] * len(texts)

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

        for start in range(0, len(texts), MAX_BATCH_SIZE):
            chunk = texts[start:start + MAX_BATCH_SIZE]
            resp = await client.embeddings.create(input=chunk, model=MODEL)
            for item in resp.data:
                results[start + item.index] = item.embedding

    except Exception as e:
        logger.error(f"Batch embedding error: {e}")
        # results remain None for any unprocessed items

    return results
