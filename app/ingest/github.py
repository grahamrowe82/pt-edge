import asyncio
import logging
import re
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import Project, SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)


async def fetch_repo(client: httpx.AsyncClient, owner: str, repo: str) -> dict | None:
    resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
    if resp.status_code == 200:
        return resp.json()
    logger.warning(f"GitHub API {resp.status_code} for {owner}/{repo}")
    return None


async def fetch_commit_activity(client: httpx.AsyncClient, owner: str, repo: str) -> int:
    resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}/stats/commit_activity")
    if resp.status_code == 200:
        weeks = resp.json()
        if isinstance(weeks, list) and len(weeks) >= 4:
            return sum(w.get("total", 0) for w in weeks[-4:])
    return 0


async def fetch_contributor_count(client: httpx.AsyncClient, owner: str, repo: str) -> int:
    resp = await client.get(
        f"https://api.github.com/repos/{owner}/{repo}/contributors",
        params={"per_page": 1, "anon": "true"},
    )
    if resp.status_code == 200:
        link = resp.headers.get("Link", "")
        if 'rel="last"' in link:
            for part in link.split(","):
                if 'rel="last"' in part:
                    match = re.search(r"page=(\d+)", part)
                    if match:
                        return int(match.group(1))
        data = resp.json()
        return len(data) if isinstance(data, list) else 0
    return 0


async def collect_project_data(
    client: httpx.AsyncClient, project: Project, semaphore: asyncio.Semaphore
) -> dict | None:
    """Fetch all GitHub data for one project. Returns a dict for batch insert, or None."""
    if not project.github_owner or not project.github_repo:
        return None

    async with semaphore:
        repo_data = await fetch_repo(client, project.github_owner, project.github_repo)
        if not repo_data:
            return None
        await asyncio.sleep(0.1)
        commits_30d = await fetch_commit_activity(client, project.github_owner, project.github_repo)
        await asyncio.sleep(0.1)
        contributors = await fetch_contributor_count(client, project.github_owner, project.github_repo)

    last_push = repo_data.get("pushed_at")
    last_commit_at = None
    if last_push:
        last_commit_at = datetime.fromisoformat(last_push.replace("Z", "+00:00"))

    return {
        "project_id": project.id,
        "snapshot_date": date.today(),
        "captured_at": datetime.now(timezone.utc),
        "stars": repo_data.get("stargazers_count", 0),
        "forks": repo_data.get("forks_count", 0),
        "open_issues": repo_data.get("open_issues_count", 0),
        "watchers": repo_data.get("subscribers_count", 0),
        "commits_30d": commits_30d,
        "contributors": contributors,
        "last_commit_at": last_commit_at,
        "license": (repo_data.get("license") or {}).get("spdx_id"),
    }


async def ingest_github() -> dict:
    """Fetch GitHub stats for all projects, then batch write to DB."""
    session = SessionLocal()
    projects = (
        session.query(Project)
        .filter(Project.is_active.is_(True), Project.github_owner.isnot(None), Project.github_repo.isnot(None))
        .all()
    )
    session.close()

    logger.info(f"Ingesting GitHub stats for {len(projects)} projects")
    started_at = datetime.now(timezone.utc)

    headers = {"User-Agent": "pt-edge/1.0"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    semaphore = asyncio.Semaphore(5)

    # Phase 1: collect all data from API (async, concurrent)
    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        tasks = [collect_project_data(client, p, semaphore) for p in projects]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    snapshots = []
    error_count = 0
    for r in results:
        if isinstance(r, Exception):
            error_count += 1
            logger.error(f"GitHub fetch error: {r}")
        elif r is not None:
            snapshots.append(r)
        # None means skipped (no github info)

    # Phase 2: batch write to DB in one connection
    if snapshots:
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO github_snapshots
                        (project_id, snapshot_date, captured_at, stars, forks, open_issues,
                         watchers, commits_30d, contributors, last_commit_at, license)
                    VALUES
                        (:project_id, :snapshot_date, :captured_at, :stars, :forks, :open_issues,
                         :watchers, :commits_30d, :contributors, :last_commit_at, :license)
                    ON CONFLICT (project_id, snapshot_date)
                    DO UPDATE SET
                        stars = EXCLUDED.stars, forks = EXCLUDED.forks,
                        open_issues = EXCLUDED.open_issues, watchers = EXCLUDED.watchers,
                        commits_30d = EXCLUDED.commits_30d, contributors = EXCLUDED.contributors,
                        last_commit_at = EXCLUDED.last_commit_at, license = EXCLUDED.license,
                        captured_at = EXCLUDED.captured_at
                """),
                snapshots,
            )
            conn.commit()
        logger.info(f"Batch wrote {len(snapshots)} GitHub snapshots")

    # Log sync
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="github",
            status="success" if error_count == 0 else "partial",
            records_written=len(snapshots),
            error_message=f"{error_count} failures" if error_count else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    logger.info(f"GitHub ingest complete: {len(snapshots)} success, {error_count} errors")
    return {"success": len(snapshots), "errors": error_count}
