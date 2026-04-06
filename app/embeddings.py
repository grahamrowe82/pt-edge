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
MAX_TEXT_CHARS = 6000  # ~8191 tokens ≈ 6K chars conservative limit


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


def build_briefing_text(
    slug: str,
    title: str,
    summary: str,
    domain: str,
) -> str:
    """What goes into a briefing embedding. Uses summary, not full detail."""
    return f"{title}. {summary}. Domain: {domain}. Slug: {slug}."


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


def build_hf_dataset_text(
    name: str,
    description: str | None,
    task_categories: list[str] | None,
    languages: list[str] | None,
) -> str:
    """What goes into a HuggingFace dataset embedding for discovery search."""
    parts = [name or ""]
    if description:
        parts[0] += f": {description[:500]}"
    if task_categories:
        parts.append(f"Tasks: {', '.join(task_categories)}")
    if languages:
        parts.append(f"Languages: {', '.join(languages)}")
    return ". ".join(parts) + "."


def build_hf_model_text(
    name: str,
    description: str | None,
    pipeline_tag: str | None,
    library_name: str | None,
    languages: list[str] | None,
) -> str:
    """What goes into a HuggingFace model embedding for discovery search."""
    parts = [name or ""]
    if description:
        parts[0] += f": {description[:500]}"
    if pipeline_tag:
        parts.append(f"Task: {pipeline_tag}")
    if library_name:
        parts.append(f"Library: {library_name}")
    if languages:
        parts.append(f"Languages: {', '.join(languages)}")
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

    from app.ingest.budget import acquire_budget, record_call, ResourceExhaustedError

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
            # Retry individually — isolate the bad text(s)
            for i, text in enumerate(chunk):
                try:
                    if not await acquire_budget("openai"):
                        raise ResourceExhaustedError("openai")
                    resp = await client.embeddings.create(
                        input=[text], model=MODEL, dimensions=dimensions,
                    )
                    await record_call("openai")
                    results[start + i] = resp.data[0].embedding
                except Exception as e2:
                    logger.warning(f"Individual embed failed (index {start + i}): {e2}")
                    # This text is truly un-embeddable — leave as None

    return results
