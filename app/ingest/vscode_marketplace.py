import asyncio
import logging
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import Project, SyncLog

logger = logging.getLogger(__name__)

VSCODE_API_URL = "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"

# Flags: IncludeStatistics (0x10) | IncludeVersions (0x100) | ExcludeNonValidated (0x80) | IncludeInstallationTargets (0x2)
QUERY_FLAGS = 0x192


async def fetch_vscode_installs(client: httpx.AsyncClient, extension_id: str) -> int | None:
    """Fetch total install count for a VS Code Marketplace extension."""
    body = {
        "filters": [{
            "criteria": [
                {"filterType": 7, "value": extension_id}
            ]
        }],
        "flags": QUERY_FLAGS,
    }
    resp = await client.post(VSCODE_API_URL, json=body)
    if resp.status_code != 200:
        logger.warning(f"VS Code Marketplace API {resp.status_code} for {extension_id}")
        return None

    data = resp.json()
    results = data.get("results", [])
    if not results or not results[0].get("extensions"):
        logger.warning(f"No extension found for {extension_id}")
        return None

    ext = results[0]["extensions"][0]
    statistics = {s["statisticName"]: s["value"] for s in ext.get("statistics", [])}
    return int(statistics.get("install", 0))


async def collect_vscode_for_project(
    client: httpx.AsyncClient, project: Project, semaphore: asyncio.Semaphore
) -> dict | None:
    if not project.vscode_extension_id:
        return None

    async with semaphore:
        installs = await fetch_vscode_installs(client, project.vscode_extension_id)
        await asyncio.sleep(0.5)

    if installs is None:
        return None

    return {
        "project_id": project.id,
        "source": "vscode",
        "snapshot_date": date.today(),
        "captured_at": datetime.now(timezone.utc),
        "downloads_daily": 0,
        "downloads_weekly": 0,
        "downloads_monthly": installs,
    }


async def ingest_vscode() -> dict:
    session = SessionLocal()
    projects = [
        p for p in session.query(Project).filter(
            Project.is_active.is_(True),
            Project.vscode_extension_id.isnot(None),
        ).all()
    ]
    session.close()

    logger.info(f"Ingesting VS Code Marketplace installs for {len(projects)} projects")
    started_at = datetime.now(timezone.utc)

    semaphore = asyncio.Semaphore(3)
    async with httpx.AsyncClient(
        headers={
            "User-Agent": "pt-edge/1.0",
            "Content-Type": "application/json",
            "Accept": "application/json;api-version=6.1-preview.1",
        },
        timeout=30.0,
    ) as client:
        tasks = [collect_vscode_for_project(client, p, semaphore) for p in projects]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    snapshots = []
    error_count = 0
    for r in results:
        if isinstance(r, Exception):
            error_count += 1
            logger.error(f"VS Code Marketplace fetch error: {r}")
        elif r is not None:
            snapshots.append(r)

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
                        downloads_monthly = EXCLUDED.downloads_monthly,
                        captured_at = EXCLUDED.captured_at
                """),
                snapshots,
            )
            conn.commit()
        logger.info(f"Batch wrote {len(snapshots)} VS Code Marketplace download snapshots")

    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="vscode", status="success" if error_count == 0 else "partial",
            records_written=len(snapshots),
            error_message=f"{error_count} failures" if error_count else None,
            started_at=started_at, finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    logger.info(f"VS Code Marketplace ingest complete: {len(snapshots)} snapshots, {error_count} errors")
    return {"success": len(snapshots), "errors": error_count}
