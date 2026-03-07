import asyncio
import logging
from datetime import date, datetime, timezone

import httpx

from app.db import SessionLocal
from app.models import DownloadSnapshot, Project, SyncLog

logger = logging.getLogger(__name__)


async def fetch_pypi_downloads(client: httpx.AsyncClient, package: str) -> dict | None:
    """Fetch recent download stats from PyPI Stats API.

    Returns dict with keys: last_day, last_week, last_month, or None on error.
    """
    url = f"https://pypistats.org/api/packages/{package}/recent"
    resp = await client.get(url)
    if resp.status_code == 200:
        data = resp.json().get("data", {})
        return {
            "last_day": data.get("last_day", 0),
            "last_week": data.get("last_week", 0),
            "last_month": data.get("last_month", 0),
        }
    logger.warning(f"PyPI stats API {resp.status_code} for {package}")
    return None


async def fetch_npm_downloads(client: httpx.AsyncClient, package: str) -> dict | None:
    """Fetch recent download stats from npm registry API.

    Returns dict with keys: last_day, last_week, last_month, or None on error.
    """
    result = {"last_day": 0, "last_week": 0, "last_month": 0}

    for period, key in [("last-day", "last_day"), ("last-week", "last_week"), ("last-month", "last_month")]:
        url = f"https://api.npmjs.org/downloads/point/{period}/{package}"
        resp = await client.get(url)
        if resp.status_code == 200:
            result[key] = resp.json().get("downloads", 0)
        else:
            logger.warning(f"npm API {resp.status_code} for {package} ({period})")
            return None
        # Be gentle with npm API
        await asyncio.sleep(0.5)

    return result


async def ingest_downloads_for_project(
    client: httpx.AsyncClient, project: Project, semaphore: asyncio.Semaphore
) -> int:
    """Fetch download stats for a single project from PyPI and/or npm.

    Returns number of snapshot records written (0, 1, or 2).
    """
    records = 0

    async with semaphore:
        # PyPI downloads
        if project.pypi_package:
            stats = await fetch_pypi_downloads(client, project.pypi_package)
            if stats:
                _upsert_download_snapshot(project.id, "pypi", stats)
                records += 1
            await asyncio.sleep(1.0)  # rate limit: 1s between PyPI requests

        # npm downloads
        if project.npm_package:
            stats = await fetch_npm_downloads(client, project.npm_package)
            if stats:
                _upsert_download_snapshot(project.id, "npm", stats)
                records += 1
            await asyncio.sleep(1.0)  # rate limit: 1s between npm requests

    return records


def _upsert_download_snapshot(project_id: int, source: str, stats: dict) -> None:
    """Insert or update a download snapshot for today."""
    session = SessionLocal()
    try:
        existing = (
            session.query(DownloadSnapshot)
            .filter(
                DownloadSnapshot.project_id == project_id,
                DownloadSnapshot.source == source,
                DownloadSnapshot.snapshot_date == date.today(),
            )
            .first()
        )

        if existing:
            existing.downloads_daily = stats["last_day"]
            existing.downloads_weekly = stats["last_week"]
            existing.downloads_monthly = stats["last_month"]
            existing.captured_at = datetime.now(timezone.utc)
        else:
            snapshot = DownloadSnapshot(
                project_id=project_id,
                source=source,
                snapshot_date=date.today(),
                downloads_daily=stats["last_day"],
                downloads_weekly=stats["last_week"],
                downloads_monthly=stats["last_month"],
            )
            session.add(snapshot)

        session.commit()
    except Exception:
        session.rollback()
        logger.exception(f"Failed to save download snapshot for project {project_id} ({source})")
        raise
    finally:
        session.close()


async def ingest_downloads() -> dict:
    """Fetch download stats for all active projects with PyPI or npm packages."""
    session = SessionLocal()
    projects = (
        session.query(Project)
        .filter(Project.is_active.is_(True))
        .all()
    )
    # Filter to projects that have at least one package identifier
    projects = [p for p in projects if p.pypi_package or p.npm_package]
    session.close()

    logger.info(f"Ingesting download stats for {len(projects)} projects")
    started_at = datetime.now(timezone.utc)
    success_count = 0
    error_count = 0

    headers = {"User-Agent": "pt-edge/1.0"}
    semaphore = asyncio.Semaphore(3)  # conservative concurrency for public APIs

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        tasks = [ingest_downloads_for_project(client, p, semaphore) for p in projects]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                error_count += 1
                logger.error(f"Download ingest error: {r}")
            elif isinstance(r, int):
                success_count += r
            else:
                error_count += 1

    # Log sync
    session = SessionLocal()
    try:
        log = SyncLog(
            sync_type="downloads",
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

    logger.info(f"Download ingest complete: {success_count} snapshots, {error_count} errors")
    return {"success": success_count, "errors": error_count}
