import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import HNPost, Project, SyncLog

logger = logging.getLogger(__name__)

ALGOLIA_API = "https://hn.algolia.com/api/v1/search_by_date"

SEARCH_TERMS = [
    "LLM",
    "GPT",
    "Claude",
    "Anthropic",
    "OpenAI",
    "Gemini",
    "AI model",
    "machine learning",
    "transformer model",
    "fine-tuning",
    "RAG",
    "vector database",
    "AI agent",
]

SECONDS_IN_7_DAYS = 7 * 24 * 60 * 60


def _determine_post_type(title: str) -> str:
    """Determine HN post type from title prefix."""
    title_lower = title.lower()
    if title_lower.startswith("show hn:"):
        return "show"
    if title_lower.startswith("ask hn:"):
        return "ask"
    return "link"


def _match_project(title: str, projects: list[Project]) -> int | None:
    """Try to match a HN post title to a project by name or slug (case-insensitive)."""
    title_lower = title.lower()
    for project in projects:
        # Check both name and slug for matches
        if project.name and project.name.lower() in title_lower:
            return project.id
        if project.slug and project.slug.lower() in title_lower:
            return project.id
    return None


async def fetch_hn_page(
    client: httpx.AsyncClient, query: str, min_timestamp: int, page: int = 0
) -> dict | None:
    """Fetch a single page of HN search results from Algolia API."""
    params = {
        "query": query,
        "tags": "story",
        "numericFilters": f"points>10,created_at_i>{min_timestamp}",
        "hitsPerPage": 50,
        "page": page,
    }
    resp = await client.get(ALGOLIA_API, params=params)
    if resp.status_code == 200:
        return resp.json()
    logger.warning(f"HN Algolia API {resp.status_code} for query '{query}' page {page}")
    return None


async def ingest_hn_for_term(
    client: httpx.AsyncClient,
    term: str,
    min_timestamp: int,
    projects: list[Project],
    semaphore: asyncio.Semaphore,
) -> int:
    """Fetch and store HN posts for a single search term. Returns count of new posts stored."""
    async with semaphore:
        data = await fetch_hn_page(client, term, min_timestamp)
        await asyncio.sleep(1.0)  # rate limit: 1s between Algolia requests

    if not data:
        return 0

    hits = data.get("hits", [])
    if not hits:
        return 0

    new_count = 0
    session = SessionLocal()
    try:
        for hit in hits:
            hn_id = hit.get("objectID")
            title = hit.get("title")
            if not hn_id or not title:
                continue

            try:
                hn_id_int = int(hn_id)
            except (ValueError, TypeError):
                continue

            created_at_i = hit.get("created_at_i")
            if not created_at_i:
                continue

            posted_at = datetime.fromtimestamp(created_at_i, tz=timezone.utc)
            project_id = _match_project(title, projects)

            post = HNPost(
                hn_id=hn_id_int,
                title=title,
                url=hit.get("url"),
                author=hit.get("author", "unknown"),
                points=hit.get("points", 0),
                num_comments=hit.get("num_comments", 0),
                post_type=_determine_post_type(title),
                posted_at=posted_at,
                project_id=project_id,
            )
            session.add(post)

            try:
                session.flush()
                new_count += 1
            except IntegrityError:
                # Post already exists (unique constraint on hn_id), skip it
                session.rollback()
                continue

        session.commit()
    except Exception:
        session.rollback()
        logger.exception(f"Failed to save HN posts for term '{term}'")
        raise
    finally:
        session.close()

    return new_count


async def ingest_hn() -> dict:
    """Fetch recent AI-related Hacker News posts across all search terms."""
    # Load all active projects for matching
    session = SessionLocal()
    projects = session.query(Project).filter(Project.is_active.is_(True)).all()
    session.close()

    min_timestamp = int(time.time()) - SECONDS_IN_7_DAYS

    logger.info(f"Ingesting HN posts for {len(SEARCH_TERMS)} search terms")
    started_at = datetime.now(timezone.utc)
    success_count = 0
    error_count = 0

    headers = {"User-Agent": "pt-edge/1.0"}
    semaphore = asyncio.Semaphore(2)  # conservative concurrency for Algolia

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        tasks = [ingest_hn_for_term(client, term, min_timestamp, projects, semaphore) for term in SEARCH_TERMS]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                error_count += 1
                logger.error(f"HN ingest error: {r}")
            elif isinstance(r, int):
                success_count += r
            else:
                error_count += 1

    # Log sync
    session = SessionLocal()
    try:
        log = SyncLog(
            sync_type="hn",
            status="success" if error_count == 0 else "partial",
            records_written=success_count,
            error_message=f"{error_count} failures" if error_count else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        session.add(log)
        session.commit()
    finally:
        session.close()

    logger.info(f"HN ingest complete: {success_count} new posts, {error_count} errors")
    return {"success": success_count, "errors": error_count}
