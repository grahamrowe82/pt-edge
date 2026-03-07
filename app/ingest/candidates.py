"""Re-score pending project candidates by re-fetching their GitHub star counts.

This enables velocity tracking: by comparing the current star count to the
previous value, radar() can surface candidates that are exploding in popularity.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

# Only re-score candidates discovered more than 24h ago (need a baseline first)
MIN_AGE = timedelta(hours=24)


async def _rescore_candidate(
    client: httpx.AsyncClient, candidate: dict, semaphore: asyncio.Semaphore,
) -> dict | None:
    """Fetch current star count for a candidate repo."""
    owner = candidate.get("github_owner")
    repo = candidate.get("github_repo")
    if not owner or not repo:
        return None

    async with semaphore:
        try:
            resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error fetching {owner}/{repo}: {e}")
            return None

    if resp.status_code != 200:
        logger.warning(f"GitHub API {resp.status_code} for candidate {owner}/{repo}")
        return None

    data = resp.json()
    new_stars = data.get("stargazers_count", 0)
    old_stars = candidate.get("stars") or 0

    return {
        "id": candidate["id"],
        "stars_previous": old_stars,
        "stars": new_stars,
    }


async def ingest_candidate_velocity() -> dict:
    """Re-fetch star counts for pending candidates to track velocity."""
    started_at = datetime.now(timezone.utc)
    cutoff = datetime.now(timezone.utc) - MIN_AGE

    # Get pending candidates old enough to have a baseline
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, github_owner, github_repo, stars
            FROM project_candidates
            WHERE status = 'pending'
              AND discovered_at < :cutoff
            ORDER BY stars DESC NULLS LAST
        """), {"cutoff": cutoff}).fetchall()

    candidates = [dict(r._mapping) for r in rows]
    logger.info(f"Re-scoring {len(candidates)} pending candidates")

    if not candidates:
        return {"rescored": 0, "errors": 0}

    headers = {"User-Agent": "pt-edge/1.0"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    semaphore = asyncio.Semaphore(5)
    async with httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True) as client:
        tasks = [_rescore_candidate(client, c, semaphore) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    updates = []
    error_count = 0
    for r in results:
        if isinstance(r, Exception):
            error_count += 1
            logger.error(f"Rescore error: {r}")
        elif r is not None:
            updates.append(r)

    # Batch update
    if updates:
        with engine.connect() as conn:
            for u in updates:
                conn.execute(text("""
                    UPDATE project_candidates
                    SET stars_previous = :stars_previous,
                        stars = :stars,
                        stars_updated_at = NOW()
                    WHERE id = :id
                """), u)
            conn.commit()
        logger.info(f"Updated {len(updates)} candidate star counts")

    # Log sync
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="candidate_velocity",
            status="success" if error_count == 0 else "partial",
            records_written=len(updates),
            error_message=f"{error_count} failures" if error_count else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    logger.info(f"Candidate velocity complete: {len(updates)} rescored, {error_count} errors")
    return {"rescored": len(updates), "errors": error_count}
