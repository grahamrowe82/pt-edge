"""Re-score pending project candidates by re-fetching their GitHub star counts.

This enables velocity tracking: by comparing the current star count to the
previous value, radar() can surface candidates that are exploding in popularity.

Auto-promotion: candidates crossing star thresholds are automatically promoted
to tracked projects. Generous thresholds — false positives are cheap to clean up,
false negatives mean missing the next OpenClaw.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import Project, SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

# Only re-score candidates discovered more than 24h ago (need a baseline first)
MIN_AGE = timedelta(hours=24)


async def _rescore_candidate(
    client: httpx.AsyncClient, candidate: dict, semaphore: asyncio.Semaphore,
) -> dict | None:
    """Fetch current star count for a candidate repo."""
    owner = candidate.get("github_owner")
    repo = candidate.get("github_repo")
    if not owner or not repo:
        return None

    async with semaphore:
        try:
            resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error fetching {owner}/{repo}: {e}")
            return None

    if resp.status_code != 200:
        logger.warning(f"GitHub API {resp.status_code} for candidate {owner}/{repo}")
        return None

    data = resp.json()
    new_stars = data.get("stargazers_count", 0)
    old_stars = candidate.get("stars") or 0

    return {
        "id": candidate["id"],
        "stars_previous": old_stars,
        "stars": new_stars,
    }


async def ingest_candidate_velocity() -> dict:
    """Re-fetch star counts for pending candidates to track velocity."""
    started_at = datetime.now(timezone.utc)
    cutoff = datetime.now(timezone.utc) - MIN_AGE

    # Get pending candidates old enough to have a baseline
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, github_owner, github_repo, stars
            FROM project_candidates
            WHERE status = 'pending'
              AND discovered_at < :cutoff
            ORDER BY stars DESC NULLS LAST
        """), {"cutoff": cutoff}).fetchall()

    candidates = [dict(r._mapping) for r in rows]
    logger.info(f"Re-scoring {len(candidates)} pending candidates")

    if not candidates:
        return {"rescored": 0, "errors": 0}

    headers = {"User-Agent": "pt-edge/1.0"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    semaphore = asyncio.Semaphore(5)
    async with httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True) as client:
        tasks = [_rescore_candidate(client, c, semaphore) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    updates = []
    error_count = 0
    for r in results:
        if isinstance(r, Exception):
            error_count += 1
            logger.error(f"Rescore error: {r}")
        elif r is not None:
            updates.append(r)

    # Batch update
    if updates:
        with engine.connect() as conn:
            for u in updates:
                conn.execute(text("""
                    UPDATE project_candidates
                    SET stars_previous = :stars_previous,
                        stars = :stars,
                        stars_updated_at = NOW()
                    WHERE id = :id
                """), u)
            conn.commit()
        logger.info(f"Updated {len(updates)} candidate star counts")

    # Log sync
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="candidate_velocity",
            status="success" if error_count == 0 else "partial",
            records_written=len(updates),
            error_message=f"{error_count} failures" if error_count else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    # Auto-promote candidates that cross thresholds
    promoted = await _auto_promote_candidates()

    logger.info(
        f"Candidate velocity complete: {len(updates)} rescored, "
        f"{error_count} errors, {len(promoted)} auto-promoted"
    )
    return {"rescored": len(updates), "errors": error_count, "auto_promoted": promoted}


# ---------------------------------------------------------------------------
# Auto-promotion: generous thresholds, false positives are cheap
# ---------------------------------------------------------------------------

# >1K stars + discovered via HN = someone in AI community posted it
AUTO_PROMOTE_HN_STARS = 1_000
# >5K stars from any source = significant project regardless of how we found it
AUTO_PROMOTE_ANY_STARS = 5_000

# Language → likely category mapping
LANG_CATEGORY = {
    "python": "library",
    "typescript": "tool",
    "javascript": "tool",
    "rust": "library",
    "go": "tool",
    "c++": "library",
    "c": "library",
    "jupyter notebook": "library",
}


async def _auto_promote_candidates() -> list[dict]:
    """Promote pending candidates that cross star thresholds.

    Returns list of {"slug": ..., "stars": ..., "source": ...} for each promoted project.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, github_url, github_owner, github_repo, name, description,
                   stars, language, topics, source
            FROM project_candidates
            WHERE status = 'pending'
              AND stars IS NOT NULL
              AND (
                  (stars >= :hn_threshold AND source = 'hn')
                  OR stars >= :any_threshold
              )
            ORDER BY stars DESC
        """), {
            "hn_threshold": AUTO_PROMOTE_HN_STARS,
            "any_threshold": AUTO_PROMOTE_ANY_STARS,
        }).fetchall()

    if not rows:
        return []

    promoted = []
    for r in rows:
        c = r._mapping

        # Generate slug
        slug = (c.get("github_repo") or c.get("name") or f"candidate-{c['id']}").lower()
        slug = re.sub(r"[^a-z0-9-]", "-", slug).strip("-")

        # Each promotion in its own session to avoid long-running transaction timeouts
        session = SessionLocal()
        try:
            # Skip if slug already exists as a tracked project
            existing = session.query(Project).filter(Project.slug == slug).first()
            if existing:
                # Mark candidate as accepted (already tracked under this slug)
                session.execute(text(
                    "UPDATE project_candidates SET status = 'accepted', reviewed_at = NOW() WHERE id = :cid"
                ), {"cid": c["id"]})
                session.commit()
                continue

            # Guess category from language
            lang = (c.get("language") or "").lower()
            category = LANG_CATEGORY.get(lang, "tool")

            # Create project — default to binary distribution (most HN/trending
            # discoveries are apps, not pip-installable packages)
            candidate_topics = list(c.get("topics") or [])
            project = Project(
                slug=slug,
                name=c.get("name") or c.get("github_repo") or slug,
                category=category,
                github_owner=c.get("github_owner"),
                github_repo=c.get("github_repo"),
                url=c.get("github_url"),
                description=(c.get("description") or "")[:500],
                topics=candidate_topics if candidate_topics else None,
                distribution_type="binary",
                is_active=True,
            )
            session.add(project)

            # Mark candidate as accepted
            session.execute(text(
                "UPDATE project_candidates SET status = 'accepted', reviewed_at = NOW() WHERE id = :cid"
            ), {"cid": c["id"]})

            session.commit()

            promoted.append({
                "slug": slug,
                "stars": c.get("stars"),
                "source": c.get("source"),
                "name": project.name,
                "description": project.description,
                "topics": candidate_topics,
                "category": category,
                "language": c.get("language"),
            })
            logger.info(
                f"Auto-promoted: {slug} ({c.get('stars'):,} stars, source={c.get('source')})"
            )
        except Exception as e:
            session.rollback()
            logger.error(f"Auto-promotion failed for {slug}: {e}")
        finally:
            session.close()

    if promoted:
        logger.info(f"Auto-promoted {len(promoted)} candidates to tracked projects")
        await _embed_promoted_projects(promoted)

    return promoted


async def _embed_promoted_projects(promoted: list[dict]) -> None:
    """Generate embeddings for newly promoted projects. Optional — skips if no API key."""
    from app.embeddings import is_enabled, build_project_text, embed_batch

    if not is_enabled():
        return

    texts = [
        build_project_text(p["name"], p["description"], p["topics"], p["category"], p["language"])
        for p in promoted
    ]
    vectors = await embed_batch(texts)

    with engine.connect() as conn:
        for p, vec in zip(promoted, vectors):
            if vec is not None:
                conn.execute(text("""
                    UPDATE projects SET embedding = :vec WHERE slug = :slug
                """), {"vec": str(vec), "slug": p["slug"]})
        conn.commit()

    embedded = sum(1 for v in vectors if v is not None)
    logger.info(f"Embedded {embedded}/{len(promoted)} promoted projects")
