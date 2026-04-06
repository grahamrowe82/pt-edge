import asyncio
import logging
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.ingest.budget import acquire_budget, record_call, record_throttle, record_success
from app.models import Project, SyncLog

logger = logging.getLogger(__name__)


async def fetch_pypi_downloads(client: httpx.AsyncClient, package: str) -> dict | None:
    if not await acquire_budget("pypi"):
        return None
    resp = await client.get(f"https://pypistats.org/api/packages/{package}/recent")
    await record_call("pypi")
    if resp.status_code == 200:
        await record_success("pypi")
        data = resp.json().get("data", {})
        return {"last_day": data.get("last_day", 0), "last_week": data.get("last_week", 0), "last_month": data.get("last_month", 0)}
    if resp.status_code == 429:
        await record_throttle("pypi")
        return None
    logger.warning(f"PyPI stats API {resp.status_code} for {package}")
    return None


async def fetch_npm_downloads(client: httpx.AsyncClient, package: str) -> dict | None:
    result = {"last_day": 0, "last_week": 0, "last_month": 0}
    for period, key in [("last-day", "last_day"), ("last-week", "last_week"), ("last-month", "last_month")]:
        if not await acquire_budget("npm"):
            return None
        resp = await client.get(f"https://api.npmjs.org/downloads/point/{period}/{package}")
        await record_call("npm")
        if resp.status_code == 200:
            await record_success("npm")
            result[key] = resp.json().get("downloads", 0)
        elif resp.status_code == 429:
            await record_throttle("npm")
            return None
        else:
            logger.warning(f"npm API {resp.status_code} for {package} ({period})")
            return None
    return result


async def fetch_crate_downloads(client: httpx.AsyncClient, crate_name: str) -> dict | None:
    """Fetch download counts from crates.io.

    crates.io returns `recent_downloads` (~90 days). Divide by 3 for monthly.
    """
    if not await acquire_budget("crates"):
        return None
    resp = await client.get(
        f"https://crates.io/api/v1/crates/{crate_name}",
        headers={"User-Agent": "pt-edge/1.0 (https://github.com/pt-edge)"},
    )
    await record_call("crates")
    if resp.status_code == 200:
        await record_success("crates")
        data = resp.json().get("crate", {})
        recent = data.get("recent_downloads", 0) or 0
        return {"last_month": recent // 3}
    if resp.status_code == 429:
        await record_throttle("crates")
        return None
    logger.warning(f"crates.io API {resp.status_code} for {crate_name}")
    return None


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

        if project.npm_package:
            stats = await fetch_npm_downloads(client, project.npm_package)
            if stats:
                rows.append({
                    "project_id": project.id, "source": "npm", "snapshot_date": date.today(),
                    "captured_at": datetime.now(timezone.utc),
                    "downloads_daily": stats["last_day"], "downloads_weekly": stats["last_week"],
                    "downloads_monthly": stats["last_month"],
                })

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
