"""Fetch commits_30d for top ai_repos using GitHub GraphQL API.

Batches 50 repos per query to stay efficient within rate limits.
Targets repos with >=500 stars, pushed in last 90 days, not archived.
Weekly cadence (called from runner.py Phase 2).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import engine, SessionLocal
from app.github_client import get_github_client
from app.models import SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

# Only check repos likely to be interesting
MIN_STARS = 500
MAX_PUSH_AGE_DAYS = 90
BATCH_SIZE = 50  # GraphQL nodes per query
CONCURRENCY = 3  # parallel GraphQL requests


def _build_graphql_query(repos: list[dict]) -> str:
    """Build a GraphQL query that fetches commit counts for multiple repos."""
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    fragments = []
    for i, repo in enumerate(repos):
        owner = repo["github_owner"].replace('"', '\\"')
        name = repo["github_repo"].replace('"', '\\"')
        fragments.append(f"""
    r{i}: repository(owner: "{owner}", name: "{name}") {{
      defaultBranchRef {{
        target {{
          ... on Commit {{
            history(since: "{since}") {{
              totalCount
            }}
          }}
        }}
      }}
    }}""")
    return "query {" + "".join(fragments) + "\n}"


async def _fetch_batch(
    repos: list[dict],
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    """Fetch commits_30d for a batch of repos via GraphQL."""
    query = _build_graphql_query(repos)
    gh = get_github_client()

    async with semaphore:
        try:
            resp = await gh.post_graphql(query, caller="ingest.ai_repo_commits")
        except Exception as e:
            logger.error(f"GraphQL request failed: {e}")
            return []

    if resp.status_code != 200:
        logger.warning(f"GraphQL HTTP {resp.status_code}: {resp.text[:200]}")
        return []

    data = resp.json()
    if "errors" in data and not data.get("data"):
        logger.warning(f"GraphQL errors: {data['errors'][:3]}")
        return []

    results = []
    gql_data = data.get("data", {})
    for i, repo in enumerate(repos):
        node = gql_data.get(f"r{i}")
        if not node:
            continue
        branch = node.get("defaultBranchRef")
        if not branch or not branch.get("target"):
            results.append({"id": repo["id"], "commits_30d": 0})
            continue
        history = branch["target"].get("history", {})
        count = history.get("totalCount", 0)
        results.append({"id": repo["id"], "commits_30d": count})

    return results


async def ingest_ai_repo_commits() -> dict:
    """Fetch commits_30d for eligible ai_repos and update in place."""
    started_at = datetime.now(timezone.utc)

    if not settings.GITHUB_TOKEN:
        logger.warning("No GITHUB_TOKEN — skipping ai_repo commits ingest")
        return {"skipped": True, "reason": "no GITHUB_TOKEN"}

    # Select eligible repos: high stars, recently active, not archived
    push_cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_PUSH_AGE_DAYS)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, github_owner, github_repo
            FROM ai_repos
            WHERE stars >= :min_stars
              AND last_pushed_at >= :push_cutoff
              AND archived = false
            ORDER BY stars DESC
        """), {"min_stars": MIN_STARS, "push_cutoff": push_cutoff}).fetchall()

    repos = [dict(r._mapping) for r in rows]
    logger.info(f"Fetching commits_30d for {len(repos)} ai_repos (stars >= {MIN_STARS})")

    if not repos:
        return {"updated": 0, "errors": 0}

    # Batch into groups of BATCH_SIZE
    batches = [repos[i:i + BATCH_SIZE] for i in range(0, len(repos), BATCH_SIZE)]
    semaphore = asyncio.Semaphore(CONCURRENCY)

    all_results = []
    error_count = 0
    tasks = [_fetch_batch(batch, semaphore) for batch in batches]
    batch_results = await asyncio.gather(*tasks, return_exceptions=True)
    for br in batch_results:
        if isinstance(br, Exception):
            error_count += 1
            logger.error(f"Batch error: {br}")
        else:
            all_results.extend(br)

    # Bulk update via temp table + UPDATE FROM (fast for thousands of rows)
    now = datetime.now(timezone.utc)
    if all_results:
        with engine.connect() as conn:
            conn.execute(text("CREATE TEMP TABLE _commits_tmp (id INTEGER, commits_30d INTEGER) ON COMMIT DROP"))
            conn.execute(
                text("INSERT INTO _commits_tmp (id, commits_30d) VALUES (:id, :commits_30d)"),
                all_results,
            )
            updated = conn.execute(text("""
                UPDATE ai_repos a
                SET commits_30d = t.commits_30d, commits_checked_at = :now
                FROM _commits_tmp t
                WHERE a.id = t.id
            """), {"now": now}).rowcount
            conn.commit()
        logger.info(f"Updated commits_30d for {updated} ai_repos")

    # Log sync
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="ai_repo_commits",
            status="success" if error_count == 0 else "partial",
            records_written=len(all_results),
            error_message=f"{error_count} batch failures" if error_count else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    logger.info(f"ai_repo_commits complete: {len(all_results)} updated, {error_count} errors")
    return {"updated": len(all_results), "errors": error_count, "eligible": len(repos)}
