"""Detect PyPI/npm packages for ai_repos and fetch download counts.

Two phases per run:
  A) Detect — for repos never checked, try to match a published package
  B) Refresh — for repos with matched packages, fetch fresh download counts

Run standalone:  python -m app.ingest.ai_repo_downloads [detect_limit] [refresh_limit]
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.ingest.downloads import fetch_pypi_downloads, fetch_npm_downloads, fetch_crate_downloads
from app.models import SyncLog

logger = logging.getLogger(__name__)

PYPI_LANGUAGES = {"Python", "Jupyter Notebook"}
NPM_LANGUAGES = {"JavaScript", "TypeScript"}
CRATE_LANGUAGES = {"Rust"}


# ---------------------------------------------------------------------------
# Name variant generators
# ---------------------------------------------------------------------------

def _pypi_candidates(repo_name: str) -> list[str]:
    """Generate candidate PyPI package names from a repo name."""
    name = repo_name.lower()
    candidates = [name, name.replace("-", "_"), name.replace("_", "-")]
    for suffix in ["-python", "-py", ".py", "-lib"]:
        if name.endswith(suffix):
            candidates.append(name[: -len(suffix)])
    for prefix in ["python-", "py-"]:
        if name.startswith(prefix):
            candidates.append(name[len(prefix) :])
    return list(dict.fromkeys(candidates))  # dedupe preserving order


def _npm_candidates(owner: str, repo_name: str) -> list[str]:
    """Generate candidate npm package names from a repo name."""
    name = repo_name.lower()
    candidates = [name, f"@{owner.lower()}/{name}"]
    for suffix in ["-js", "-node", ".js"]:
        if name.endswith(suffix):
            candidates.append(name[: -len(suffix)])
    for prefix in ["node-", "js-"]:
        if name.startswith(prefix):
            candidates.append(name[len(prefix) :])
    return list(dict.fromkeys(candidates))


# ---------------------------------------------------------------------------
# GitHub URL verification
# ---------------------------------------------------------------------------

def _pypi_matches_repo(pypi_data: dict, owner: str, repo: str) -> bool:
    """Check if a PyPI package's metadata points back to the GitHub repo."""
    slug = f"{owner}/{repo}".lower()
    info = pypi_data.get("info", {})
    # Check project_urls
    for url in (info.get("project_urls") or {}).values():
        if url and slug in url.lower():
            return True
    # Check home_page
    home = info.get("home_page") or ""
    if slug in home.lower():
        return True
    # Check package_url or project_url
    for key in ("package_url", "project_url"):
        val = info.get(key) or ""
        if slug in val.lower():
            return True
    return False


def _npm_matches_repo(npm_data: dict, owner: str, repo: str) -> bool:
    """Check if an npm package's metadata points back to the GitHub repo."""
    slug = f"{owner}/{repo}".lower()
    repo_field = npm_data.get("repository") or {}
    if isinstance(repo_field, dict):
        url = (repo_field.get("url") or "").lower()
    else:
        url = str(repo_field).lower()
    return slug in url


def _is_pypi_candidate(language: str | None, topics: list | None) -> bool:
    if language in PYPI_LANGUAGES:
        return True
    if topics and any(t in {"python", "pip", "pypi"} for t in topics):
        return True
    return False


def _is_npm_candidate(language: str | None, topics: list | None) -> bool:
    if language in NPM_LANGUAGES:
        return True
    if topics and any(t in {"npm", "nodejs", "node"} for t in topics):
        return True
    return False


def _is_crate_candidate(language: str | None, topics: list | None) -> bool:
    if language in CRATE_LANGUAGES:
        return True
    if topics and any(t in {"rust", "crate", "cargo"} for t in topics):
        return True
    return False


def _crate_candidates(repo_name: str) -> list[str]:
    """Generate candidate crate names from a repo name."""
    name = repo_name.lower()
    candidates = [name, name.replace("_", "-"), name.replace("-", "_")]
    for suffix in ["-rs", "-rust"]:
        if name.endswith(suffix):
            candidates.append(name[: -len(suffix)])
    return list(dict.fromkeys(candidates))


def _crate_matches_repo(crate_data: dict, owner: str, repo: str) -> bool:
    """Check if a crate's metadata points back to the GitHub repo."""
    slug = f"{owner}/{repo}".lower()
    crate = crate_data.get("crate", {})
    repo_url = (crate.get("repository") or "").lower()
    if slug in repo_url:
        return True
    homepage = (crate.get("homepage") or "").lower()
    if slug in homepage:
        return True
    return False


# ---------------------------------------------------------------------------
# Detection: try to match repo → package
# ---------------------------------------------------------------------------

async def _detect_pypi(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    owner: str,
    repo: str,
    repo_name: str,
) -> str | None:
    """Try candidate names against PyPI JSON API. Return matched package or None."""
    from app.ingest.budget import acquire_budget, record_throttle, record_success
    for candidate in _pypi_candidates(repo_name):
        async with semaphore:
            if not await acquire_budget("pypi"):
                return None
            try:
                resp = await client.get(f"https://pypi.org/pypi/{candidate}/json")
            except httpx.HTTPError:
                continue

        if resp.status_code == 200:
            await record_success("pypi")
            data = resp.json()
            if _pypi_matches_repo(data, owner, repo):
                return candidate
        elif resp.status_code == 429:
            await record_throttle("pypi")
            return None
    return None


async def _detect_npm(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    owner: str,
    repo: str,
    repo_name: str,
) -> str | None:
    """Try candidate names against npm registry. Return matched package or None."""
    from app.ingest.budget import acquire_budget, record_throttle, record_success
    for candidate in _npm_candidates(owner, repo_name):
        async with semaphore:
            if not await acquire_budget("npm"):
                return None
            try:
                resp = await client.get(f"https://registry.npmjs.org/{candidate}")
            except httpx.HTTPError:
                continue

        if resp.status_code == 200:
            await record_success("npm")
            data = resp.json()
            if _npm_matches_repo(data, owner, repo):
                return candidate
        elif resp.status_code == 429:
            await record_throttle("npm")
            return None
    return None


async def _detect_crate(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    owner: str,
    repo: str,
    repo_name: str,
) -> str | None:
    """Try candidate names against crates.io API. Return matched crate or None."""
    from app.ingest.budget import acquire_budget, record_throttle, record_success
    for candidate in _crate_candidates(repo_name):
        async with semaphore:
            if not await acquire_budget("crates"):
                return None
            try:
                resp = await client.get(
                    f"https://crates.io/api/v1/crates/{candidate}",
                    headers={"User-Agent": "pt-edge/1.0 (https://github.com/pt-edge)"},
                )
            except httpx.HTTPError:
                continue

        if resp.status_code == 200:
            await record_success("crates")
            data = resp.json()
            if _crate_matches_repo(data, owner, repo):
                return candidate
        elif resp.status_code == 429:
            await record_throttle("crates")
            return None
    return None


# ---------------------------------------------------------------------------
# Batch DB writes
# ---------------------------------------------------------------------------

def _batch_update(updates: list[tuple]) -> int:
    """Batch update ai_repos with package names and download counts.

    Each tuple: (id, pypi_package, npm_package, crate_package, downloads_monthly)
    """
    if not updates:
        return 0
    from psycopg2.extras import execute_values

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        cur.execute("""
            CREATE TEMP TABLE _dl_batch (
                id INTEGER PRIMARY KEY,
                pypi_package VARCHAR(200),
                npm_package VARCHAR(200),
                crate_package VARCHAR(200),
                downloads_monthly BIGINT
            ) ON COMMIT DROP
        """)
        execute_values(
            cur,
            "INSERT INTO _dl_batch (id, pypi_package, npm_package, crate_package, downloads_monthly) VALUES %s",
            updates,
            template="(%s, %s, %s, %s, %s)",
            page_size=500,
        )
        cur.execute("""
            UPDATE ai_repos a SET
                pypi_package = b.pypi_package,
                npm_package = b.npm_package,
                crate_package = b.crate_package,
                downloads_monthly = b.downloads_monthly,
                downloads_checked_at = NOW()
            FROM _dl_batch b
            WHERE a.id = b.id
        """)
        count = cur.rowcount
        raw_conn.commit()
        return count
    except Exception as e:
        try:
            raw_conn.rollback()
        except Exception:
            pass
        logger.error(f"Batch update downloads failed: {e}")
        return 0
    finally:
        try:
            raw_conn.close()
        except Exception:
            pass


def _mark_checked(ids: list[int]) -> None:
    """Mark repos as checked even if no package was found."""
    if not ids:
        return
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE ai_repos SET downloads_checked_at = NOW() WHERE id = ANY(:ids)"),
            {"ids": ids},
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

async def ingest_ai_repo_downloads(
    detect_limit: int = 5000,
    refresh_limit: int = 10000,
) -> dict:
    """Detect packages and fetch download counts for ai_repos."""
    started_at = datetime.now(timezone.utc)
    detected = 0
    refreshed = 0
    errors = 0

    pypi_sem = asyncio.Semaphore(2)
    npm_sem = asyncio.Semaphore(3)
    crate_sem = asyncio.Semaphore(1)  # crates.io: 1 req/sec
    dl_sem = asyncio.Semaphore(3)

    async with httpx.AsyncClient(
        headers={"User-Agent": "pt-edge/1.0"}, timeout=30.0
    ) as client:

        # ---- Phase A: Detect new packages ----
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, github_owner, github_repo, name, language, topics
                FROM ai_repos
                WHERE downloads_checked_at IS NULL AND archived = false
                ORDER BY stars DESC
                LIMIT :lim
            """), {"lim": detect_limit}).fetchall()

        if rows:
            logger.info(f"Phase A: detecting packages for {len(rows)} repos")

            updates: list[tuple] = []
            no_match_ids: list[int] = []

            for r in rows:
                m = r._mapping
                rid = m["id"]
                owner = m["github_owner"]
                repo = m["github_repo"]
                repo_name = m["name"]
                language = m["language"]
                topics = list(m["topics"]) if m["topics"] else []

                pypi_pkg = None
                npm_pkg = None
                crate_pkg = None
                dl_monthly = 0

                try:
                    # Try PyPI
                    if _is_pypi_candidate(language, topics):
                        pypi_pkg = await _detect_pypi(client, pypi_sem, owner, repo, repo_name)
                        if pypi_pkg:
                            async with dl_sem:
                                stats = await fetch_pypi_downloads(client, pypi_pkg)
                            if stats:
                                dl_monthly += stats["last_month"]

                    # Try npm
                    if _is_npm_candidate(language, topics):
                        npm_pkg = await _detect_npm(client, npm_sem, owner, repo, repo_name)
                        if npm_pkg:
                            async with dl_sem:
                                stats = await fetch_npm_downloads(client, npm_pkg)
                            if stats:
                                dl_monthly += stats["last_month"]

                    # Try crates.io
                    if _is_crate_candidate(language, topics):
                        crate_pkg = await _detect_crate(client, crate_sem, owner, repo, repo_name)
                        if crate_pkg:
                            async with dl_sem:
                                stats = await fetch_crate_downloads(client, crate_pkg)
                            if stats:
                                dl_monthly += stats["last_month"]

                    # Normalize package names to match package_deps convention
                    if pypi_pkg:
                        pypi_pkg = pypi_pkg.lower().replace("_", "-")
                    if npm_pkg:
                        npm_pkg = npm_pkg.lower()

                    if pypi_pkg or npm_pkg or crate_pkg:
                        updates.append((rid, pypi_pkg, npm_pkg, crate_pkg, dl_monthly))
                        logger.info(
                            f"  {owner}/{repo} → pypi={pypi_pkg} npm={npm_pkg} "
                            f"crate={crate_pkg} dl={dl_monthly:,}/mo"
                        )
                    else:
                        no_match_ids.append(rid)

                except Exception as e:
                    logger.warning(f"Detection error for {owner}/{repo}: {e}")
                    no_match_ids.append(rid)
                    errors += 1

            detected = _batch_update(updates)
            _mark_checked(no_match_ids)
            logger.info(
                f"Phase A complete: {detected} matched, "
                f"{len(no_match_ids)} no match"
            )

        # ---- Phase B: Refresh existing packages ----
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, pypi_package, npm_package, crate_package
                FROM ai_repos
                WHERE (pypi_package IS NOT NULL OR npm_package IS NOT NULL
                       OR crate_package IS NOT NULL)
                  AND downloads_checked_at < NOW() - INTERVAL '7 days'
                ORDER BY stars DESC
                LIMIT :lim
            """), {"lim": refresh_limit}).fetchall()

        if rows:
            logger.info(f"Phase B: refreshing downloads for {len(rows)} repos")

            updates = []
            for r in rows:
                m = r._mapping
                rid = m["id"]
                dl_monthly = 0

                try:
                    if m["pypi_package"]:
                        async with dl_sem:
                            stats = await fetch_pypi_downloads(client, m["pypi_package"])
                        if stats:
                            dl_monthly += stats["last_month"]

                    if m["npm_package"]:
                        async with dl_sem:
                            stats = await fetch_npm_downloads(client, m["npm_package"])
                        if stats:
                            dl_monthly += stats["last_month"]

                    if m["crate_package"]:
                        async with dl_sem:
                            stats = await fetch_crate_downloads(client, m["crate_package"])
                        if stats:
                            dl_monthly += stats["last_month"]

                    updates.append((rid, m["pypi_package"], m["npm_package"], m["crate_package"], dl_monthly))
                except Exception as e:
                    logger.warning(f"Refresh error for repo {rid}: {e}")
                    errors += 1

            refreshed = _batch_update(updates)
            logger.info(f"Phase B complete: {refreshed} refreshed")

    # ---- Sync log ----
    _log_sync(started_at, detected + refreshed, f"{errors} errors" if errors else None)

    result = {"detected": detected, "refreshed": refreshed, "errors": errors}
    logger.info(f"ai_repo_downloads complete: {result}")
    return result


def _log_sync(started_at: datetime, records: int, error: str | None) -> None:
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="ai_repo_downloads",
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
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    detect = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    refresh = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    result = await ingest_ai_repo_downloads(detect_limit=detect, refresh_limit=refresh)
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
