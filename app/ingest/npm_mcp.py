"""Discover MCP servers published on npm that lack GitHub topic tags.

Searches the npm registry for packages with MCP-related keywords,
resolves their GitHub repos, fetches metadata via GitHub API,
and upserts into ai_repos with domain='mcp'.

Run standalone:  python -m app.ingest.npm_mcp
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

NPM_SEARCH_URL = "https://registry.npmjs.org/-/v1/search"
SEARCH_KEYWORDS = ["keywords:mcp-server", "keywords:model-context-protocol"]
MAX_PER_QUERY = 250  # npm search caps at 250


def _extract_github_slug(url: str | None) -> str | None:
    """Extract 'owner/repo' from a GitHub URL."""
    if not url:
        return None
    m = re.search(r"github\.com[/:]([^/]+)/([^/.#?]+)", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


async def _search_npm(client: httpx.AsyncClient) -> list[dict]:
    """Search npm registry for MCP-related packages. Returns package metadata."""
    seen_names: set[str] = set()
    packages: list[dict] = []

    for keyword in SEARCH_KEYWORDS:
        offset = 0
        while offset < MAX_PER_QUERY:
            try:
                resp = await client.get(
                    NPM_SEARCH_URL,
                    params={"text": keyword, "size": 250, "from": offset},
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(f"npm search failed for '{keyword}' at offset {offset}: {e}")
                break

            objects = data.get("objects", [])
            if not objects:
                break

            for obj in objects:
                pkg = obj.get("package", {})
                name = pkg.get("name", "")
                if name and name not in seen_names:
                    seen_names.add(name)
                    # Extract repo URL from links or repository
                    links = pkg.get("links", {})
                    repo_url = links.get("repository") or links.get("homepage") or ""
                    packages.append({
                        "npm_name": name,
                        "description": pkg.get("description", ""),
                        "repo_url": repo_url,
                    })

            # npm search total indicates available results
            total = data.get("total", 0)
            offset += len(objects)
            if offset >= total or offset >= MAX_PER_QUERY:
                break
            await asyncio.sleep(0.5)  # be polite to npm

    logger.info(f"Found {len(packages)} npm packages across {len(SEARCH_KEYWORDS)} keyword searches")
    return packages


async def _fetch_github_metadata(
    client: httpx.AsyncClient, slug: str, semaphore: asyncio.Semaphore,
) -> dict | None:
    """Fetch repo metadata from GitHub API."""
    async with semaphore:
        try:
            resp = await client.get(f"https://api.github.com/repos/{slug}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.debug(f"GitHub fetch failed for {slug}: {e}")
            return None
        await asyncio.sleep(0.2)  # stay under rate limit

    return {
        "github_owner": data.get("owner", {}).get("login", ""),
        "github_repo": data.get("name", ""),
        "full_name": data.get("full_name", slug),
        "name": data.get("name", ""),
        "description": data.get("description"),
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "language": data.get("language"),
        "topics": data.get("topics") or None,
        "license": (data.get("license") or {}).get("spdx_id"),
        "last_pushed_at": data.get("pushed_at"),
        "archived": data.get("archived", False),
        "domain": "mcp",
    }


def _batch_upsert(repos: list[dict], npm_names: dict[str, str]) -> int:
    """Upsert repos into ai_repos, setting npm_package column."""
    if not repos:
        return 0
    from psycopg2.extras import execute_values

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        tuples = [
            (
                r["github_owner"], r["github_repo"], r["full_name"], r["name"],
                r["description"], r["stars"], r["forks"], r["language"],
                r["topics"], r["license"], r["last_pushed_at"], r["archived"],
                r["domain"],
                npm_names.get(r["full_name"].lower(), ""),
            )
            for r in repos
        ]
        execute_values(
            cur,
            """
            INSERT INTO ai_repos (
                github_owner, github_repo, full_name, name, description,
                stars, forks, language, topics, license,
                last_pushed_at, archived, domain, npm_package, updated_at
            ) VALUES %s
            ON CONFLICT (github_owner, github_repo) DO UPDATE SET
                description = COALESCE(EXCLUDED.description, ai_repos.description),
                stars = EXCLUDED.stars,
                forks = EXCLUDED.forks,
                language = EXCLUDED.language,
                topics = EXCLUDED.topics,
                license = EXCLUDED.license,
                last_pushed_at = EXCLUDED.last_pushed_at,
                archived = EXCLUDED.archived,
                domain = CASE
                    WHEN ai_repos.domain = 'uncategorized' THEN EXCLUDED.domain
                    ELSE ai_repos.domain
                END,
                npm_package = CASE
                    WHEN ai_repos.npm_package IS NULL OR ai_repos.npm_package = ''
                    THEN EXCLUDED.npm_package
                    ELSE ai_repos.npm_package
                END,
                updated_at = NOW()
            """,
            tuples,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
            page_size=500,
        )
        raw_conn.commit()
        return len(tuples)
    except Exception as e:
        try:
            raw_conn.rollback()
        except Exception:
            pass
        logger.error(f"npm_mcp batch upsert failed: {e}")
        return 0
    finally:
        try:
            raw_conn.close()
        except Exception:
            pass


async def ingest_npm_mcp() -> dict:
    """Discover MCP servers from npm and upsert into ai_repos."""
    started_at = datetime.now(timezone.utc)

    gh_headers = {"User-Agent": "pt-edge/1.0", "Accept": "application/vnd.github+json"}
    if settings.GITHUB_TOKEN:
        gh_headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    # Step 1: Search npm
    async with httpx.AsyncClient(
        headers={"User-Agent": "pt-edge/1.0"},
        timeout=30.0,
        follow_redirects=True,
    ) as npm_client:
        packages = await _search_npm(npm_client)

    # Step 2: Extract GitHub slugs and dedup against existing ai_repos
    slug_to_npm: dict[str, str] = {}  # lowercase slug -> npm package name
    for pkg in packages:
        slug = _extract_github_slug(pkg["repo_url"])
        if slug:
            slug_to_npm.setdefault(slug.lower(), pkg["npm_name"])

    with engine.connect() as conn:
        existing = conn.execute(text(
            "SELECT LOWER(full_name) FROM ai_repos"
        )).fetchall()
    seen = {r[0] for r in existing}

    new_slugs = [s for s in slug_to_npm if s not in seen]
    logger.info(f"npm: {len(slug_to_npm)} packages with GitHub repos, {len(new_slugs)} new")

    if not new_slugs:
        _log_sync(started_at, 0, None)
        return {"npm_packages": len(packages), "with_github": len(slug_to_npm), "new": 0, "upserted": 0}

    # Step 3: Fetch GitHub metadata for new repos
    semaphore = asyncio.Semaphore(5)
    async with httpx.AsyncClient(
        headers=gh_headers,
        timeout=30.0,
        follow_redirects=True,
    ) as gh_client:
        tasks = [
            _fetch_github_metadata(gh_client, slug, semaphore)
            for slug in new_slugs
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    repos = [r for r in results if isinstance(r, dict)]
    logger.info(f"Fetched GitHub metadata for {len(repos)}/{len(new_slugs)} repos")

    # Step 4: Upsert
    # Build full_name -> npm_name mapping for upsert
    npm_names = {slug: name for slug, name in slug_to_npm.items()}
    upserted = _batch_upsert(repos, npm_names)
    logger.info(f"Upserted {upserted} MCP repos from npm")

    _log_sync(started_at, upserted, None)
    return {
        "npm_packages": len(packages),
        "with_github": len(slug_to_npm),
        "new": len(new_slugs),
        "upserted": upserted,
    }


def _log_sync(started_at: datetime, records: int, error: str | None) -> None:
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="npm_mcp",
            status="success" if not error else "partial",
            records_written=records,
            error_message=error,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()


async def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = await ingest_npm_mcp()
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
