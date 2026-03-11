"""Ingest AI/ML repos from GitHub Search API.

Discovers repos across multiple domains (MCP, agents, RAG, LLM tools, etc.)
using adaptive sub-sharding to get past the 1,000-result-per-query limit.
Embeds descriptions at 256d for semantic search via find_ai_tool().

Run standalone:  python -m app.ingest.ai_repos [domain ...]
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.embeddings import build_ai_repo_text, embed_batch, is_enabled
from app.ingest.ai_repo_domains import DOMAINS, DOMAIN_ORDER
from app.ingest.github_search import adaptive_search
from app.models import SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

AI_REPO_EMBED_DIM = 256


async def ingest_ai_repos(domains: list[str] | None = None) -> dict:
    """Discover and upsert AI repos from GitHub Search API.

    Args:
        domains: specific domain keys to ingest, or None for all.
    """
    started_at = datetime.now(timezone.utc)

    headers = {"User-Agent": "pt-edge/1.0", "Accept": "application/vnd.github+json"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    semaphore = asyncio.Semaphore(2)  # conservative for Search API
    seen: set[str] = set()  # global dedup by lowercase full_name
    domain_results: dict[str, int] = {}
    all_repos: list[dict] = []

    # Process domains in priority order (specific → broad)
    ordered = [d for d in DOMAIN_ORDER if d in DOMAINS]
    if domains:
        ordered = [d for d in ordered if d in domains]

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        for domain_key in ordered:
            cfg = DOMAINS[domain_key]
            domain_repos: list[dict] = []

            for topic in cfg["topics"]:
                base_query = f"topic:{topic}"
                if cfg["min_stars"] > 0:
                    base_query += f" stars:>={cfg['min_stars']}"

                repos = await adaptive_search(
                    client, base_query, semaphore, seen,
                )
                # Tag each repo with this domain
                for r in repos:
                    r["domain"] = domain_key
                domain_repos.extend(repos)

                logger.info(
                    f"[{domain_key}] topic:{topic}: {len(repos)} new "
                    f"(seen total: {len(seen)})"
                )
                await asyncio.sleep(1.0)

            domain_results[domain_key] = len(domain_repos)
            all_repos.extend(domain_repos)
            logger.info(f"Domain '{domain_key}' complete: {len(domain_repos)} repos")

    if not all_repos:
        logger.warning("No AI repos found")
        _log_sync(started_at, 0, None)
        return {"repos_found": 0, "upserted": 0, "embedded": 0, "domains": domain_results}

    logger.info(f"Discovered {len(all_repos)} unique repos across {len(domain_results)} domains")

    # Batch upsert
    upserted = _batch_upsert(all_repos)
    logger.info(f"Upserted {upserted}/{len(all_repos)} repos")

    # Embed new descriptions
    embedded = 0
    if is_enabled():
        embedded = await _embed_new_repos()

    _log_sync(started_at, upserted, None)
    return {
        "repos_found": len(all_repos),
        "upserted": upserted,
        "embedded": embedded,
        "domains": domain_results,
    }


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
                r["last_pushed_at"], r["archived"], r["domain"],
            )
            for r in repos
        ]
        execute_values(
            cur,
            """
            INSERT INTO ai_repos (
                github_owner, github_repo, full_name, name, description,
                stars, forks, language, topics, license,
                last_pushed_at, archived, domain, updated_at
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
                archived = EXCLUDED.archived,
                domain = CASE
                    WHEN ai_repos.domain = 'uncategorized' THEN EXCLUDED.domain
                    ELSE ai_repos.domain
                END,
                updated_at = NOW()
            """,
            tuples,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
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


def _log_sync(started_at: datetime, records: int, error: str | None) -> None:
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="ai_repos",
            status="success" if not error else "failed",
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
    domains = sys.argv[1:] or None
    result = await ingest_ai_repos(domains=domains)
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
