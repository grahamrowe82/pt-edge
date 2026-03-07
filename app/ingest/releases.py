import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import Project, Release, SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

MAX_SUMMARY_LENGTH = 500


async def fetch_releases(client: httpx.AsyncClient, owner: str, repo: str) -> list[dict]:
    """Fetch the latest releases from GitHub API. Returns up to 10 releases."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"
    resp = await client.get(url, params={"per_page": 10})
    if resp.status_code == 200:
        return resp.json()
    logger.warning(f"GitHub releases API {resp.status_code} for {owner}/{repo}")
    return []


def _truncate(text: str | None, max_length: int) -> str | None:
    """Truncate text to max_length, appending ellipsis if shortened."""
    if not text:
        return None
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


async def ingest_releases_for_project(
    client: httpx.AsyncClient, project: Project, semaphore: asyncio.Semaphore
) -> int:
    """Fetch and store releases for a single project. Returns count of new releases stored."""
    if not project.github_owner or not project.github_repo:
        return 0

    async with semaphore:
        releases_data = await fetch_releases(client, project.github_owner, project.github_repo)
        await asyncio.sleep(1.0 / settings.GITHUB_RATE_LIMIT)

    if not releases_data:
        return 0

    new_count = 0
    session = SessionLocal()
    try:
        for rel in releases_data:
            html_url = rel.get("html_url")
            if not html_url:
                continue

            published_at = rel.get("published_at")
            if not published_at:
                continue

            released_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            body = rel.get("body") or ""
            title = rel.get("name") or rel.get("tag_name") or "Untitled"

            release = Release(
                project_id=project.id,
                lab_id=project.lab_id,
                version=rel.get("tag_name"),
                title=title,
                summary=_truncate(body, MAX_SUMMARY_LENGTH),
                body=body if body else None,
                url=html_url,
                released_at=released_at,
                source="github",
            )
            session.add(release)

            try:
                session.flush()
                new_count += 1
            except IntegrityError:
                # Release already exists (unique constraint on url), skip it
                session.rollback()
                continue

        session.commit()
    except Exception:
        session.rollback()
        logger.exception(f"Failed to save releases for {project.slug}")
        raise
    finally:
        session.close()

    return new_count


async def ingest_releases() -> dict:
    """Fetch releases for all active projects with GitHub repos."""
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

    logger.info(f"Ingesting releases for {len(projects)} projects")
    started_at = datetime.now(timezone.utc)
    success_count = 0
    error_count = 0

    headers = {"User-Agent": "pt-edge/1.0"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    semaphore = asyncio.Semaphore(5)

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        tasks = [ingest_releases_for_project(client, p, semaphore) for p in projects]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                error_count += 1
                logger.error(f"Releases ingest error: {r}")
            elif isinstance(r, int):
                success_count += r
            else:
                error_count += 1

    # Log sync
    session = SessionLocal()
    try:
        log = SyncLog(
            sync_type="releases",
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

    logger.info(f"Releases ingest complete: {success_count} new releases, {error_count} errors")
    return {"success": success_count, "errors": error_count}
