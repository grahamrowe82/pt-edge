import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import Project, SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)


async def fetch_releases(client: httpx.AsyncClient, owner: str, repo: str) -> list[dict]:
    resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}/releases", params={"per_page": 10})
    if resp.status_code == 200:
        return resp.json()
    logger.warning(f"GitHub releases API {resp.status_code} for {owner}/{repo}")
    return []


async def collect_releases_for_project(
    client: httpx.AsyncClient, project: Project, semaphore: asyncio.Semaphore
) -> list[dict]:
    if not project.github_owner or not project.github_repo:
        return []

    async with semaphore:
        releases_data = await fetch_releases(client, project.github_owner, project.github_repo)
        await asyncio.sleep(0.1)

    rows = []
    for rel in releases_data:
        html_url = rel.get("html_url")
        published_at = rel.get("published_at")
        if not html_url or not published_at:
            continue

        body = rel.get("body") or ""
        title = rel.get("name") or rel.get("tag_name") or "Untitled"
        summary = body[:497] + "..." if len(body) > 500 else body if body else None

        rows.append({
            "project_id": project.id,
            "lab_id": project.lab_id,
            "version": rel.get("tag_name"),
            "title": title,
            "summary": summary,
            "body": body if body else None,
            "url": html_url,
            "released_at": datetime.fromisoformat(published_at.replace("Z", "+00:00")),
            "captured_at": datetime.now(timezone.utc),
            "source": "github",
        })
    return rows


async def ingest_releases() -> dict:
    session = SessionLocal()
    projects = (
        session.query(Project)
        .filter(Project.is_active.is_(True), Project.github_owner.isnot(None), Project.github_repo.isnot(None))
        .all()
    )
    session.close()

    logger.info(f"Ingesting releases for {len(projects)} projects")
    started_at = datetime.now(timezone.utc)

    headers = {"User-Agent": "pt-edge/1.0"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    semaphore = asyncio.Semaphore(5)
    async with httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True) as client:
        tasks = [collect_releases_for_project(client, p, semaphore) for p in projects]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    releases = []
    error_count = 0
    for r in results:
        if isinstance(r, Exception):
            error_count += 1
            logger.error(f"Releases fetch error: {r}")
        elif isinstance(r, list):
            releases.extend(r)

    new_count = 0
    if releases:
        with engine.connect() as conn:
            for rel in releases:
                try:
                    conn.execute(
                        text("""
                            INSERT INTO releases (project_id, lab_id, version, title, summary, body, url, released_at, captured_at, source)
                            VALUES (:project_id, :lab_id, :version, :title, :summary, :body, :url, :released_at, :captured_at, :source)
                            ON CONFLICT (url) DO NOTHING
                        """),
                        rel,
                    )
                    new_count += 1
                except Exception:
                    pass  # skip duplicates
            conn.commit()
        logger.info(f"Batch wrote {new_count} releases")

    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="releases", status="success" if error_count == 0 else "partial",
            records_written=new_count,
            error_message=f"{error_count} failures" if error_count else None,
            started_at=started_at, finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    logger.info(f"Releases ingest complete: {new_count} new, {error_count} errors")
    return {"success": new_count, "errors": error_count}
