import asyncio
import logging
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import Project, SyncLog

logger = logging.getLogger(__name__)


async def fetch_hf_downloads(client: httpx.AsyncClient, model_id: str) -> int | None:
    """Fetch last-30-day download count for a HuggingFace model."""
    resp = await client.get(f"https://huggingface.co/api/models/{model_id}")
    if resp.status_code == 200:
        return resp.json().get("downloads", 0)
    logger.warning(f"HuggingFace API {resp.status_code} for {model_id}")
    return None


async def collect_hf_downloads_for_project(
    client: httpx.AsyncClient, project: Project, semaphore: asyncio.Semaphore
) -> dict | None:
    if not project.hf_model_id:
        return None

    async with semaphore:
        downloads = await fetch_hf_downloads(client, project.hf_model_id)
        await asyncio.sleep(0.5)

    if downloads is None:
        return None

    return {
        "project_id": project.id,
        "source": "huggingface",
        "snapshot_date": date.today(),
        "captured_at": datetime.now(timezone.utc),
        "downloads_daily": 0,  # HF API only gives 30-day total
        "downloads_weekly": 0,
        "downloads_monthly": downloads,
    }


async def ingest_huggingface() -> dict:
    session = SessionLocal()
    projects = [
        p for p in session.query(Project).filter(
            Project.is_active.is_(True),
            Project.hf_model_id.isnot(None),
        ).all()
    ]
    session.close()

    logger.info(f"Ingesting HuggingFace downloads for {len(projects)} projects")
    started_at = datetime.now(timezone.utc)

    semaphore = asyncio.Semaphore(3)
    async with httpx.AsyncClient(
        headers={"User-Agent": "pt-edge/1.0"}, timeout=30.0, follow_redirects=True
    ) as client:
        tasks = [collect_hf_downloads_for_project(client, p, semaphore) for p in projects]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    snapshots = []
    error_count = 0
    for r in results:
        if isinstance(r, Exception):
            error_count += 1
            logger.error(f"HuggingFace fetch error: {r}")
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
        logger.info(f"Batch wrote {len(snapshots)} HuggingFace download snapshots")

    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="huggingface", status="success" if error_count == 0 else "partial",
            records_written=len(snapshots),
            error_message=f"{error_count} failures" if error_count else None,
            started_at=started_at, finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    logger.info(f"HuggingFace ingest complete: {len(snapshots)} snapshots, {error_count} errors")
    return {"success": len(snapshots), "errors": error_count}
