"""Backfill ai_repos.created_at from GitHub API.

Fetches created_at for repos where it's NULL, in batches.
Idempotent — only fetches rows where created_at IS NULL.
Rate-limited to ~4,500 requests/hour (under GitHub's 5,000/hour limit).

Usage:
    source .env && .venv/bin/python scripts/backfill_created_at.py [--batch-size 500] [--max-batches 10]
"""
import argparse
import logging
import os
import time

import httpx
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


def get_engine():
    from sqlalchemy import create_engine
    return create_engine(DATABASE_URL)


def fetch_batch(engine, batch_size: int) -> list[dict]:
    """Get a batch of repos missing created_at, prioritised by stars."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, full_name
            FROM ai_repos
            WHERE created_at IS NULL
            ORDER BY stars DESC NULLS LAST
            LIMIT :limit
        """), {"limit": batch_size}).fetchall()
    return [{"id": r[0], "full_name": r[1]} for r in rows]


def fetch_created_at(client: httpx.Client, full_name: str) -> str | None:
    """Fetch created_at from GitHub API for a single repo."""
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        resp = client.get(f"https://api.github.com/repos/{full_name}", headers=headers)
        if resp.status_code == 404:
            return None
        if resp.status_code == 403:
            # Rate limited — check reset time
            reset = int(resp.headers.get("X-RateLimit-Reset", 0))
            wait = max(0, reset - int(time.time())) + 5
            logger.warning(f"Rate limited, waiting {wait}s")
            time.sleep(wait)
            return fetch_created_at(client, full_name)  # retry once
        resp.raise_for_status()
        return resp.json().get("created_at")
    except Exception as e:
        logger.debug(f"Failed to fetch {full_name}: {e}")
        return None


def update_batch(engine, updates: list[dict]) -> int:
    """Write created_at values back to ai_repos."""
    if not updates:
        return 0
    with engine.connect() as conn:
        for u in updates:
            conn.execute(text("""
                UPDATE ai_repos SET created_at = :created_at
                WHERE id = :id AND created_at IS NULL
            """), u)
        conn.commit()
    return len(updates)


def main():
    parser = argparse.ArgumentParser(description="Backfill ai_repos.created_at")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-batches", type=int, default=10)
    args = parser.parse_args()

    engine = get_engine()
    client = httpx.Client(timeout=10)

    total_updated = 0
    for batch_num in range(1, args.max_batches + 1):
        repos = fetch_batch(engine, args.batch_size)
        if not repos:
            logger.info("No more repos to backfill")
            break

        logger.info(f"Batch {batch_num}: fetching {len(repos)} repos")
        updates = []
        for i, repo in enumerate(repos):
            created_at = fetch_created_at(client, repo["full_name"])
            if created_at:
                updates.append({"id": repo["id"], "created_at": created_at})
            if (i + 1) % 100 == 0:
                logger.info(f"  ...{i + 1}/{len(repos)} fetched")
            time.sleep(0.8)  # ~4,500 requests/hour

        written = update_batch(engine, updates)
        total_updated += written
        logger.info(f"Batch {batch_num}: updated {written}/{len(repos)} repos")

    # Check remaining
    with engine.connect() as conn:
        remaining = conn.execute(text(
            "SELECT COUNT(*) FROM ai_repos WHERE created_at IS NULL"
        )).scalar()

    logger.info(f"Done: {total_updated} repos updated, {remaining} remaining")
    client.close()


if __name__ == "__main__":
    main()
