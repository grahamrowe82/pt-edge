"""Ingest AI/ML repos from GitHub Search API.

Discovers repos across multiple domains (MCP, agents, RAG, LLM tools, etc.)
using adaptive sub-sharding to get past the 1,000-result-per-query limit.
Embeds descriptions at 256d for semantic search via find_ai_tool().

Run standalone:  python -m app.ingest.ai_repos [domain ...]
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.embeddings import build_ai_repo_text, embed_batch, is_enabled
from app.ingest.ai_repo_domains import DOMAINS, DOMAIN_ORDER, DOMAIN_OVERRIDES, FOUNDATIONAL_SEEDS
from app.ingest.github_search import (
    adaptive_search, BudgetExhausted, CallCounter,
)
from app.models import SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

AI_REPO_EMBED_DIM = 256


def _is_full_crawl_day() -> bool:
    """Return True if today is the first Saturday of the month."""
    today = datetime.now(timezone.utc).date()
    if today.weekday() != 5:  # 5 = Saturday
        return False
    return today.day <= 7


def _get_last_successful_sync() -> datetime | None:
    """Return finished_at of the last successful ai_repos sync, or None."""
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT finished_at FROM sync_log
            WHERE sync_type = 'ai_repos' AND status IN ('success', 'partial')
            ORDER BY finished_at DESC LIMIT 1
        """)).fetchone()
    if row and row[0]:
        return row[0]
    return None


async def ingest_ai_repos(
    domains: list[str] | None = None,
    force_full: bool = False,
) -> dict:
    """Discover and upsert AI repos from GitHub Search API.

    Args:
        domains: specific domain keys to ingest, or None for all.
        force_full: if True, skip incremental mode and crawl everything.
    """
    started_at = datetime.now(timezone.utc)

    # Ensure foundational seed repos are present with package names
    seeds_updated = await _ensure_seeds()
    if seeds_updated:
        logger.info(f"Foundational seeds: {seeds_updated} package names set")

    # Determine incremental vs full crawl
    pushed_after: str | None = None
    if force_full or _is_full_crawl_day():
        logger.info("Full crawl mode" + (" (forced)" if force_full else " (first Saturday)"))
    else:
        last_sync = _get_last_successful_sync()
        if last_sync:
            cutoff = last_sync - timedelta(days=2)
            pushed_after = cutoff.strftime("%Y-%m-%d")
            logger.info(f"Incremental crawl: pushed:>={pushed_after}")
        else:
            logger.info("Full crawl mode (no prior successful sync)")

    headers = {"User-Agent": "pt-edge/1.0", "Accept": "application/vnd.github+json"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    semaphore = asyncio.Semaphore(2)  # conservative for Search API
    counter = CallCounter(budget=3000)

    # Pre-seed dedup set from DB so we skip already-known repos
    with engine.connect() as conn:
        existing = conn.execute(text(
            "SELECT LOWER(full_name) FROM ai_repos"
        )).fetchall()
    seen: set[str] = {r[0] for r in existing}
    logger.info(f"Pre-seeded {len(seen)} existing repos into dedup set")

    domain_results: dict[str, int] = {}
    total_upserted = 0
    total_found = 0
    total_embedded = 0
    budget_exhausted_domains: list[str] = []

    # Process domains in priority order (specific → broad)
    ordered = [d for d in DOMAIN_ORDER if d in DOMAINS]
    if domains:
        ordered = [d for d in ordered if d in domains]

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        for domain_key in ordered:
            cfg = DOMAINS[domain_key]
            domain_repos: list[dict] = []

            try:
                for topic in cfg["topics"]:
                    base_query = f"topic:{topic}"
                    if cfg["min_stars"] > 0:
                        base_query += f" stars:>={cfg['min_stars']}"

                    repos = await adaptive_search(
                        client, base_query, semaphore, seen,
                        pushed_after=pushed_after,
                        counter=counter,
                    )
                    # Tag each repo with this domain
                    for r in repos:
                        r["domain"] = domain_key
                    domain_repos.extend(repos)

                    logger.info(
                        f"[{domain_key}] topic:{topic}: {len(repos)} new "
                        f"(seen total: {len(seen)}, API calls: {counter.count})"
                    )
                    await asyncio.sleep(0.3)
            except BudgetExhausted:
                logger.warning(
                    f"Budget exhausted during domain '{domain_key}' "
                    f"({counter.count} API calls). Moving to next domain."
                )
                budget_exhausted_domains.append(domain_key)

            domain_results[domain_key] = len(domain_repos)
            total_found += len(domain_repos)

            # Flush this domain to DB immediately
            if domain_repos:
                upserted = _batch_upsert(domain_repos)
                total_upserted += upserted
                logger.info(f"Domain '{domain_key}' complete: {len(domain_repos)} found, {upserted} upserted")

                # Embed new descriptions for this domain
                if is_enabled():
                    embedded = await _embed_new_repos()
                    total_embedded += embedded
            else:
                logger.info(f"Domain '{domain_key}' complete: 0 new repos")

    if total_found == 0:
        logger.warning("No AI repos found")

    # Apply manual domain overrides for known misclassifications
    overrides_applied = _apply_domain_overrides()
    if overrides_applied:
        logger.info(f"Applied {overrides_applied} domain overrides")

    status = "partial" if budget_exhausted_domains else None
    _log_sync(started_at, total_upserted, status)

    logger.info(f"Total API calls: {counter.count}")
    if budget_exhausted_domains:
        logger.warning(f"Budget-exhausted domains: {budget_exhausted_domains}")

    return {
        "repos_found": total_found,
        "upserted": total_upserted,
        "embedded": total_embedded,
        "domains": domain_results,
        "api_calls": counter.count,
    }


async def _ensure_seeds() -> int:
    """Ensure FOUNDATIONAL_SEEDS repos exist in ai_repos with package names set.

    Fetches metadata from GitHub API for any seeds not already in the database,
    upserts them, then sets pypi_package/npm_package for all seeds.
    """
    if not FOUNDATIONAL_SEEDS:
        return 0

    headers = {"User-Agent": "pt-edge/1.0", "Accept": "application/vnd.github+json"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    # Check which seeds are missing from the DB
    with engine.connect() as conn:
        existing = conn.execute(text(
            "SELECT LOWER(full_name) FROM ai_repos"
        )).fetchall()
    existing_set = {r[0] for r in existing}

    missing = [
        s for s in FOUNDATIONAL_SEEDS
        if f"{s[0]}/{s[1]}".lower() not in existing_set
    ]

    # Fetch missing repos from GitHub API and upsert
    if missing:
        logger.info(f"Seeding {len(missing)} foundational repos from GitHub API...")
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            repos_to_upsert = []
            for owner, repo, domain, _, _ in missing:
                try:
                    resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
                    if resp.status_code != 200:
                        logger.warning(f"Seed {owner}/{repo}: GitHub API returned {resp.status_code}")
                        continue
                    data = resp.json()
                    repos_to_upsert.append({
                        "github_owner": data["owner"]["login"],
                        "github_repo": data["name"],
                        "full_name": data["full_name"],
                        "name": data["name"],
                        "description": data.get("description") or "",
                        "stars": data.get("stargazers_count", 0),
                        "forks": data.get("forks_count", 0),
                        "language": data.get("language"),
                        "topics": data.get("topics"),
                        "license": (data.get("license") or {}).get("spdx_id"),
                        "last_pushed_at": data.get("pushed_at"),
                        "created_at": data.get("created_at"),
                        "archived": data.get("archived", False),
                        "domain": domain,
                    })
                    await asyncio.sleep(0.3)
                except Exception as e:
                    logger.warning(f"Seed {owner}/{repo}: {e}")

            if repos_to_upsert:
                upserted = _batch_upsert(repos_to_upsert)
                logger.info(f"Upserted {upserted} seed repos")

    # Set package names for all seeds (including already-existing ones)
    updated = 0
    with engine.connect() as conn:
        for owner, repo, domain, pypi_pkg, npm_pkg in FOUNDATIONAL_SEEDS:
            sets = []
            params: dict = {"owner": owner, "repo": repo}
            if pypi_pkg:
                sets.append("pypi_package = :pypi")
                params["pypi"] = pypi_pkg
            if npm_pkg:
                sets.append("npm_package = :npm")
                params["npm"] = npm_pkg
            if not sets:
                continue
            result = conn.execute(text(f"""
                UPDATE ai_repos SET {', '.join(sets)}, updated_at = NOW()
                WHERE github_owner = :owner AND github_repo = :repo
            """), params)
            updated += result.rowcount
        conn.commit()

    logger.info(f"Seed package names set for {updated} repos")
    return updated


def _apply_domain_overrides() -> int:
    """Apply manual domain overrides from DOMAIN_OVERRIDES dict."""
    if not DOMAIN_OVERRIDES:
        return 0
    count = 0
    with engine.connect() as conn:
        for (owner, repo), domain in DOMAIN_OVERRIDES.items():
            result = conn.execute(
                text("""
                    UPDATE ai_repos SET domain = :domain, updated_at = NOW()
                    WHERE github_owner = :owner AND github_repo = :repo
                      AND domain != :domain
                """),
                {"owner": owner, "repo": repo, "domain": domain},
            )
            count += result.rowcount
        conn.commit()
    return count


def _batch_upsert(repos: list[dict]) -> int:
    """Batch upsert repos via psycopg2 execute_values."""
    from psycopg2.extras import execute_values

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        tuples = [
            (
                r["github_owner"], r["github_repo"], r["full_name"], r["name"],
                r["description"], r["stars"], r["forks"], r["language"],
                r["topics"] if r["topics"] else None, r["license"],
                r["last_pushed_at"], r.get("created_at"), r["archived"], r["domain"],
            )
            for r in repos
        ]
        execute_values(
            cur,
            """
            INSERT INTO ai_repos (
                github_owner, github_repo, full_name, name, description,
                stars, forks, language, topics, license,
                last_pushed_at, created_at, archived, domain, updated_at
            ) VALUES %s
            ON CONFLICT (github_owner, github_repo) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                stars = EXCLUDED.stars,
                forks = EXCLUDED.forks,
                language = EXCLUDED.language,
                topics = EXCLUDED.topics,
                license = EXCLUDED.license,
                last_pushed_at = EXCLUDED.last_pushed_at,
                created_at = COALESCE(EXCLUDED.created_at, ai_repos.created_at),
                archived = EXCLUDED.archived,
                domain = CASE
                    WHEN ai_repos.domain = 'uncategorized' THEN EXCLUDED.domain
                    ELSE ai_repos.domain
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
        raw_conn.rollback()
        logger.error(f"Batch upsert failed: {e}")
        return 0
    finally:
        raw_conn.close()


async def _embed_new_repos() -> int:
    """Embed ai_repos rows that don't have embeddings yet."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, name, description, topics, language, domain
            FROM ai_repos
            WHERE embedding IS NULL AND description IS NOT NULL
            ORDER BY stars DESC
        """)).fetchall()

    if not rows:
        return 0

    logger.info(f"Embedding {len(rows)} AI repos at {AI_REPO_EMBED_DIM}d...")

    texts = []
    ids = []
    for r in rows:
        m = r._mapping
        t = build_ai_repo_text(
            name=m["name"],
            description=m["description"],
            topics=list(m["topics"]) if m["topics"] else None,
            language=m["language"],
            domain=m["domain"],
        )
        texts.append(t)
        ids.append(m["id"])

    vectors = await embed_batch(texts, dimensions=AI_REPO_EMBED_DIM)

    tuples = [
        (sid, str(vec))
        for sid, vec in zip(ids, vectors)
        if vec is not None
    ]
    if not tuples:
        return 0

    # Chunk writes — avoid SSL drops on large payloads
    from psycopg2.extras import execute_values
    CHUNK = 500  # 256d vectors are ~2KB each, much smaller than 1536d
    count = 0

    for i in range(0, len(tuples), CHUNK):
        chunk = tuples[i:i + CHUNK]
        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            cur.execute("""
                CREATE TEMP TABLE _emb_batch (
                    id INTEGER PRIMARY KEY,
                    embedding vector(256)
                ) ON COMMIT DROP
            """)
            execute_values(
                cur,
                "INSERT INTO _emb_batch (id, embedding) VALUES %s",
                chunk,
                template="(%s, %s)",
                page_size=500,
            )
            cur.execute("""
                UPDATE ai_repos s
                SET embedding = b.embedding
                FROM _emb_batch b
                WHERE s.id = b.id
            """)
            count += cur.rowcount
            raw_conn.commit()
        except Exception as e:
            try:
                raw_conn.rollback()
            except Exception:
                pass
            logger.error(f"Embedding write failed at chunk {i}: {e}")
        finally:
            try:
                raw_conn.close()
            except Exception:
                pass

    logger.info(f"Embedded {count}/{len(rows)} AI repos")
    return count


def _log_sync(started_at: datetime, records: int, status: str | None) -> None:
    if status is None:
        status = "success"
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="ai_repos",
            status=status,
            records_written=records,
            error_message=None if status != "partial" else "Budget exhausted on some domains",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()


async def main():
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    args = sys.argv[1:]
    force_full = "--full" in args
    domains = [a for a in args if not a.startswith("--")] or None

    result = await ingest_ai_repos(domains=domains, force_full=force_full)
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
