import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import Project, SyncLog

logger = logging.getLogger(__name__)


async def fetch_dockerhub_pulls(client: httpx.AsyncClient, image: str) -> int | None:
    """Fetch cumulative pull count for a Docker Hub repository."""
    resp = await client.get(f"https://hub.docker.com/v2/repositories/{image}")
    if resp.status_code == 200:
        return resp.json().get("pull_count", 0)
    logger.warning(f"Docker Hub API {resp.status_code} for {image}")
    return None


async def collect_dockerhub_pulls_for_project(
    client: httpx.AsyncClient, project: Project, semaphore: asyncio.Semaphore
) -> dict | None:
    if not project.docker_image:
        return None

    async with semaphore:
        pulls = await fetch_dockerhub_pulls(client, project.docker_image)
        await asyncio.sleep(0.5)

    if pulls is None:
        return None

    return {
        "project_id": project.id,
        "source": "dockerhub",
        "snapshot_date": date.today(),
        "captured_at": datetime.now(timezone.utc),
        "downloads_daily": 0,
        "downloads_weekly": 0,
        "downloads_monthly": 0,  # computed from historical delta below
        "cumulative_pulls": pulls,
    }


async def ingest_dockerhub() -> dict:
    session = SessionLocal()
    projects = [
        p for p in session.query(Project).filter(
            Project.is_active.is_(True),
            Project.docker_image.isnot(None),
        ).all()
    ]
    session.close()

    logger.info(f"Ingesting Docker Hub pulls for {len(projects)} projects")
    started_at = datetime.now(timezone.utc)

    semaphore = asyncio.Semaphore(3)
    async with httpx.AsyncClient(
        headers={"User-Agent": "pt-edge/1.0"}, timeout=30.0, follow_redirects=True
    ) as client:
        tasks = [collect_dockerhub_pulls_for_project(client, p, semaphore) for p in projects]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    snapshots = []
    error_count = 0
    for r in results:
        if isinstance(r, Exception):
            error_count += 1
            logger.error(f"Docker Hub fetch error: {r}")
        elif r is not None:
            snapshots.append(r)

    if snapshots:
        with engine.connect() as conn:
            # Compute monthly delta from historical snapshots
            for snap in snapshots:
                cumulative = snap.pop("cumulative_pulls")
                prev = conn.execute(
                    text("""
                        SELECT downloads_monthly FROM download_snapshots
                        WHERE project_id = :pid AND source = 'dockerhub'
                          AND snapshot_date <= :cutoff
                        ORDER BY snapshot_date DESC LIMIT 1
                    """),
                    {"pid": snap["project_id"], "cutoff": date.today() - timedelta(days=30)},
                ).fetchone()
                if prev and prev[0] > 0:
                    # Previous downloads_monthly stored the cumulative total
                    snap["downloads_monthly"] = max(0, cumulative - prev[0])
                else:
                    # No prior snapshot — store cumulative as-is for future delta
                    snap["downloads_monthly"] = cumulative

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
        logger.info(f"Batch wrote {len(snapshots)} Docker Hub download snapshots")

    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="dockerhub", status="success" if error_count == 0 else "partial",
            records_written=len(snapshots),
            error_message=f"{error_count} failures" if error_count else None,
            started_at=started_at, finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    logger.info(f"Docker Hub ingest complete: {len(snapshots)} snapshots, {error_count} errors")
    return {"success": len(snapshots), "errors": error_count}
