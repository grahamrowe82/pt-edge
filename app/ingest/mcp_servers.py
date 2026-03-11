"""Ingest MCP server repos from GitHub Search API.

Discovers repos tagged with mcp-server or model-context-protocol topics,
sharded by star count to work around GitHub's 1,000-result-per-query limit.
Embeds descriptions for semantic search via find_mcp_server() tool.

Run standalone: python -m app.ingest.mcp_servers
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.embeddings import build_mcp_server_text, embed_batch, is_enabled
from app.models import SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

# GitHub Search API: 1,000 results max per query.
# Shard by star ranges to get full coverage.
STAR_SHARDS = [
    "stars:>=1000",
    "stars:100..999",
    "stars:10..99",
    "stars:1..9",
    "stars:0",
]

TOPIC_QUERIES = [
    "topic:mcp-server",
    "topic:model-context-protocol",
]

SEARCH_URL = "https://api.github.com/search/repositories"
PER_PAGE = 100
MAX_PAGES = 10  # 100 * 10 = 1,000 per query


async def _search_shard(
    client: httpx.AsyncClient,
    topic_query: str,
    star_filter: str,
    semaphore: asyncio.Semaphore,
    seen: set[str],
) -> list[dict]:
    """Paginate one shard of GitHub Search. Returns list of repo dicts."""
    q = f"{topic_query} {star_filter}"
    repos = []

    for page in range(1, MAX_PAGES + 1):
        async with semaphore:
            try:
                resp = await client.get(
                    SEARCH_URL,
                    params={
                        "q": q,
                        "sort": "stars",
                        "order": "desc",
                        "per_page": PER_PAGE,
                        "page": page,
                    },
                )
            except httpx.HTTPError as e:
                logger.warning(f"HTTP error for shard {q} page {page}: {e}")
                break

        if resp.status_code == 403:
            # Rate limited — stop this shard
            logger.warning(f"Rate limited on shard {q} page {page}")
            await asyncio.sleep(60)
            break
        if resp.status_code == 422:
            # Validation error (e.g. too many results) — skip shard
            logger.warning(f"422 on shard {q}: {resp.text[:200]}")
            break
        if resp.status_code != 200:
            logger.warning(f"GitHub Search {resp.status_code} for {q} page {page}")
            break

        data = resp.json()
        items = data.get("items", [])
        if not items:
            break

        for item in items:
            full_name = item.get("full_name", "").lower()
            if full_name in seen:
                continue
            seen.add(full_name)

            owner, repo = item.get("full_name", "/").split("/", 1)
            license_info = item.get("license") or {}

            repos.append({
                "github_owner": owner,
                "github_repo": repo,
                "full_name": item.get("full_name", ""),
                "name": item.get("name", repo),
                "description": (item.get("description") or "")[:2000] or None,
                "stars": item.get("stargazers_count", 0),
                "forks": item.get("forks_count", 0),
                "language": item.get("language"),
                "topics": item.get("topics") or [],
                "license": license_info.get("spdx_id"),
                "last_pushed_at": item.get("pushed_at"),
                "archived": item.get("archived", False),
            })

        # If fewer than PER_PAGE results, we've exhausted this shard
        if len(items) < PER_PAGE:
            break

        # Respect rate limits — small pause between pages
        await asyncio.sleep(0.5)

    return repos


async def ingest_mcp_servers() -> dict:
    """Discover and upsert MCP server repos from GitHub Search API."""
    started_at = datetime.now(timezone.utc)

    headers = {"User-Agent": "pt-edge/1.0", "Accept": "application/vnd.github+json"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    semaphore = asyncio.Semaphore(3)  # conservative for Search API
    seen: set[str] = set()
    all_repos: list[dict] = []

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        for star_filter in STAR_SHARDS:
            for topic_query in TOPIC_QUERIES:
                repos = await _search_shard(
                    client, topic_query, star_filter, semaphore, seen,
                )
                all_repos.extend(repos)
                logger.info(
                    f"Shard {topic_query} {star_filter}: {len(repos)} new repos "
                    f"(total: {len(all_repos)})"
                )
                # Pause between shards to stay well within rate limits
                await asyncio.sleep(1.0)

    if not all_repos:
        logger.warning("No MCP server repos found")
        _log_sync(started_at, 0, None)
        return {"repos_found": 0, "upserted": 0, "embedded": 0}

    logger.info(f"Discovered {len(all_repos)} unique MCP server repos, upserting...")

    # Batch upsert — use psycopg2 execute_values for true multi-row insert
    upserted = 0
    from psycopg2.extras import execute_values

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        tuples = [
            (
                r["github_owner"], r["github_repo"], r["full_name"], r["name"],
                r["description"], r["stars"], r["forks"], r["language"],
                r["topics"] if r["topics"] else None, r["license"],
                r["last_pushed_at"], r["archived"],
            )
            for r in all_repos
        ]
        execute_values(
            cur,
            """
            INSERT INTO mcp_servers (
                github_owner, github_repo, full_name, name, description,
                stars, forks, language, topics, license,
                last_pushed_at, archived, updated_at
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
                updated_at = NOW()
            """,
            tuples,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
            page_size=500,
        )
        raw_conn.commit()
        upserted = len(tuples)
    except Exception as e:
        raw_conn.rollback()
        logger.error(f"Batch upsert failed: {e}")
    finally:
        raw_conn.close()

    logger.info(f"Upserted {upserted}/{len(all_repos)} MCP server repos")

    # Embed new/changed descriptions
    embedded = 0
    if is_enabled():
        embedded = await _embed_new_servers()

    _log_sync(started_at, upserted, None)

    return {"repos_found": len(all_repos), "upserted": upserted, "embedded": embedded}


async def _embed_new_servers() -> int:
    """Embed MCP servers that don't have embeddings yet."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, name, description, topics, language
            FROM mcp_servers
            WHERE embedding IS NULL AND description IS NOT NULL
            ORDER BY stars DESC
        """)).fetchall()

    if not rows:
        return 0

    logger.info(f"Embedding {len(rows)} MCP servers...")

    texts = []
    ids = []
    for r in rows:
        m = r._mapping
        text_input = build_mcp_server_text(
            name=m["name"],
            description=m["description"],
            topics=list(m["topics"]) if m["topics"] else None,
            language=m["language"],
        )
        texts.append(text_input)
        ids.append(m["id"])

    vectors = await embed_batch(texts)

    tuples = [
        (sid, str(vec))
        for sid, vec in zip(ids, vectors)
        if vec is not None
    ]
    if not tuples:
        return 0

    # Chunk writes — each vector is ~12KB so keep batches small to avoid SSL drops
    from psycopg2.extras import execute_values
    CHUNK = 200
    count = 0

    for i in range(0, len(tuples), CHUNK):
        chunk = tuples[i:i + CHUNK]
        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            cur.execute("""
                CREATE TEMP TABLE _emb_batch (
                    id INTEGER PRIMARY KEY,
                    embedding vector(1536)
                ) ON COMMIT DROP
            """)
            execute_values(
                cur,
                "INSERT INTO _emb_batch (id, embedding) VALUES %s",
                chunk,
                template="(%s, %s)",
                page_size=200,
            )
            cur.execute("""
                UPDATE mcp_servers s
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
            logger.error(f"Batch embedding write failed at chunk {i}: {e}")
        finally:
            try:
                raw_conn.close()
            except Exception:
                pass

    logger.info(f"Embedded {count}/{len(rows)} MCP servers")
    return count


def _log_sync(started_at: datetime, records: int, error: str | None) -> None:
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="mcp_servers",
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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = await ingest_mcp_servers()
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
