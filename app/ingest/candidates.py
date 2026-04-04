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
from app.ingest.llm import call_llm_text
from app.models import Project, SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

# Only re-score candidates discovered more than 24h ago (need a baseline first)
MIN_AGE = timedelta(hours=24)


async def _rescore_candidate(
    client: httpx.AsyncClient, candidate: dict, semaphore: asyncio.Semaphore,
) -> dict | None:
    """Fetch current star count and enrichment data for a candidate repo.

    Enrichment (created_at, commit_trend, contributor_count) is fetched
    once and cached so MCP tools don't need live API calls per-request.
    """
    from app.ingest.github import (
        fetch_commit_activity, fetch_commit_count_simple, fetch_contributor_count,
    )

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

    result = {
        "id": candidate["id"],
        "stars_previous": old_stars,
        "stars": new_stars,
    }

    # Enrichment: repo_created_at (always available from repo response)
    created_str = data.get("created_at")
    if created_str:
        try:
            result["repo_created_at"] = datetime.fromisoformat(
                created_str.replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            pass

    # Enrichment: commit_trend + contributor_count (skip if already cached)
    needs_enrichment = (
        candidate.get("repo_created_at") is None
        or candidate.get("commit_trend") is None
    )
    if needs_enrichment:
        async with semaphore:
            try:
                commit_trend = await fetch_commit_activity(client, owner, repo)
                # Stats API often returns 0 for young repos — fall back to
                # simple commit listing which works for any repo age
                if commit_trend == 0:
                    commit_trend = await fetch_commit_count_simple(client, owner, repo)
                result["commit_trend"] = commit_trend
            except Exception:
                pass
            try:
                contrib = await fetch_contributor_count(client, owner, repo)
                result["contributor_count"] = contrib
            except Exception:
                pass

    return result


async def ingest_candidate_velocity() -> dict:
    """Re-fetch star counts for pending candidates to track velocity."""
    started_at = datetime.now(timezone.utc)
    cutoff = datetime.now(timezone.utc) - MIN_AGE

    # Get pending candidates old enough to have a baseline
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, github_owner, github_repo, stars,
                   repo_created_at, commit_trend
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
                # Build dynamic SET clause — always update stars, conditionally update enrichment
                set_parts = [
                    "stars_previous = :stars_previous",
                    "stars = :stars",
                    "stars_updated_at = NOW()",
                ]
                if "repo_created_at" in u:
                    set_parts.append("repo_created_at = :repo_created_at")
                if "commit_trend" in u:
                    set_parts.append("commit_trend = :commit_trend")
                if "contributor_count" in u:
                    set_parts.append("contributor_count = :contributor_count")

                conn.execute(text(f"""
                    UPDATE project_candidates
                    SET {', '.join(set_parts)}
                    WHERE id = :id
                """), u)
            conn.commit()
        logger.info(f"Updated {len(updates)} candidate star counts + enrichment")

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

# Domain-specific overrides (lower bar for commercially relevant domains)
DOMAIN_PROMOTE_STARS = {
    "eval": 2_000,
    "orchestration": 2_000,
    "data": 2_500,
    "infra": 2_500,
}

# Domain weight multipliers for watchlist scoring
DOMAIN_WEIGHTS = {
    "eval": 1.4,
    "orchestration": 1.3,
    "data": 1.3,
    "infra": 1.3,
    "agents": 1.2,
    "rag": 1.2,
    "ai-coding": 1.1,
}
DEFAULT_DOMAIN_WEIGHT = 1.0

# Minimum watchlist tenure before auto-promotion (prevents flash-in-the-pan repos)
AUTO_PROMOTE_MIN_AGE_DAYS = 14

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


CATEGORY_PROMPT = """\
Classify this AI/ML GitHub project into exactly one category: \
model, framework, tool, library, infra, agent.

Project: {name}
Description: {description}
Language: {language}
Topics: {topics}

Return ONLY the category word, nothing else."""

VALID_CATEGORIES = {"model", "framework", "tool", "library", "infra", "agent"}


async def _classify_category_llm(
    name: str, description: str, language: str | None, topics: list | None,
) -> str | None:
    """Use LLM to classify a project's category. Returns category or None."""
    prompt = CATEGORY_PROMPT.format(
        name=name,
        description=description or "",
        language=language or "unknown",
        topics=", ".join(topics) if topics else "none",
    )
    result = await call_llm_text(prompt, max_tokens=20)
    if result:
        cat = result.strip().lower()
        if cat in VALID_CATEGORIES:
            return cat
    return None


async def _auto_promote_candidates() -> list[dict]:
    """Promote pending candidates that cross star thresholds.

    Returns list of {"slug": ..., "stars": ..., "source": ...} for each promoted project.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT pc.id, pc.github_url, pc.github_owner, pc.github_repo,
                   pc.name, pc.description, pc.stars, pc.language, pc.topics,
                   pc.source, ar.domain
            FROM project_candidates pc
            LEFT JOIN ai_repos ar
                ON LOWER(pc.github_owner) = LOWER(ar.github_owner)
               AND LOWER(pc.github_repo) = LOWER(ar.github_repo)
            WHERE pc.status = 'pending'
              AND pc.stars IS NOT NULL
              AND pc.discovered_at <= NOW() - make_interval(days => :age_days)
              AND (
                  (pc.stars >= :hn_threshold AND pc.source = 'hn')
                  OR pc.stars >= :any_threshold
                  -- Domain-specific lower thresholds
                  OR (ar.domain = 'eval' AND pc.stars >= :eval_threshold)
                  OR (ar.domain = 'orchestration' AND pc.stars >= :orch_threshold)
                  OR (ar.domain = 'data' AND pc.stars >= :data_threshold)
                  OR (ar.domain = 'infra' AND pc.stars >= :infra_threshold)
              )
            ORDER BY pc.stars DESC
        """), {
            "age_days": AUTO_PROMOTE_MIN_AGE_DAYS,
            "hn_threshold": AUTO_PROMOTE_HN_STARS,
            "any_threshold": AUTO_PROMOTE_ANY_STARS,
            "eval_threshold": DOMAIN_PROMOTE_STARS.get("eval", AUTO_PROMOTE_ANY_STARS),
            "orch_threshold": DOMAIN_PROMOTE_STARS.get("orchestration", AUTO_PROMOTE_ANY_STARS),
            "data_threshold": DOMAIN_PROMOTE_STARS.get("data", AUTO_PROMOTE_ANY_STARS),
            "infra_threshold": DOMAIN_PROMOTE_STARS.get("infra", AUTO_PROMOTE_ANY_STARS),
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

            # LLM category classification with language-based fallback
            category = await _classify_category_llm(
                c.get("name") or c.get("github_repo") or "",
                c.get("description") or "",
                c.get("language"),
                list(c.get("topics") or []),
            )
            if not category:
                lang = (c.get("language") or "").lower()
                category = LANG_CATEGORY.get(lang, "tool")

            # Create project — default to binary distribution (most HN/trending
            # discoveries are apps, not pip-installable packages)
            candidate_topics = list(c.get("topics") or [])
            candidate_domain = c.get("domain")  # from ai_repos JOIN
            project = Project(
                slug=slug,
                name=c.get("name") or c.get("github_repo") or slug,
                category=category,
                domain=candidate_domain,
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


# ---------------------------------------------------------------------------
# Watchlist: top-1000 ai_repos → project_candidates
# ---------------------------------------------------------------------------

# Scoring weights (tuned from EDA natural breaks)
# Score = (star_weight * star_score) + (velocity_weight * velocity_score) + (recency_weight * recency_score)
WATCHLIST_LIMIT = 1000


async def refresh_candidate_watchlist() -> dict:
    """Identify the top-1000 most interesting ai_repos and upsert into project_candidates.

    Scoring blends:
      - stars (log-scaled, max ~50 points)
      - commits_30d velocity (log-scaled, max ~30 points)
      - recency of last push (linear decay, max ~20 points)

    Excludes repos already tracked as projects or already accepted/rejected candidates.
    """
    with engine.connect() as conn:
        # Get already-tracked project github identities to exclude
        tracked = conn.execute(text("""
            SELECT LOWER(github_owner) || '/' || LOWER(github_repo)
            FROM projects
            WHERE github_owner IS NOT NULL
        """)).fetchall()
        tracked_set = {r[0] for r in tracked}

        # Get accepted/rejected candidates to exclude
        resolved = conn.execute(text("""
            SELECT LOWER(github_owner) || '/' || LOWER(github_repo)
            FROM project_candidates
            WHERE status IN ('accepted', 'rejected')
              AND github_owner IS NOT NULL
        """)).fetchall()
        resolved_set = {r[0] for r in resolved}

        # Score and rank ai_repos
        # Using SQL for efficiency — log scaling + recency decay
        rows = conn.execute(text("""
            SELECT
                id, github_owner, github_repo, full_name, name, description,
                stars, forks, language, topics, domain,
                last_pushed_at, commits_30d,
                -- Blended score with domain weight multiplier
                (
                    COALESCE(LN(GREATEST(stars, 1) + 1) * 7, 0)
                    + COALESCE(LN(GREATEST(commits_30d, 0) + 1) * 10, 0)
                    + CASE
                        WHEN last_pushed_at >= NOW() - INTERVAL '7 days' THEN 20
                        WHEN last_pushed_at >= NOW() - INTERVAL '30 days' THEN 15
                        WHEN last_pushed_at >= NOW() - INTERVAL '60 days' THEN 10
                        WHEN last_pushed_at >= NOW() - INTERVAL '90 days' THEN 5
                        ELSE 0
                      END
                ) * CASE domain
                    WHEN 'eval' THEN 1.4
                    WHEN 'orchestration' THEN 1.3
                    WHEN 'data' THEN 1.3
                    WHEN 'infra' THEN 1.3
                    WHEN 'agents' THEN 1.2
                    WHEN 'rag' THEN 1.2
                    WHEN 'ai-coding' THEN 1.1
                    ELSE 1.0
                  END AS watchlist_score
            FROM ai_repos
            WHERE stars >= 100
              AND archived = false
              AND last_pushed_at >= NOW() - INTERVAL '90 days'
              AND commits_30d IS NOT NULL
            ORDER BY watchlist_score DESC
            LIMIT :fetch_limit
        """), {"fetch_limit": WATCHLIST_LIMIT * 2}).fetchall()
        # Fetch 2x to have headroom after filtering

    # Filter out already-tracked and resolved
    candidates = []
    for r in rows:
        m = dict(r._mapping)
        key = f"{m['github_owner'].lower()}/{m['github_repo'].lower()}"
        if key in tracked_set or key in resolved_set:
            continue
        candidates.append(m)
        if len(candidates) >= WATCHLIST_LIMIT:
            break

    if not candidates:
        logger.info("No new watchlist candidates found")
        return {"upserted": 0}

    # Upsert into project_candidates
    upserted = 0
    with engine.connect() as conn:
        for c in candidates:
            github_url = f"https://github.com/{c['github_owner']}/{c['github_repo']}"
            conn.execute(text("""
                INSERT INTO project_candidates
                    (github_url, github_owner, github_repo, name, description,
                     stars, language, source, source_detail, topics,
                     commit_trend, discovered_at, status)
                VALUES
                    (:url, :owner, :repo, :name, :desc,
                     :stars, :lang, 'watchlist', :detail, :topics,
                     :commits, NOW(), 'pending')
                ON CONFLICT (github_url) DO UPDATE SET
                    stars = EXCLUDED.stars,
                    commit_trend = EXCLUDED.commit_trend,
                    stars_updated_at = NOW()
            """), {
                "url": github_url,
                "owner": c["github_owner"],
                "repo": c["github_repo"],
                "name": c["name"],
                "desc": (c["description"] or "")[:500],
                "stars": c["stars"],
                "lang": c["language"],
                "detail": f"watchlist_score={c['watchlist_score']:.1f}, domain={c['domain']}",
                "topics": c.get("topics"),
                "commits": c.get("commits_30d"),
            })
            upserted += 1
        conn.commit()

    logger.info(f"Watchlist refresh: upserted {upserted} candidates from ai_repos")
    return {"upserted": upserted, "scored": len(rows)}
