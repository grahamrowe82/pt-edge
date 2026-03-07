import asyncio
import logging
import re
from datetime import date, datetime, timezone

import httpx

from app.db import SessionLocal
from app.models import GitHubSnapshot, Project, SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)


async def fetch_repo(client: httpx.AsyncClient, owner: str, repo: str) -> dict | None:
    """Fetch repo metadata from GitHub API. Returns parsed JSON or None on error."""
    url = f"https://api.github.com/repos/{owner}/{repo}"
    resp = await client.get(url)
    if resp.status_code == 200:
        return resp.json()
    logger.warning(f"GitHub API {resp.status_code} for {owner}/{repo}")
    return None


async def fetch_commit_activity(client: httpx.AsyncClient, owner: str, repo: str) -> int:
    """Fetch commit activity for last 30 days. Returns total commits in last 4 weeks."""
    url = f"https://api.github.com/repos/{owner}/{repo}/stats/commit_activity"
    resp = await client.get(url)
    if resp.status_code == 200:
        weeks = resp.json()
        if isinstance(weeks, list) and len(weeks) >= 4:
            return sum(w.get("total", 0) for w in weeks[-4:])
    return 0


async def fetch_contributor_count(client: httpx.AsyncClient, owner: str, repo: str) -> int:
    """Fetch contributor count using per_page=1 and parsing Link header for last page."""
    url = f"https://api.github.com/repos/{owner}/{repo}/contributors"
    resp = await client.get(url, params={"per_page": 1, "anon": "true"})
    if resp.status_code == 200:
        link = resp.headers.get("Link", "")
        # Parse last page number from Link header
        if 'rel="last"' in link:
            for part in link.split(","):
                if 'rel="last"' in part:
                    match = re.search(r"page=(\d+)", part)
                    if match:
                        return int(match.group(1))
        # If no Link header, count is just the results length
        data = resp.json()
        return len(data) if isinstance(data, list) else 0
    return 0


async def ingest_github_for_project(
    client: httpx.AsyncClient, project: Project, semaphore: asyncio.Semaphore
) -> bool:
    """Fetch GitHub stats for a single project and store snapshot."""
    if not project.github_owner or not project.github_repo:
        return False

    async with semaphore:
        repo_data = await fetch_repo(client, project.github_owner, project.github_repo)
        if not repo_data:
            return False

        await asyncio.sleep(1.0 / settings.GITHUB_RATE_LIMIT)
        commits_30d = await fetch_commit_activity(client, project.github_owner, project.github_repo)

        await asyncio.sleep(1.0 / settings.GITHUB_RATE_LIMIT)
        contributors = await fetch_contributor_count(client, project.github_owner, project.github_repo)

    last_push = repo_data.get("pushed_at")
    last_commit_at = None
    if last_push:
        last_commit_at = datetime.fromisoformat(last_push.replace("Z", "+00:00"))

    session = SessionLocal()
    try:
        # Upsert: check if snapshot exists for today
        existing = (
            session.query(GitHubSnapshot)
            .filter(
                GitHubSnapshot.project_id == project.id,
                GitHubSnapshot.snapshot_date == date.today(),
            )
            .first()
        )

        if existing:
            existing.stars = repo_data.get("stargazers_count", 0)
            existing.forks = repo_data.get("forks_count", 0)
            existing.open_issues = repo_data.get("open_issues_count", 0)
            existing.watchers = repo_data.get("subscribers_count", 0)
            existing.commits_30d = commits_30d
            existing.contributors = contributors
            existing.last_commit_at = last_commit_at
            existing.license = (repo_data.get("license") or {}).get("spdx_id")
            existing.captured_at = datetime.now(timezone.utc)
        else:
            snapshot = GitHubSnapshot(
                project_id=project.id,
                snapshot_date=date.today(),
                stars=repo_data.get("stargazers_count", 0),
                forks=repo_data.get("forks_count", 0),
                open_issues=repo_data.get("open_issues_count", 0),
                watchers=repo_data.get("subscribers_count", 0),
                commits_30d=commits_30d,
                contributors=contributors,
                last_commit_at=last_commit_at,
                license=(repo_data.get("license") or {}).get("spdx_id"),
            )
            session.add(snapshot)

        session.commit()
        return True
    except Exception:
        session.rollback()
        logger.exception(f"Failed to save GitHub snapshot for {project.slug}")
        return False
    finally:
        session.close()


async def ingest_github() -> dict:
    """Fetch GitHub stats for all active projects with GitHub repos."""
    session = SessionLocal()
    projects = (
        session.query(Project)
        .filter(
            Project.is_active.is_(True),
            Project.github_owner.isnot(None),
            Project.github_repo.isnot(None),
        )
        .all()
    )
    session.close()

    logger.info(f"Ingesting GitHub stats for {len(projects)} projects")
    started_at = datetime.now(timezone.utc)
    success_count = 0
    error_count = 0

    headers = {"User-Agent": "pt-edge/1.0"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    semaphore = asyncio.Semaphore(5)  # max concurrent requests

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        tasks = [ingest_github_for_project(client, p, semaphore) for p in projects]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                error_count += 1
                logger.error(f"GitHub ingest error: {r}")
            elif r:
                success_count += 1
            else:
                error_count += 1

    # Log sync
    session = SessionLocal()
    try:
        log = SyncLog(
            sync_type="github",
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

    logger.info(f"GitHub ingest complete: {success_count} success, {error_count} errors")
    return {"success": success_count, "errors": error_count}
