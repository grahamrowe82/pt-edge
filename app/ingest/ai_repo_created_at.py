"""Backfill ai_repos.created_at from GitHub REST API.

Self-draining: fetches repos WHERE created_at IS NULL in chunks, prioritised
by stars DESC. Commits each chunk independently so crashes lose at most one
chunk of in-flight work. Stops when the time budget is exhausted, the rate
limit is hit, or there are no more NULL rows.

Once the backlog is cleared (new repos already arrive with created_at from
the Search API), this becomes a no-op safety net — one cheap query per run.

Constrained by GitHub's 5,000 requests/hour token rate limit.
At 0.8s delay = ~4,500 requests/hour. A 10-hour budget = ~45,000 repos/run.
225K backlog / 45K per day = ~5 days to complete.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import SyncLog

logger = logging.getLogger(__name__)

WRITE_CHUNK = 1_000    # repos per DB write — crash loses at most this many
REQUEST_DELAY = 0.8    # seconds between requests — paces to ~4,500/hour
TIME_BUDGET_HOURS = 10 # stop after this many hours regardless


async def _fetch_created_at(full_name: str) -> str | None:
    """Fetch created_at for a single repo. Returns ISO string or None."""
    from app.github_client import GitHubRateLimitError, get_github_client
    gh = get_github_client()
    try:
        resp = await gh.get(f"/repos/{full_name}", caller="ingest.ai_repo_created_at")
        if resp.status_code == 404:
            return None
        if resp.status_code == 403:
            kind = gh.classify_403(resp)
            if kind in ("rate_limit", "secondary_rate_limit"):
                return "RATE_LIMITED"
            return None  # access denied — skip this repo
        if resp.status_code != 200:
            return None
        return resp.json().get("created_at")
    except GitHubRateLimitError:
        return "RATE_LIMITED"
    except Exception as e:
        logger.debug(f"Failed {full_name}: {e}")
        return None


def _write_chunk(updates: list[dict]) -> int:
    """Bulk-write a chunk of created_at values. Returns rows updated."""
    if not updates:
        return 0
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
    return updated


async def ingest_ai_repo_created_at() -> dict:
    """Backfill created_at for ai_repos. Time-budgeted, chunked writes."""
    started_at = datetime.now(timezone.utc)
    wall_start = time.monotonic()
    budget_seconds = TIME_BUDGET_HOURS * 3600

    # Quick check — anything to do?
    with engine.connect() as conn:
        remaining = conn.execute(text(
            "SELECT COUNT(*) FROM ai_repos WHERE created_at IS NULL"
        )).scalar() or 0

    if remaining == 0:
        logger.info("ai_repo_created_at: nothing to backfill")
        return {"status": "complete", "remaining": 0}

    logger.info(f"ai_repo_created_at: {remaining} repos to backfill")

    total_fetched = 0
    total_updated = 0
    stop_reason = "queue_empty"

    while True:
        # Check time budget
        elapsed = time.monotonic() - wall_start
        if elapsed >= budget_seconds:
            stop_reason = "time_budget"
            logger.info(f"ai_repo_created_at: time budget reached ({elapsed / 3600:.1f}h)")
            break

        # Fetch next chunk of NULL repos
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, full_name
                FROM ai_repos
                WHERE created_at IS NULL
                ORDER BY stars DESC NULLS LAST
                LIMIT :limit
            """), {"limit": WRITE_CHUNK}).fetchall()

        if not rows:
            stop_reason = "queue_empty"
            break

        # Fetch created_at for each repo, sequentially
        chunk_updates = []
        for repo_id, full_name in rows:
            created_at = await _fetch_created_at(full_name)

            if created_at == "RATE_LIMITED":
                stop_reason = "rate_limited"
                logger.warning("ai_repo_created_at: GitHub rate limit hit, stopping early")
                break

            if created_at:
                chunk_updates.append({"id": repo_id, "created_at": created_at})

            await asyncio.sleep(REQUEST_DELAY)

        # Write whatever we got from this chunk
        chunk_written = _write_chunk(chunk_updates)
        total_fetched += len(rows) if stop_reason != "rate_limited" else len(chunk_updates)
        total_updated += chunk_written

        logger.info(
            f"ai_repo_created_at: chunk done — {chunk_written} written, "
            f"{total_updated} total, {elapsed / 60:.0f}min elapsed"
        )

        if stop_reason == "rate_limited":
            break

    # Final remaining count
    with engine.connect() as conn:
        remaining = conn.execute(text(
            "SELECT COUNT(*) FROM ai_repos WHERE created_at IS NULL"
        )).scalar() or 0

    status = "success" if stop_reason == "queue_empty" else "partial"

    with SessionLocal() as session:
        session.add(SyncLog(
            sync_type="ai_repo_created_at",
            status=status,
            records_written=total_updated,
            error_message=None if stop_reason == "queue_empty" else f"stopped: {stop_reason}",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()

    logger.info(
        f"ai_repo_created_at: {stop_reason} — {total_updated} updated, "
        f"{remaining} remaining, {(time.monotonic() - wall_start) / 3600:.1f}h elapsed"
    )

    return {
        "status": status,
        "stop_reason": stop_reason,
        "fetched": total_fetched,
        "updated": total_updated,
        "remaining": remaining,
    }
