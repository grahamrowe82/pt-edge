import asyncio
import logging
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import Project, SyncLog

logger = logging.getLogger(__name__)


async def fetch_pypi_downloads(client: httpx.AsyncClient, package: str) -> dict | None:
    resp = await client.get(f"https://pypistats.org/api/packages/{package}/recent")
    if resp.status_code == 200:
        data = resp.json().get("data", {})
        return {"last_day": data.get("last_day", 0), "last_week": data.get("last_week", 0), "last_month": data.get("last_month", 0)}
    logger.warning(f"PyPI stats API {resp.status_code} for {package}")
    return None


async def fetch_npm_downloads(client: httpx.AsyncClient, package: str) -> dict | None:
    result = {"last_day": 0, "last_week": 0, "last_month": 0}
    for period, key in [("last-day", "last_day"), ("last-week", "last_week"), ("last-month", "last_month")]:
        resp = await client.get(f"https://api.npmjs.org/downloads/point/{period}/{package}")
        if resp.status_code == 200:
            result[key] = resp.json().get("downloads", 0)
        else:
            logger.warning(f"npm API {resp.status_code} for {package} ({period})")
            return None
        await asyncio.sleep(0.3)
    return result


async def collect_downloads_for_project(
    client: httpx.AsyncClient, project: Project, semaphore: asyncio.Semaphore
) -> list[dict]:
    """Collect download snapshots for a project. Returns list of 0-2 snapshot dicts."""
    rows = []
    async with semaphore:
        if project.pypi_package:
            stats = await fetch_pypi_downloads(client, project.pypi_package)
            if stats:
                rows.append({
                    "project_id": project.id, "source": "pypi", "snapshot_date": date.today(),
                    "captured_at": datetime.now(timezone.utc),
                    "downloads_daily": stats["last_day"], "downloads_weekly": stats["last_week"],
                    "downloads_monthly": stats["last_month"],
                })
            await asyncio.sleep(1.0)

        if project.npm_package:
            stats = await fetch_npm_downloads(client, project.npm_package)
            if stats:
                rows.append({
                    "project_id": project.id, "source": "npm", "snapshot_date": date.today(),
                    "captured_at": datetime.now(timezone.utc),
                    "downloads_daily": stats["last_day"], "downloads_weekly": stats["last_week"],
                    "downloads_monthly": stats["last_month"],
                })
            await asyncio.sleep(0.5)

    return rows


async def ingest_downloads() -> dict:
    session = SessionLocal()
    projects = [p for p in session.query(Project).filter(Project.is_active.is_(True)).all()
                if p.pypi_package or p.npm_package]
    session.close()

    logger.info(f"Ingesting download stats for {len(projects)} projects")
    started_at = datetime.now(timezone.utc)

    semaphore = asyncio.Semaphore(3)
    async with httpx.AsyncClient(headers={"User-Agent": "pt-edge/1.0"}, timeout=30.0) as client:
        tasks = [collect_downloads_for_project(client, p, semaphore) for p in projects]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    snapshots = []
    error_count = 0
    for r in results:
        if isinstance(r, Exception):
            error_count += 1
            logger.error(f"Download fetch error: {r}")
        elif isinstance(r, list):
            snapshots.extend(r)

    if snapshots:
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO download_snapshots
                        (project_id, source, snapshot_date, captured_at,
                         downloads_daily, downloads_weekly, downloads_monthly)
                    VALUES (:project_id, :source, :snapshot_date, :captured_at,
                            :downloads_daily, :downloads_weekly, :downloads_monthly)
                    ON CONFLICT (project_id, source, snapshot_date)
                    DO UPDATE SET
                        downloads_daily = EXCLUDED.downloads_daily,
                        downloads_weekly = EXCLUDED.downloads_weekly,
                        downloads_monthly = EXCLUDED.downloads_monthly,
                        captured_at = EXCLUDED.captured_at
                """),
                snapshots,
            )
            conn.commit()
        logger.info(f"Batch wrote {len(snapshots)} download snapshots")

    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="downloads", status="success" if error_count == 0 else "partial",
            records_written=len(snapshots),
            error_message=f"{error_count} failures" if error_count else None,
            started_at=started_at, finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    logger.info(f"Download ingest complete: {len(snapshots)} snapshots, {error_count} errors")
    return {"success": len(snapshots), "errors": error_count}
