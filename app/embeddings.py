"""Embedding service for PT-Edge semantic search.

Thin async module wrapping OpenAI text-embedding-3-large.
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

MODEL = "text-embedding-3-large"
DIMENSIONS = 1536  # truncate to match existing pgvector columns
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


def build_release_text(
    project_name: str,
    version: str | None,
    title: str,
    summary: str | None,
) -> str:
    """What goes into a release embedding. Uses project + version + title + summary."""
    parts = [project_name]
    if version:
        parts[0] += f" {version}"
    parts.append(title)
    if summary:
        parts.append(summary)
    return ". ".join(parts) + "."


def build_newsletter_text(
    title: str,
    summary: str | None,
    mentions: list[dict] | None,
) -> str:
    """What goes into a newsletter topic embedding. Uses title + summary + mention names."""
    parts = [title]
    if summary:
        parts.append(summary)
    if mentions:
        names = [m.get("name", "") for m in mentions if m.get("name")]
        if names:
            parts.append(f"Mentions: {', '.join(names)}")
    return ". ".join(parts) + "."


def build_mcp_server_text(
    name: str,
    description: str | None,
    topics: list[str] | None,
    language: str | None,
) -> str:
    """Legacy — use build_ai_repo_text instead."""
    return build_ai_repo_text(name=name, description=description, topics=topics, language=language)


def build_ai_repo_text(
    name: str,
    description: str | None,
    topics: list[str] | None,
    language: str | None,
    domain: str | None = None,
) -> str:
    """What goes into an AI repo embedding for discovery search."""
    parts = [name or ""]
    if description:
        parts[0] += f": {description}"
    if topics:
        parts.append(f"Topics: {', '.join(topics)}")
    if domain:
        parts.append(f"Domain: {domain}")
    if language:
        parts.append(f"Language: {language}")
    return ". ".join(parts) + "."


def build_public_api_text(
    title: str,
    description: str | None,
    categories: list[str] | None,
    provider: str | None,
) -> str:
    """What goes into a public API embedding for discovery search."""
    import re
    parts = [title or ""]
    if description:
        # Strip HTML tags and truncate — some APIs.guru entries have full docs
        desc = re.sub(r"<[^>]+>", "", description)[:500]
        parts[0] += f": {desc}"
    if categories:
        parts.append(f"Categories: {', '.join(categories)}")
    if provider:
        parts.append(f"Provider: {provider}")
    return ". ".join(parts) + "."


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
    """Embed multiple texts. Chunks to MAX_BATCH_SIZE. Returns aligned list."""
    if not is_enabled():
        return [None] * len(texts)

    results: list[Optional[list[float]]] = [None] * len(texts)

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

        for start in range(0, len(texts), MAX_BATCH_SIZE):
            chunk = texts[start:start + MAX_BATCH_SIZE]
            resp = await client.embeddings.create(input=chunk, model=MODEL, dimensions=dimensions)
            for item in resp.data:
                results[start + item.index] = item.embedding

    except Exception as e:
        logger.error(f"Batch embedding error: {e}")
        # results remain None for any unprocessed items

    return results
