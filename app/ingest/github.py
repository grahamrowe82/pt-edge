import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.ingest.budget import (
    ResourceThrottledError,
    acquire_budget,
    record_call,
    record_success,
    record_throttle,
)
from app.models import Project, SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

# Module-level flag: set to False when GitHub returns 403, checked by all fetchers
_github_available = True


async def check_github_rate_limit(client: httpx.AsyncClient) -> bool:
    """Pre-flight check: is GitHub API available? Returns False if rate-limited."""
    global _github_available
    try:
        resp = await client.get("https://api.github.com/rate_limit")
        if resp.status_code == 403:
            logger.error("GitHub API rate-limited (403 on /rate_limit) — skipping all GitHub calls")
            _github_available = False
            return False
        if resp.status_code == 200:
            data = resp.json()
            remaining = data.get("resources", {}).get("core", {}).get("remaining", 0)
            if remaining < 100:
                logger.warning(f"GitHub API near limit ({remaining} remaining) — skipping to avoid 403")
                _github_available = False
                return False
            _github_available = True
            return True
    except Exception as e:
        logger.warning(f"GitHub rate limit check failed: {e}")
    return True  # optimistic if check itself fails


async def fetch_repo(client: httpx.AsyncClient, owner: str, repo: str) -> dict | None:
    global _github_available
    if not _github_available:
        return None
    if not await acquire_budget("github_api"):
        _github_available = False
        return None
    resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
    await record_call("github_api")
    if resp.status_code == 200:
        await record_success("github_api")
        return resp.json()
    if resp.status_code in (403, 429):
        await record_throttle("github_api")
        _github_available = False
        logger.error(f"GitHub API {resp.status_code} for {owner}/{repo} — aborting remaining requests")
        return None
    logger.warning(f"GitHub API {resp.status_code} for {owner}/{repo}")
    return None


async def fetch_commit_activity(client: httpx.AsyncClient, owner: str, repo: str) -> int:
    if not _github_available or not await acquire_budget("github_api"):
        return 0
    url = f"https://api.github.com/repos/{owner}/{repo}/stats/commit_activity"
    resp = await client.get(url)
    await record_call("github_api")
    # GitHub returns 202 when stats are being computed async — retry with exponential backoff
    backoff = [2.0, 5.0, 10.0]
    for delay in backoff:
        if resp.status_code != 202:
            break
        await asyncio.sleep(delay)
        if not await acquire_budget("github_api"):
            return 0
        resp = await client.get(url)
        await record_call("github_api")
    if resp.status_code == 200:
        await record_success("github_api")
        weeks = resp.json()
        if isinstance(weeks, list) and len(weeks) >= 4:
            return sum(w.get("total", 0) for w in weeks[-4:])
    return 0


async def fetch_commit_count_simple(
    client: httpx.AsyncClient, owner: str, repo: str, days: int = 30,
) -> int:
    """Count commits in the last N days using the /commits endpoint + Link header.

    Lightweight fallback for repos where /stats/commit_activity returns 0
    (common for repos < 4 weeks old). Uses the same pagination trick as
    fetch_contributor_count — request per_page=1 and read the last page number.
    """
    if not _github_available or not await acquire_budget("github_api"):
        return 0
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    resp = await client.get(
        f"https://api.github.com/repos/{owner}/{repo}/commits",
        params={"since": since, "per_page": 1},
    )
    await record_call("github_api")
    if resp.status_code != 200:
        return 0
    link = resp.headers.get("Link", "")
    if 'rel="last"' in link:
        for part in link.split(","):
            if 'rel="last"' in part:
                match = re.search(r"page=(\d+)", part)
                if match:
                    return int(match.group(1))
    # No Link header → one page or less
    data = resp.json()
    return len(data) if isinstance(data, list) else 0


async def fetch_contributor_count(client: httpx.AsyncClient, owner: str, repo: str) -> int:
    if not _github_available or not await acquire_budget("github_api"):
        return -1
    resp = await client.get(
        f"https://api.github.com/repos/{owner}/{repo}/contributors",
        params={"per_page": 1, "anon": "true"},
    )
    await record_call("github_api")
    count = 0
    if resp.status_code == 200:
        link = resp.headers.get("Link", "")
        if 'rel="last"' in link:
            for part in link.split(","):
                if 'rel="last"' in part:
                    match = re.search(r"page=(\d+)", part)
                    if match:
                        count = int(match.group(1))
                        break
        if count == 0:
            data = resp.json()
            count = len(data) if isinstance(data, list) else 0

    # Fallback: if pagination trick returned 0 or 1, try stats/contributors endpoint
    if count <= 1:
        try:
            if not await acquire_budget("github_api"):
                return count if count > 0 else -1
            stats_url = f"https://api.github.com/repos/{owner}/{repo}/stats/contributors"
            stats_resp = await client.get(stats_url)
            await record_call("github_api")
            # GitHub returns 202 when stats are being computed — retry with exponential backoff
            for delay in [2.0, 5.0, 10.0]:
                if stats_resp.status_code != 202:
                    break
                await asyncio.sleep(delay)
                if not await acquire_budget("github_api"):
                    break
                stats_resp = await client.get(stats_url)
                await record_call("github_api")
            if stats_resp.status_code == 200:
                stats_data = stats_resp.json()
                if isinstance(stats_data, list) and len(stats_data) > count:
                    return len(stats_data)
            # Stats endpoint failed or returned less — use -1 sentinel for "unknown"
            if count == 0:
                return -1
        except Exception:
            if count == 0:
                return -1

    return count


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
        if commits_30d == 0:
            await asyncio.sleep(0.1)
            commits_30d = await fetch_commit_count_simple(client, project.github_owner, project.github_repo)
        await asyncio.sleep(0.1)
        contributors = await fetch_contributor_count(client, project.github_owner, project.github_repo)
        contributors = max(contributors, 0)  # clamp -1 sentinel before it reaches the DB

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
        # Underscore-prefixed: used for project enrichment, not snapshot INSERT
        "_topics": repo_data.get("topics") or [],
        "_description": (repo_data.get("description") or "")[:500],
        "_language": repo_data.get("language"),
        "_repo_created_at": repo_data.get("created_at"),
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

    # Pre-flight: check if GitHub API is available before firing 784 requests
    async with httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True) as client:
        if not await check_github_rate_limit(client):
            session = SessionLocal()
            try:
                session.add(SyncLog(
                    sync_type="github", status="partial", records_written=0,
                    error_message="skipped: GitHub rate-limited",
                    started_at=started_at, finished_at=datetime.now(timezone.utc),
                ))
                session.commit()
            finally:
                session.close()
            return {"success": 0, "errors": 0, "skipped": "github_rate_limited"}

        # Phase 1: collect all data from API (async, concurrent)
        tasks = [collect_project_data(client, p, semaphore) for p in projects]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    snapshots = []
    enrichments = []  # (project_id, topics, description, language) for project updates
    error_count = 0
    for r in results:
        if isinstance(r, Exception):
            error_count += 1
            logger.error(f"GitHub fetch error: {r}")
        elif r is not None:
            # Pop enrichment fields before snapshot INSERT
            topics = r.pop("_topics", [])
            description = r.pop("_description", None)
            language = r.pop("_language", None)
            repo_created_str = r.pop("_repo_created_at", None)
            repo_created_at = None
            if repo_created_str:
                try:
                    repo_created_at = datetime.fromisoformat(
                        repo_created_str.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass
            enrichments.append({
                "project_id": r["project_id"],
                "topics": topics,
                "description": description,
                "language": language,
                "repo_created_at": repo_created_at,
            })
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
                        commits_30d = CASE
                            WHEN EXCLUDED.commits_30d = 0 AND github_snapshots.commits_30d > 0
                            THEN github_snapshots.commits_30d
                            ELSE EXCLUDED.commits_30d
                        END,
                        contributors = CASE
                            WHEN EXCLUDED.contributors <= 0 AND github_snapshots.contributors > 0
                            THEN github_snapshots.contributors
                            ELSE EXCLUDED.contributors
                        END,
                        last_commit_at = EXCLUDED.last_commit_at, license = EXCLUDED.license,
                        captured_at = EXCLUDED.captured_at
                """),
                snapshots,
            )
            conn.commit()
        logger.info(f"Batch wrote {len(snapshots)} GitHub snapshots")

        # Post-ingest validation warnings
        with engine.connect() as conn:
            zero_commits = conn.execute(text("""
                SELECT COUNT(*) FROM github_snapshots
                WHERE snapshot_date = CURRENT_DATE
                  AND commits_30d = 0
                  AND last_commit_at > NOW() - INTERVAL '30 days'
            """)).scalar()
            if zero_commits:
                logger.warning(f"Data quality: {zero_commits} projects with commits_30d=0 despite recent activity")

            suspect_contributors = conn.execute(text("""
                SELECT COUNT(*) FROM github_snapshots
                WHERE snapshot_date = CURRENT_DATE
                  AND contributors <= 1 AND stars > 500
            """)).scalar()
            if suspect_contributors:
                logger.warning(f"Data quality: {suspect_contributors} projects with contributors<=1 and stars>500")

    # Phase 2b: update project enrichment (topics, description) and re-embed
    if enrichments:
        await _update_project_enrichment(enrichments, projects)

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


async def _update_project_enrichment(enrichments: list[dict], projects: list[Project]) -> None:
    """Update project topics/description from GitHub API and regenerate embeddings if changed."""
    from app.embeddings import is_enabled, build_project_text, embed_batch

    project_map = {p.id: p for p in projects}
    changed = []

    with engine.connect() as conn:
        for e in enrichments:
            pid = e["project_id"]
            proj = project_map.get(pid)
            if not proj:
                continue

            new_topics = e["topics"]
            new_desc = e["description"]
            old_topics = proj.topics or []
            old_desc = proj.description or ""

            # Backfill repo_created_at if not yet set (immutable field)
            repo_created_at = e.get("repo_created_at")
            if repo_created_at and proj.repo_created_at is None:
                conn.execute(text("""
                    UPDATE projects SET repo_created_at = :rca WHERE id = :pid
                """), {"rca": repo_created_at, "pid": pid})

            # Only update topics/description if something changed
            if sorted(new_topics) != sorted(old_topics) or new_desc != old_desc:
                conn.execute(text("""
                    UPDATE projects
                    SET topics = :topics, description = :description, updated_at = NOW()
                    WHERE id = :pid
                """), {"topics": new_topics, "description": new_desc, "pid": pid})
                changed.append({
                    "project_id": pid,
                    "name": proj.name,
                    "description": new_desc,
                    "topics": new_topics,
                    "category": proj.category,
                    "language": e.get("language"),
                })

        conn.commit()

    if changed and is_enabled():
        texts = [
            build_project_text(c["name"], c["description"], c["topics"], c["category"], c["language"])
            for c in changed
        ]
        vectors = await embed_batch(texts)
        with engine.connect() as conn:
            for c, vec in zip(changed, vectors):
                if vec is not None:
                    conn.execute(text("""
                        UPDATE projects SET embedding = :vec WHERE id = :pid
                    """), {"vec": str(vec), "pid": c["project_id"]})
            conn.commit()
        embedded_count = sum(1 for v in vectors if v is not None)
        logger.info(f"Updated {len(changed)} project enrichments, embedded {embedded_count}")
