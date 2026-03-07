import asyncio
import logging
import re
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import Project, SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

ALGOLIA_API = "https://hn.algolia.com/api/v1/search_by_date"

SEARCH_TERMS = [
    "LLM", "GPT", "Claude", "Anthropic", "OpenAI", "Gemini",
    "AI model", "machine learning", "transformer model",
    "fine-tuning", "RAG", "vector database", "AI agent",
    "AI assistant", "personal AI", "autonomous agent",
    "MCP server", "open source AI",
    "model context protocol", "AI security", "prompt injection", "LLM guard",
]

SECONDS_IN_7_DAYS = 7 * 24 * 60 * 60


def _determine_post_type(title: str) -> str:
    t = title.lower()
    if t.startswith("show hn:"):
        return "show"
    if t.startswith("ask hn:"):
        return "ask"
    return "link"


def _match_project(title: str, projects: list[Project]) -> int | None:
    title_lower = title.lower()
    for p in projects:
        if p.name and p.name.lower() in title_lower:
            return p.id
        if p.slug and p.slug.lower() in title_lower:
            return p.id
    return None


async def fetch_hn_page(client: httpx.AsyncClient, query: str, min_timestamp: int) -> list[dict]:
    params = {
        "query": query, "tags": "story",
        "numericFilters": f"points>10,created_at_i>{min_timestamp}",
        "hitsPerPage": 50,
    }
    resp = await client.get(ALGOLIA_API, params=params)
    if resp.status_code == 200:
        return resp.json().get("hits", [])
    logger.warning(f"HN Algolia API {resp.status_code} for '{query}'")
    return []


async def collect_hn_for_term(
    client: httpx.AsyncClient, term: str, min_timestamp: int,
    projects: list[Project], semaphore: asyncio.Semaphore,
) -> list[dict]:
    async with semaphore:
        hits = await fetch_hn_page(client, term, min_timestamp)
        await asyncio.sleep(1.0)

    rows = []
    seen_ids = set()
    for hit in hits:
        hn_id = hit.get("objectID")
        title = hit.get("title")
        created_at_i = hit.get("created_at_i")
        if not hn_id or not title or not created_at_i:
            continue
        try:
            hn_id_int = int(hn_id)
        except (ValueError, TypeError):
            continue
        if hn_id_int in seen_ids:
            continue
        seen_ids.add(hn_id_int)

        rows.append({
            "hn_id": hn_id_int,
            "title": title,
            "url": hit.get("url"),
            "author": hit.get("author", "unknown"),
            "points": hit.get("points", 0),
            "num_comments": hit.get("num_comments", 0),
            "post_type": _determine_post_type(title),
            "posted_at": datetime.fromtimestamp(created_at_i, tz=timezone.utc),
            "captured_at": datetime.now(timezone.utc),
            "project_id": _match_project(title, projects),
        })
    return rows


async def ingest_hn() -> dict:
    session = SessionLocal()
    projects = session.query(Project).filter(Project.is_active.is_(True)).all()
    session.close()

    min_timestamp = int(time.time()) - SECONDS_IN_7_DAYS
    logger.info(f"Ingesting HN posts for {len(SEARCH_TERMS)} search terms")
    started_at = datetime.now(timezone.utc)

    semaphore = asyncio.Semaphore(2)
    async with httpx.AsyncClient(headers={"User-Agent": "pt-edge/1.0"}, timeout=30.0) as client:
        tasks = [collect_hn_for_term(client, t, min_timestamp, projects, semaphore) for t in SEARCH_TERMS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_posts = []
    seen_hn_ids = set()
    error_count = 0
    for r in results:
        if isinstance(r, Exception):
            error_count += 1
            logger.error(f"HN fetch error: {r}")
        elif isinstance(r, list):
            for post in r:
                if post["hn_id"] not in seen_hn_ids:
                    seen_hn_ids.add(post["hn_id"])
                    all_posts.append(post)

    new_count = 0
    if all_posts:
        with engine.connect() as conn:
            for post in all_posts:
                try:
                    conn.execute(
                        text("""
                            INSERT INTO hn_posts (hn_id, title, url, author, points, num_comments,
                                                  post_type, posted_at, captured_at, project_id)
                            VALUES (:hn_id, :title, :url, :author, :points, :num_comments,
                                    :post_type, :posted_at, :captured_at, :project_id)
                            ON CONFLICT (hn_id) DO NOTHING
                        """),
                        post,
                    )
                    new_count += 1
                except Exception:
                    pass
            conn.commit()
        logger.info(f"Batch wrote {new_count} HN posts")

    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="hn", status="success" if error_count == 0 else "partial",
            records_written=new_count,
            error_message=f"{error_count} failures" if error_count else None,
            started_at=started_at, finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    # Extract project candidates from collected posts
    candidates_count = await _extract_candidates(all_posts)

    logger.info(f"HN ingest complete: {new_count} new posts, {error_count} errors, {candidates_count} candidates")
    return {"success": new_count, "errors": error_count, "candidates": candidates_count}


GITHUB_REPO_RE = re.compile(r"https?://github\.com/([^/]+)/([^/\s?#]+)")


async def _extract_candidates(posts: list[dict]) -> int:
    """Scan HN posts for GitHub repo URLs and insert untracked ones as candidates."""
    # Collect all GitHub repo refs from post URLs and titles
    repo_refs: dict[str, str] = {}  # "owner/repo" -> source HN URL
    for post in posts:
        hn_url = f"https://news.ycombinator.com/item?id={post['hn_id']}"
        for field in [post.get("url") or "", post.get("title") or ""]:
            for match in GITHUB_REPO_RE.finditer(field):
                owner, repo = match.group(1), match.group(2)
                # Strip trailing .git if present
                repo = repo.removesuffix(".git")
                full = f"{owner}/{repo}".lower()
                if full not in repo_refs:
                    repo_refs[full] = hn_url

    if not repo_refs:
        return 0

    # Get tracked projects to exclude
    session = SessionLocal()
    try:
        tracked = set()
        rows = session.execute(text(
            "SELECT LOWER(github_owner || '/' || github_repo) FROM projects WHERE github_owner IS NOT NULL"
        )).fetchall()
        for (key,) in rows:
            tracked.add(key)

        # Also exclude already-known candidates
        existing = set()
        rows = session.execute(text("SELECT github_url FROM project_candidates")).fetchall()
        for (url,) in rows:
            existing.add(url.lower())
    finally:
        session.close()

    # Filter out tracked and existing
    new_refs = {
        full: source_url for full, source_url in repo_refs.items()
        if full not in tracked and f"https://github.com/{full}".lower() not in existing
    }

    if not new_refs:
        return 0

    # Fetch GitHub stats for each new repo
    headers = {"User-Agent": "pt-edge/1.0"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    candidates = []
    semaphore = asyncio.Semaphore(5)
    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        for full, source_url in new_refs.items():
            owner, repo = full.split("/", 1)
            async with semaphore:
                try:
                    resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
                    if resp.status_code != 200:
                        logger.warning(f"GitHub API {resp.status_code} for {owner}/{repo}")
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
                        "source": "hn",
                        "source_detail": source_url,
                    })
                except Exception as e:
                    logger.error(f"Error fetching GitHub repo {owner}/{repo}: {e}")
                await asyncio.sleep(0.1)

    # Batch insert candidates
    if candidates:
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO project_candidates
                        (github_url, github_owner, github_repo, name, description, stars, language, topics, source, source_detail)
                    VALUES
                        (:github_url, :github_owner, :github_repo, :name, :description, :stars, :language, :topics, :source, :source_detail)
                    ON CONFLICT (github_url) DO NOTHING
                """),
                candidates,
            )
            conn.commit()
        logger.info(f"Inserted {len(candidates)} HN-sourced project candidates")

    return len(candidates)
