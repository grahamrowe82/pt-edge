"""Ingest AI-related posts from V2EX (Chinese developer community).

Polls AI-focused nodes (openai, claude, claudecode) plus hot/latest feeds
with client-side filtering. Mirrors the HN ingest pattern.
Uses V2EX API v1 (public, no auth required, 120 req/hr).
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.ingest.llm import call_llm_text
from app.models import Project, Lab, SyncLog
from app.settings import settings
from app.ingest.hn import (
    SEARCH_TERMS, LAB_ALIASES, GITHUB_REPO_RE,
    _match_project, _match_lab,
)

logger = logging.getLogger(__name__)

V2EX_API = "https://www.v2ex.com/api"

# AI-focused nodes — ingest everything, manageable volume
TARGET_NODES = ["openai", "claude", "claudecode"]

# Combined filter terms for hot/latest scanning (lowercase)
_BROAD_FILTER_TERMS = {t.lower() for t in SEARCH_TERMS} | set(LAB_ALIASES.keys())

# Rate limiting now handled by acquire_budget("v2ex") — 10 RPM in DB.


def _matches_broad_filter(title: str, content: str | None) -> bool:
    """Check if a V2EX post from hot/latest feed is AI-related."""
    text_lower = f"{title} {content or ''}".lower()
    return any(term in text_lower for term in _BROAD_FILTER_TERMS)


V2EX_FILTER_PROMPT = """\
Is this Chinese developer forum post about AI, machine learning, LLMs, \
or related developer tools? Consider both the title and content.

Title: {title}
Content (first 500 chars): {content_preview}

Return ONLY "yes" or "no"."""


async def _llm_ai_filter(title: str, content: str) -> bool:
    """Use LLM to determine if a V2EX post is AI-related. Haiku understands Chinese."""
    prompt = V2EX_FILTER_PROMPT.format(
        title=title,
        content_preview=(content or "")[:500],
    )
    result = await call_llm_text(prompt, max_tokens=10)
    return result is not None and result.strip().lower().startswith("yes")


async def fetch_node_topics(
    client: httpx.AsyncClient, node_name: str,
) -> list[dict]:
    """Fetch recent topics from a V2EX node (v1 API, no auth)."""
    from app.ingest.budget import acquire_budget
    if not await acquire_budget("v2ex"):
        return []
    resp = await client.get(
        f"{V2EX_API}/topics/show.json",
        params={"node_name": node_name},
    )
    if resp.status_code == 200:
        data = resp.json()
        return data if isinstance(data, list) else []
    logger.warning(f"V2EX API {resp.status_code} for node '{node_name}'")
    return []


async def fetch_hot_topics(client: httpx.AsyncClient) -> list[dict]:
    """Fetch hot topics across all of V2EX (v1 API, no auth)."""
    from app.ingest.budget import acquire_budget
    if not await acquire_budget("v2ex"):
        return []
    resp = await client.get(f"{V2EX_API}/topics/hot.json")
    if resp.status_code == 200:
        data = resp.json()
        return data if isinstance(data, list) else []
    logger.warning(f"V2EX hot.json returned {resp.status_code}")
    return []


async def fetch_latest_topics(client: httpx.AsyncClient) -> list[dict]:
    """Fetch latest topics across all of V2EX (v1 API, no auth)."""
    from app.ingest.budget import acquire_budget
    if not await acquire_budget("v2ex"):
        return []
    resp = await client.get(f"{V2EX_API}/topics/latest.json")
    if resp.status_code == 200:
        data = resp.json()
        return data if isinstance(data, list) else []
    logger.warning(f"V2EX latest.json returned {resp.status_code}")
    return []


def _build_row(topic: dict, projects: list, lab_slug_to_id: dict) -> dict | None:
    """Convert a V2EX topic dict to a DB row dict."""
    v2ex_id = topic.get("id")
    title = topic.get("title")
    created = topic.get("created")
    if not v2ex_id or not title or not created:
        return None

    member = topic.get("member") or {}
    node = topic.get("node") or {}
    content = topic.get("content") or ""

    # Match lab against title + content for richer signal
    match_text = f"{title} {content}"
    lab_id = _match_lab(match_text, lab_slug_to_id)

    return {
        "v2ex_id": v2ex_id,
        "title": title,
        "url": f"https://www.v2ex.com/t/{v2ex_id}",
        "content": content[:5000] if content else None,  # cap stored content
        "author": member.get("username", "unknown"),
        "replies": topic.get("replies", 0),
        "node_name": node.get("name"),
        "posted_at": datetime.fromtimestamp(created, tz=timezone.utc),
        "captured_at": datetime.now(timezone.utc),
        "project_id": _match_project(title, projects, url=None),
        "lab_id": lab_id,
    }


async def ingest_v2ex() -> dict:
    """Fetch recent V2EX posts from AI-related nodes + hot/latest feeds."""
    session = SessionLocal()
    projects = session.query(Project).filter(Project.is_active.is_(True)).all()
    labs = session.query(Lab).all()
    lab_slug_to_id = {lab.slug: lab.id for lab in labs}
    session.close()

    started_at = datetime.now(timezone.utc)
    all_posts = []
    seen_ids: set[int] = set()
    error_count = 0

    headers = {"User-Agent": "pt-edge/1.0"}

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        # Target nodes: fetch recent topics (v1 returns ~10-20 per node)
        for node in TARGET_NODES:
            try:
                topics = await fetch_node_topics(client, node)
                for t in topics:
                    row = _build_row(t, projects, lab_slug_to_id)
                    if row and row["v2ex_id"] not in seen_ids:
                        seen_ids.add(row["v2ex_id"])
                        all_posts.append(row)
            except Exception as e:
                error_count += 1
                logger.error(f"V2EX fetch error ({node}): {e}")

        # Hot + latest feeds: filter client-side for AI content
        for label, fetcher in [("hot", fetch_hot_topics), ("latest", fetch_latest_topics)]:
            try:
                topics = await fetcher(client)
                for t in topics:
                    title = t.get("title", "")
                    content = t.get("content", "")
                    is_relevant = _matches_broad_filter(title, content)
                    if not is_relevant and settings.GEMINI_API_KEY:
                        is_relevant = await _llm_ai_filter(title, content)
                    if is_relevant:
                        row = _build_row(t, projects, lab_slug_to_id)
                        if row and row["v2ex_id"] not in seen_ids:
                            seen_ids.add(row["v2ex_id"])
                            all_posts.append(row)
            except Exception as e:
                error_count += 1
                logger.error(f"V2EX fetch error ({label}): {e}")

    # Batch insert
    new_count = 0
    if all_posts:
        with engine.connect() as conn:
            for post in all_posts:
                try:
                    conn.execute(
                        text("""
                            INSERT INTO v2ex_posts
                                (v2ex_id, title, url, content, author, replies,
                                 node_name, posted_at, captured_at, project_id, lab_id)
                            VALUES
                                (:v2ex_id, :title, :url, :content, :author, :replies,
                                 :node_name, :posted_at, :captured_at, :project_id, :lab_id)
                            ON CONFLICT (v2ex_id) DO NOTHING
                        """),
                        post,
                    )
                    new_count += 1
                except Exception:
                    pass
            conn.commit()
        logger.info(f"V2EX: wrote {new_count} posts")

    # Extract GitHub candidates from content
    candidates_count = await _extract_v2ex_candidates(all_posts)

    # Log sync
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="v2ex",
            status="success" if error_count == 0 else "partial",
            records_written=new_count,
            error_message=f"{error_count} failures" if error_count else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    logger.info(f"V2EX ingest complete: {new_count} new, {error_count} errors, {candidates_count} candidates")
    return {"success": new_count, "errors": error_count, "candidates": candidates_count}


async def _extract_v2ex_candidates(posts: list[dict]) -> int:
    """Scan V2EX post content for GitHub repo URLs and insert as candidates."""
    repo_refs: dict[str, str] = {}
    for post in posts:
        source_url = post.get("url", "")
        for field in [post.get("content") or "", post.get("title") or ""]:
            for match in GITHUB_REPO_RE.finditer(field):
                owner, repo = match.group(1), match.group(2)
                repo = repo.removesuffix(".git")
                full = f"{owner}/{repo}".lower()
                if full not in repo_refs:
                    repo_refs[full] = source_url

    if not repo_refs:
        return 0

    session = SessionLocal()
    try:
        tracked = set()
        rows = session.execute(text(
            "SELECT LOWER(github_owner || '/' || github_repo) FROM projects WHERE github_owner IS NOT NULL"
        )).fetchall()
        for (key,) in rows:
            tracked.add(key)

        existing = set()
        rows = session.execute(text("SELECT github_url FROM project_candidates")).fetchall()
        for (url,) in rows:
            existing.add(url.lower())
    finally:
        session.close()

    new_refs = {
        full: source_url for full, source_url in repo_refs.items()
        if full not in tracked and f"https://github.com/{full}".lower() not in existing
    }

    if not new_refs:
        return 0

    headers = {"User-Agent": "pt-edge/1.0"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    candidates = []
    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        for full, source_url in new_refs.items():
            owner, repo = full.split("/", 1)
            try:
                resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
                if resp.status_code != 200:
                    continue
                data = resp.json()
                candidates.append({
                    "github_url": f"https://github.com/{owner}/{repo}",
                    "github_owner": owner,
                    "github_repo": repo,
                    "name": data.get("name"),
                    "description": (data.get("description") or "")[:500],
                    "stars": data.get("stargazers_count", 0),
                    "language": data.get("language"),
                    "topics": data.get("topics") or [],
                    "source": "v2ex",
                    "source_detail": source_url,
                })
            except Exception as e:
                logger.error(f"GitHub fetch error for {owner}/{repo}: {e}")
            await asyncio.sleep(0.1)

    if candidates:
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO project_candidates
                        (github_url, github_owner, github_repo, name, description,
                         stars, language, topics, source, source_detail)
                    VALUES
                        (:github_url, :github_owner, :github_repo, :name, :description,
                         :stars, :language, :topics, :source, :source_detail)
                    ON CONFLICT (github_url) DO NOTHING
                """),
                candidates,
            )
            conn.commit()
        logger.info(f"Inserted {len(candidates)} V2EX-sourced project candidates")

    return len(candidates)


async def backfill_v2ex_lab_links() -> int:
    """Match unlinked V2EX posts to labs by title+content. Idempotent."""
    session = SessionLocal()
    try:
        labs = session.query(Lab).all()
        lab_slug_to_id = {lab.slug: lab.id for lab in labs}
    finally:
        session.close()

    updated = 0
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, title, content FROM v2ex_posts WHERE lab_id IS NULL"
        )).fetchall()

        for row in rows:
            m = row._mapping
            match_text = f"{m['title']} {m.get('content') or ''}"
            lid = _match_lab(match_text, lab_slug_to_id)
            if lid:
                conn.execute(
                    text("UPDATE v2ex_posts SET lab_id = :lid WHERE id = :id"),
                    {"lid": lid, "id": m["id"]},
                )
                updated += 1
        conn.commit()

    logger.info(f"backfill_v2ex_lab_links: matched {updated} posts to labs")
    return updated
