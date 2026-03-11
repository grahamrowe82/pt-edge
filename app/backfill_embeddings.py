"""Backfill embeddings for all projects and methodology entries.

Run with: python -m app.backfill_embeddings

One-time cost: ~$0.01 for 200 projects + 24 methodology entries.
Skips rows that already have embeddings unless --force is passed.
"""
import asyncio
import logging
import sys

from sqlalchemy import text

from app.db import engine
from app.embeddings import (
    is_enabled,
    build_project_text,
    build_methodology_text,
    build_newsletter_text,
    build_release_text,
    build_mcp_server_text,
    embed_batch,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def backfill_projects(force: bool = False) -> int:
    """Generate embeddings for all projects missing them."""
    where = "" if force else "WHERE embedding IS NULL"

    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, name, description, topics, category
            FROM projects
            WHERE is_active = true
            {"AND embedding IS NULL" if not force else ""}
            ORDER BY id
        """)).fetchall()

    if not rows:
        logger.info("No projects need embeddings.")
        return 0

    logger.info(f"Generating embeddings for {len(rows)} projects...")

    texts = []
    ids = []
    for r in rows:
        m = r._mapping
        # Fetch language from latest GitHub snapshot if available
        text_input = build_project_text(
            name=m["name"],
            description=m["description"],
            topics=list(m["topics"]) if m["topics"] else None,
            category=m["category"],
            language=None,  # Could fetch from GH but not worth the complexity
        )
        texts.append(text_input)
        ids.append(m["id"])

    vectors = await embed_batch(texts)

    count = 0
    with engine.connect() as conn:
        for pid, vec in zip(ids, vectors):
            if vec is not None:
                conn.execute(text("""
                    UPDATE projects SET embedding = :vec WHERE id = :pid
                """), {"vec": str(vec), "pid": pid})
                count += 1
        conn.commit()

    logger.info(f"Embedded {count}/{len(rows)} projects.")
    return count


async def backfill_methodology(force: bool = False) -> int:
    """Generate embeddings for all methodology entries missing them."""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, topic, title, summary, category
            FROM methodology
            {"WHERE embedding IS NULL" if not force else ""}
            ORDER BY id
        """)).fetchall()

    if not rows:
        logger.info("No methodology entries need embeddings.")
        return 0

    logger.info(f"Generating embeddings for {len(rows)} methodology entries...")

    texts = []
    ids = []
    for r in rows:
        m = r._mapping
        text_input = build_methodology_text(
            topic=m["topic"],
            title=m["title"],
            summary=m["summary"],
            category=m["category"],
        )
        texts.append(text_input)
        ids.append(m["id"])

    vectors = await embed_batch(texts)

    count = 0
    with engine.connect() as conn:
        for mid, vec in zip(ids, vectors):
            if vec is not None:
                conn.execute(text("""
                    UPDATE methodology SET embedding = :vec WHERE id = :mid
                """), {"vec": str(vec), "mid": mid})
                count += 1
        conn.commit()

    logger.info(f"Embedded {count}/{len(rows)} methodology entries.")
    return count


async def backfill_releases(force: bool = False) -> int:
    """Generate embeddings for releases that have summaries."""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT r.id, p.name as project_name, r.version, r.title, r.summary
            FROM releases r
            JOIN projects p ON p.id = r.project_id
            WHERE r.summary IS NOT NULL
            {"AND r.embedding IS NULL" if not force else ""}
            ORDER BY r.id
        """)).fetchall()

    if not rows:
        logger.info("No releases need embeddings.")
        return 0

    logger.info(f"Generating embeddings for {len(rows)} releases...")

    texts = []
    ids = []
    for r in rows:
        m = r._mapping
        text_input = build_release_text(
            project_name=m["project_name"],
            version=m["version"],
            title=m["title"],
            summary=m["summary"],
        )
        texts.append(text_input)
        ids.append(m["id"])

    vectors = await embed_batch(texts)

    count = 0
    with engine.connect() as conn:
        for rid, vec in zip(ids, vectors):
            if vec is not None:
                conn.execute(text("""
                    UPDATE releases SET embedding = :vec WHERE id = :rid
                """), {"vec": str(vec), "rid": rid})
                count += 1
        conn.commit()

    logger.info(f"Embedded {count}/{len(rows)} releases.")
    return count


async def backfill_newsletters(force: bool = False) -> int:
    """Generate embeddings for newsletter topics that have summaries."""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, title, summary, mentions
            FROM newsletter_mentions
            WHERE summary IS NOT NULL
            {"AND embedding IS NULL" if not force else ""}
            ORDER BY id
        """)).fetchall()

    if not rows:
        logger.info("No newsletter topics need embeddings.")
        return 0

    logger.info(f"Generating embeddings for {len(rows)} newsletter topics...")

    texts = []
    ids = []
    for r in rows:
        m = r._mapping
        mentions = m["mentions"] if isinstance(m["mentions"], list) else []
        text_input = build_newsletter_text(
            title=m["title"],
            summary=m["summary"],
            mentions=mentions,
        )
        texts.append(text_input)
        ids.append(m["id"])

    vectors = await embed_batch(texts)

    count = 0
    with engine.connect() as conn:
        for nid, vec in zip(ids, vectors):
            if vec is not None:
                conn.execute(text("""
                    UPDATE newsletter_mentions SET embedding = :vec WHERE id = :nid
                """), {"vec": str(vec), "nid": nid})
                count += 1
        conn.commit()

    logger.info(f"Embedded {count}/{len(rows)} newsletter topics.")
    return count


async def backfill_mcp_servers(force: bool = False) -> int:
    """Generate embeddings for MCP servers missing them."""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, name, description, topics, language
            FROM mcp_servers
            WHERE description IS NOT NULL
            {"AND embedding IS NULL" if not force else ""}
            ORDER BY stars DESC
        """)).fetchall()

    if not rows:
        logger.info("No MCP servers need embeddings.")
        return 0

    logger.info(f"Generating embeddings for {len(rows)} MCP servers...")

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

    logger.info(f"Embedded {count}/{len(rows)} MCP servers.")
    return count


async def main():
    if not is_enabled():
        logger.error(
            "OPENAI_API_KEY not set. Set it in .env or environment to generate embeddings."
        )
        sys.exit(1)

    force = "--force" in sys.argv

    projects = await backfill_projects(force=force)
    methodology = await backfill_methodology(force=force)
    releases = await backfill_releases(force=force)
    newsletters = await backfill_newsletters(force=force)
    mcp_servers = await backfill_mcp_servers(force=force)

    logger.info(
        f"Backfill complete: {projects} projects, {methodology} methodology, "
        f"{releases} releases, {newsletters} newsletter topics, "
        f"{mcp_servers} MCP servers."
    )


if __name__ == "__main__":
    asyncio.run(main())
