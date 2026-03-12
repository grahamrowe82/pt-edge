"""Fetch dependency lists for ai_repos with detected packages.

For PyPI: parses requires_dist from https://pypi.org/pypi/{pkg}/json
For npm: parses dependencies from https://registry.npmjs.org/{pkg}/latest

Run standalone:  python -m app.ingest.package_deps
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import SyncLog

logger = logging.getLogger(__name__)

# Regex to extract package name from PEP 508 requirement string
_PEP508_NAME = re.compile(r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_requires_dist(requires_dist: list[str] | None) -> list[dict]:
    """Parse PyPI requires_dist into structured deps."""
    if not requires_dist:
        return []
    deps = []
    for req in requires_dist:
        m = _PEP508_NAME.match(req.strip())
        if not m:
            continue
        name = m.group(1).lower().replace("_", "-")
        # Version spec is everything after name until ; or end
        rest = req[m.end():].strip()
        spec_part = rest.split(";")[0].strip().strip("()")
        # Heuristic: extras marker indicates optional/dev dependency
        is_dev = "extra ==" in req.lower() or "extra==" in req.lower()
        deps.append({
            "dep_name": name,
            "dep_spec": spec_part[:200] if spec_part else None,
            "source": "pypi",
            "is_dev": is_dev,
        })
    return deps


def _parse_npm_deps(data: dict) -> list[dict]:
    """Parse npm package.json dependencies."""
    deps = []
    for name, spec in (data.get("dependencies") or {}).items():
        deps.append({
            "dep_name": name[:200],
            "dep_spec": str(spec)[:200] if spec else None,
            "source": "npm",
            "is_dev": False,
        })
    for name, spec in (data.get("devDependencies") or {}).items():
        deps.append({
            "dep_name": name[:200],
            "dep_spec": str(spec)[:200] if spec else None,
            "source": "npm",
            "is_dev": True,
        })
    return deps


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

async def _fetch_pypi_deps(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, pkg: str,
) -> list[dict]:
    """Fetch dependency list from PyPI for a package."""
    async with sem:
        try:
            resp = await client.get(f"https://pypi.org/pypi/{pkg}/json")
            await asyncio.sleep(0.5)
        except httpx.HTTPError:
            return []
    if resp.status_code != 200:
        return []
    info = resp.json().get("info", {})
    return _parse_requires_dist(info.get("requires_dist"))


async def _fetch_npm_deps(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, pkg: str,
) -> list[dict]:
    """Fetch dependency list from npm for a package."""
    async with sem:
        try:
            resp = await client.get(f"https://registry.npmjs.org/{pkg}/latest")
            await asyncio.sleep(0.3)
        except httpx.HTTPError:
            return []
    if resp.status_code != 200:
        return []
    return _parse_npm_deps(resp.json())


# ---------------------------------------------------------------------------
# Batch DB writes
# ---------------------------------------------------------------------------

def _batch_upsert_deps(rows: list[tuple]) -> int:
    """Batch upsert (repo_id, dep_name, dep_spec, source, is_dev) into package_deps."""
    if not rows:
        return 0
    from psycopg2.extras import execute_values

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        execute_values(
            cur,
            """
            INSERT INTO package_deps (repo_id, dep_name, dep_spec, source, is_dev)
            VALUES %s
            ON CONFLICT (repo_id, dep_name, source) DO UPDATE SET
                dep_spec = EXCLUDED.dep_spec,
                fetched_at = NOW()
            """,
            rows,
            template="(%s, %s, %s, %s, %s)",
            page_size=500,
        )
        count = cur.rowcount
        raw_conn.commit()
        return count
    except Exception as e:
        try:
            raw_conn.rollback()
        except Exception:
            pass
        logger.error(f"Batch upsert deps failed: {e}")
        return 0
    finally:
        try:
            raw_conn.close()
        except Exception:
            pass


def _update_dep_counts(repo_ids: list[int]) -> None:
    """Update dependency_count and deps_fetched_at on ai_repos."""
    if not repo_ids:
        return
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE ai_repos a SET
                dependency_count = COALESCE(
                    (SELECT COUNT(*) FROM package_deps d
                     WHERE d.repo_id = a.id AND d.is_dev = false), 0),
                deps_fetched_at = NOW()
            WHERE a.id = ANY(:ids)
        """), {"ids": repo_ids})
        conn.commit()


def _mark_no_deps(repo_ids: list[int]) -> None:
    """Mark repos as checked even if no deps found."""
    if not repo_ids:
        return
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE ai_repos SET dependency_count = 0, deps_fetched_at = NOW()
            WHERE id = ANY(:ids)
        """), {"ids": repo_ids})
        conn.commit()


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

async def ingest_package_deps(batch_limit: int = 5000) -> dict:
    """Fetch dependencies for ai_repos with detected packages."""
    started_at = datetime.now(timezone.utc)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, pypi_package, npm_package
            FROM ai_repos
            WHERE (pypi_package IS NOT NULL OR npm_package IS NOT NULL)
              AND deps_fetched_at IS NULL
            ORDER BY stars DESC
            LIMIT :lim
        """), {"lim": batch_limit}).fetchall()

    if not rows:
        logger.info("No repos need dependency fetch")
        return {"processed": 0, "deps_stored": 0}

    logger.info(f"Fetching deps for {len(rows)} repos")
    pypi_sem = asyncio.Semaphore(2)
    npm_sem = asyncio.Semaphore(3)

    all_dep_rows: list[tuple] = []  # (repo_id, dep_name, dep_spec, source, is_dev)
    has_deps_ids: list[int] = []
    no_deps_ids: list[int] = []
    errors = 0

    async with httpx.AsyncClient(
        headers={"User-Agent": "pt-edge/1.0"}, timeout=30.0,
    ) as client:
        for r in rows:
            m = r._mapping
            repo_id = m["id"]
            deps: list[dict] = []

            try:
                if m["pypi_package"]:
                    deps.extend(await _fetch_pypi_deps(client, pypi_sem, m["pypi_package"]))
                if m["npm_package"]:
                    deps.extend(await _fetch_npm_deps(client, npm_sem, m["npm_package"]))
            except Exception as e:
                logger.warning(f"Dep fetch error for repo {repo_id}: {e}")
                errors += 1
                no_deps_ids.append(repo_id)
                continue

            if deps:
                # Deduplicate: same (repo_id, dep_name, source) can appear
                # multiple times with different extras/markers
                seen_keys: set[tuple] = set()
                for d in deps:
                    key = (repo_id, d["dep_name"], d["source"])
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    all_dep_rows.append((
                        repo_id, d["dep_name"], d["dep_spec"], d["source"], d["is_dev"],
                    ))
                has_deps_ids.append(repo_id)
            else:
                no_deps_ids.append(repo_id)

    stored = _batch_upsert_deps(all_dep_rows)
    _update_dep_counts(has_deps_ids)
    _mark_no_deps(no_deps_ids)

    _log_sync(started_at, stored, f"{errors} errors" if errors else None)

    result = {"processed": len(rows), "deps_stored": stored, "errors": errors}
    logger.info(f"package_deps complete: {result}")
    return result


def _log_sync(started_at: datetime, records: int, error: str | None) -> None:
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="package_deps",
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
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    result = await ingest_package_deps(batch_limit=limit)
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
