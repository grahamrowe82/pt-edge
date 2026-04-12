"""Embedding service for PT-Edge semantic search.

Thin async module wrapping OpenAI text-embedding-3-large.
All errors return None -- never raises. DB is the cache.

Usage:
    from app.embeddings import embed_one, embed_batch, build_project_text, is_enabled

    if is_enabled():
        text = build_project_text(name, description, topics, category, language)
        vec = await embed_one(text)
"""

# Generic embedding functions from core
from app.core.embeddings import (  # noqa: F401
    is_enabled,
    embed_one,
    embed_batch,
    MODEL,
    DIMENSIONS,
    MAX_BATCH_SIZE,
    MAX_TEXT_CHARS,
)


# ---------------------------------------------------------------------------
# Domain-specific text builders (PT-Edge only)
# ---------------------------------------------------------------------------

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
    """Legacy -- use build_ai_repo_text instead."""
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
        # Strip HTML tags and truncate -- some APIs.guru entries have full docs
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
