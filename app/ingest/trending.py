"""Discover trending AI repos via GitHub search API."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from app.db import engine, SessionLocal
from app.github_client import get_github_client
from app.models import SyncLog

logger = logging.getLogger(__name__)

TOPICS = [
    "machine-learning", "llm", "ai", "deep-learning",
    "generative-ai", "large-language-model",
    "ai-agent", "chatbot", "autonomous-agent", "mcp",
    "rag", "vector-database",
    "mcp-server", "model-context-protocol",
    "ai-security", "llm-security",
]


async def ingest_trending() -> dict:
    """Search GitHub for trending AI repos not yet tracked."""
    started_at = datetime.now(timezone.utc)

    session = SessionLocal()
    try:
        # Get all tracked GitHub repos
        tracked = set()
        rows = session.execute(text(
            "SELECT LOWER(github_owner || '/' || github_repo) FROM projects WHERE github_owner IS NOT NULL"
        )).fetchall()
        for (key,) in rows:
            tracked.add(key)

        # Also get already-known candidates
        existing = set()
        rows = session.execute(text("SELECT github_url FROM project_candidates")).fetchall()
        for (url,) in rows:
            existing.add(url.lower())
    finally:
        session.close()

    logger.info(f"Searching GitHub trending for {len(TOPICS)} AI topics")

    candidates = []
    error_count = 0
    gh = get_github_client()

    semaphore = asyncio.Semaphore(2)
    for topic in TOPICS:
        async with semaphore:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

            try:
                resp = await gh.get(
                    "/search/repositories",
                    caller="ingest.trending",
                    params={
                        "q": f"topic:{topic} pushed:>{cutoff}",
                        "sort": "stars",
                        "per_page": 30,
                    },
                )
                if resp.status_code != 200:
                    logger.warning(f"GitHub search failed for topic {topic}: {resp.status_code}")
                    error_count += 1
                    continue

                data = resp.json()
                for repo in data.get("items", []):
                    owner = repo["owner"]["login"]
                    name = repo["name"]
                    full = f"{owner}/{name}".lower()
                    github_url = f"https://github.com/{owner}/{name}"

                    if full in tracked or github_url.lower() in existing:
                        continue

                    candidates.append({
                        "github_url": github_url,
                        "github_owner": owner,
                        "github_repo": name,
                        "name": repo.get("name"),
                        "description": (repo.get("description") or "")[:500],
                        "stars": repo.get("stargazers_count", 0),
                        "language": repo.get("language"),
                        "topics": repo.get("topics") or [],
                        "source": "trending",
                        "source_detail": f"GitHub topic: {topic}",
                    })
                    existing.add(github_url.lower())  # dedupe across topics

            except Exception as e:
                error_count += 1
                logger.error(f"Error searching topic {topic}: {e}")

            await asyncio.sleep(2)  # Rate limit: 10 search requests/min

    # Batch insert candidates
    if candidates:
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO project_candidates
                        (github_url, github_owner, github_repo, name, description, stars, language, topics, source, source_detail)
                    VALUES
                        (:github_url, :github_owner, :github_repo, :name, :description, :stars, :language, :topics, :source, :source_detail)
                    ON CONFLICT (github_url) DO NOTHING
                """),
                candidates,
            )
            conn.commit()
        logger.info(f"Batch wrote {len(candidates)} trending candidates")

    # Log sync
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="trending",
            status="success" if error_count == 0 else "partial",
            records_written=len(candidates),
            error_message=f"{error_count} failures" if error_count else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    logger.info(f"Trending ingest complete: {len(candidates)} candidates, {error_count} errors")
    return {"candidates_discovered": len(candidates), "errors": error_count}
