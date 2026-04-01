"""Backfill ai_repos.created_at from GitHub REST API.

Self-draining: processes CHUNK_SIZE repos per daily run where created_at IS NULL,
prioritised by stars DESC. Once all repos have created_at, this step becomes a no-op.

At ~500 repos/run with 0.8s delay = ~7 minutes per run.
225K repos / 500 per day = ~450 days to complete the full backfill.
Increase CHUNK_SIZE to accelerate (stay under 5,000 GitHub API calls/hour).
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 500  # repos per daily run
CONCURRENCY = 5   # parallel GitHub API requests
REQUEST_DELAY = 0.4  # seconds between requests per worker


async def _fetch_created_at(
    client: httpx.AsyncClient,
    repo: dict,
    semaphore: asyncio.Semaphore,
) -> dict | None:
    """Fetch created_at for a single repo from GitHub REST API."""
    async with semaphore:
        try:
            resp = await client.get(
                f"https://api.github.com/repos/{repo['full_name']}"
            )
            if resp.status_code == 404:
                return None
            if resp.status_code == 403:
                remaining = resp.headers.get("X-RateLimit-Remaining", "?")
                logger.warning(f"GitHub 403 for {repo['full_name']} (remaining: {remaining})")
                return None
            resp.raise_for_status()
            created_at = resp.json().get("created_at")
            if created_at:
                return {"id": repo["id"], "created_at": created_at}
            return None
        except Exception as e:
            logger.debug(f"Failed {repo['full_name']}: {e}")
            return None
        finally:
            await asyncio.sleep(REQUEST_DELAY)


async def ingest_ai_repo_created_at() -> dict:
    """Backfill created_at for a chunk of ai_repos. Self-draining."""
    started_at = datetime.now(timezone.utc)

    # Fetch repos missing created_at, prioritised by stars
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, full_name
            FROM ai_repos
            WHERE created_at IS NULL
            ORDER BY stars DESC NULLS LAST
            LIMIT :limit
        """), {"limit": CHUNK_SIZE}).fetchall()

    repos = [{"id": r[0], "full_name": r[1]} for r in rows]

    if not repos:
        logger.info("ai_repo_created_at: no repos to backfill — all done")
        return {"status": "complete", "remaining": 0}

    remaining_before = len(repos)
    logger.info(f"ai_repo_created_at: fetching {len(repos)} repos from GitHub API")

    # Fetch from GitHub in parallel
    headers = {"Accept": "application/vnd.github+json"}
    token = settings.GITHUB_TOKEN
    if token:
        headers["Authorization"] = f"Bearer {token}"

    semaphore = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(headers=headers, timeout=10, follow_redirects=True) as client:
        tasks = [_fetch_created_at(client, repo, semaphore) for repo in repos]
        results = await asyncio.gather(*tasks)

    updates = [r for r in results if r is not None]

    # Bulk update via temp table
    updated = 0
    if updates:
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TEMP TABLE _created_at_tmp "
                "(id INTEGER, created_at TIMESTAMPTZ) ON COMMIT DROP"
            ))
            conn.execute(
                text("INSERT INTO _created_at_tmp (id, created_at) VALUES (:id, :created_at)"),
                updates,
            )
            updated = conn.execute(text("""
                UPDATE ai_repos a
                SET created_at = t.created_at
                FROM _created_at_tmp t
                WHERE a.id = t.id AND a.created_at IS NULL
            """)).rowcount
            conn.commit()

    # Check remaining
    with engine.connect() as conn:
        remaining = conn.execute(text(
            "SELECT COUNT(*) FROM ai_repos WHERE created_at IS NULL"
        )).scalar() or 0

    # Log to sync_log
    with SessionLocal() as session:
        session.add(SyncLog(
            sync_type="ai_repo_created_at",
            status="success",
            records_written=updated,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()

    logger.info(
        f"ai_repo_created_at: updated {updated}/{len(repos)} repos, "
        f"{remaining} remaining"
    )

    return {
        "status": "ok",
        "fetched": len(repos),
        "updated": updated,
        "remaining": remaining,
    }
