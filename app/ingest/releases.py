"""Ingest GitHub releases with LLM summarisation and embeddings.

For each release with a body, Claude Haiku generates a 2-3 sentence summary
focused on what changed, breaking changes, and new capabilities. Releases
with empty bodies get summary=NULL (no body to summarise).

Self-healing: on each run, re-summarises up to 500 releases that still have
the old truncated summary (body[:500]) and embeds releases missing embeddings.
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine, SessionLocal
from app.embeddings import is_enabled as embeddings_enabled, build_release_text, embed_batch
from app.github_client import get_github_client
from app.models import Project, SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """Summarise this software release in 2-3 sentences.
Focus on: what changed, any breaking changes, and new capabilities.
Be factual and concise. Do not use marketing language.

Project: {project_name}
Version: {version}
Title: {title}

Release notes:
{body}"""


async def _summarise_release(body: str, project_name: str, version: str, title: str) -> str | None:
    """Call LLM to summarise a release. Returns None on failure."""
    if not settings.GEMINI_API_KEY:
        return None
    if not body or len(body) < 50:
        return None  # too short to be worth summarising

    # Truncate very long release notes to avoid wasting tokens
    body_truncated = body[:8000] if len(body) > 8000 else body

    from app.ingest.llm import call_llm_text

    prompt = SUMMARY_PROMPT.format(
        project_name=project_name,
        version=version or "unknown",
        title=title,
        body=body_truncated,
    )
    return await call_llm_text(prompt, max_tokens=512)


async def fetch_releases(owner: str, repo: str) -> list[dict]:
    gh = get_github_client()
    resp = await gh.get(f"/repos/{owner}/{repo}/releases", caller="ingest.releases",
                        params={"per_page": 10})
    if resp.status_code == 200:
        return resp.json()
    logger.warning(f"GitHub releases API {resp.status_code} for {owner}/{repo}")
    return []


async def collect_releases_for_project(
    project: Project, semaphore: asyncio.Semaphore,
    existing_urls: set[str],
) -> list[dict]:
    if not project.github_owner or not project.github_repo:
        return []

    async with semaphore:
        releases_data = await fetch_releases(project.github_owner, project.github_repo)
        await asyncio.sleep(0.1)

    rows = []
    for rel in releases_data:
        html_url = rel.get("html_url")
        published_at = rel.get("published_at")
        if not html_url or not published_at:
            continue
        if html_url in existing_urls:
            continue

        body = rel.get("body") or ""
        title = rel.get("name") or rel.get("tag_name") or "Untitled"

        # LLM summary for releases with meaningful body text
        summary = await _summarise_release(body, project.name, rel.get("tag_name"), title)
        # Fallback: no summary if body is empty or LLM unavailable
        if not summary and body:
            summary = body[:497] + "..." if len(body) > 500 else body

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
    # Build project_id -> name lookup for self-healing
    project_names = {p.id: p.name for p in projects}
    session.close()

    logger.info(f"Ingesting releases for {len(projects)} projects")
    started_at = datetime.now(timezone.utc)
    llm_calls = 0
    embed_count = 0

    # ── Self-healing: re-summarise releases with truncated summaries ──
    # Truncated summaries end with "..." and match body[:497] — these are the old format
    healed = 0
    if settings.GEMINI_API_KEY:
        with engine.connect() as conn:
            stale_rows = conn.execute(text("""
                SELECT r.id, r.body, r.title, r.version, r.project_id
                FROM releases r
                WHERE r.body IS NOT NULL
                  AND r.summary IS NOT NULL
                  AND r.summary = LEFT(r.body, 497) || '...'
                ORDER BY r.released_at DESC
                LIMIT 500
            """)).fetchall()

        if stale_rows:
            logger.info(f"  Re-summarising {len(stale_rows)} releases with truncated summaries...")

        for row in stale_rows:
            m = row._mapping
            pname = project_names.get(m["project_id"], "Unknown")
            new_summary = await _summarise_release(m["body"], pname, m["version"], m["title"])
            if new_summary:
                with engine.connect() as conn:
                    conn.execute(
                        text("UPDATE releases SET summary = :summary WHERE id = :id"),
                        {"summary": new_summary, "id": m["id"]},
                    )
                    conn.commit()
                healed += 1
                llm_calls += 1

        if healed:
            logger.info(f"  Re-summarised {healed}/{len(stale_rows)} releases")

    # ── Self-healing: embed releases missing embeddings ──
    if embeddings_enabled():
        with engine.connect() as conn:
            unembedded = conn.execute(text("""
                SELECT r.id, p.name as project_name, r.version, r.title, r.summary
                FROM releases r
                JOIN projects p ON p.id = r.project_id
                WHERE r.summary IS NOT NULL
                  AND r.embedding IS NULL
                ORDER BY r.released_at DESC
                LIMIT 500
            """)).fetchall()

        if unembedded:
            logger.info(f"  Embedding {len(unembedded)} releases...")
            texts = []
            ids = []
            for r in unembedded:
                rm = r._mapping
                texts.append(build_release_text(
                    project_name=rm["project_name"],
                    version=rm["version"],
                    title=rm["title"],
                    summary=rm["summary"],
                ))
                ids.append(rm["id"])

            vectors = await embed_batch(texts)
            with engine.connect() as conn:
                for rid, vec in zip(ids, vectors):
                    if vec is not None:
                        conn.execute(
                            text("UPDATE releases SET embedding = :vec WHERE id = :id"),
                            {"vec": str(vec), "id": rid},
                        )
                        embed_count += 1
                conn.commit()
            logger.info(f"  Embedded {embed_count}/{len(unembedded)} releases")

    # ── Normal ingest: fetch new releases ──
    # Pre-fetch existing URLs to skip LLM calls for known releases
    with engine.connect() as conn:
        existing = conn.execute(text("SELECT url FROM releases")).fetchall()
    existing_urls: set[str] = {r[0] for r in existing}
    logger.info(f"Pre-seeded {len(existing_urls)} existing release URLs for dedup")

    semaphore = asyncio.Semaphore(5)
    tasks = [collect_releases_for_project(p, semaphore, existing_urls) for p in projects]
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
                    result = conn.execute(
                        text("""
                            INSERT INTO releases (project_id, lab_id, version, title, summary, body, url, released_at, captured_at, source)
                            VALUES (:project_id, :lab_id, :version, :title, :summary, :body, :url, :released_at, :captured_at, :source)
                            ON CONFLICT (url) DO NOTHING
                            RETURNING id
                        """),
                        rel,
                    )
                    if result.fetchone():
                        new_count += 1
                except Exception:
                    pass  # skip duplicates
            conn.commit()
        logger.info(f"Inserted {new_count} new releases (skipped {len(releases) - new_count} duplicates)")

    # Embed newly ingested releases
    new_embed_count = 0
    if embeddings_enabled() and new_count > 0:
        with engine.connect() as conn:
            new_unembedded = conn.execute(text("""
                SELECT r.id, p.name as project_name, r.version, r.title, r.summary
                FROM releases r
                JOIN projects p ON p.id = r.project_id
                WHERE r.summary IS NOT NULL
                  AND r.embedding IS NULL
                  AND r.captured_at >= :since
                ORDER BY r.id
            """), {"since": started_at}).fetchall()

        if new_unembedded:
            texts = []
            ids = []
            for r in new_unembedded:
                rm = r._mapping
                texts.append(build_release_text(
                    project_name=rm["project_name"],
                    version=rm["version"],
                    title=rm["title"],
                    summary=rm["summary"],
                ))
                ids.append(rm["id"])

            vectors = await embed_batch(texts)
            with engine.connect() as conn:
                for rid, vec in zip(ids, vectors):
                    if vec is not None:
                        conn.execute(
                            text("UPDATE releases SET embedding = :vec WHERE id = :id"),
                            {"vec": str(vec), "id": rid},
                        )
                        new_embed_count += 1
                conn.commit()
            logger.info(f"  Embedded {new_embed_count} newly ingested releases")

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

    logger.info(f"Releases ingest complete: {new_count} new, {error_count} errors, "
                f"{healed} re-summarised, {embed_count + new_embed_count} embedded, {llm_calls} LLM calls")
    return {
        "success": new_count,
        "errors": error_count,
        "healed": healed,
        "embedded": embed_count + new_embed_count,
        "llm_calls": llm_calls,
    }
