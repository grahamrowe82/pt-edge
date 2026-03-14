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
    build_briefing_text,
    build_newsletter_text,
    build_release_text,
    build_ai_repo_text,
    build_public_api_text,
    build_hf_dataset_text,
    build_hf_model_text,
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
                conn.commit()
                count += 1

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
                conn.commit()
                count += 1

    logger.info(f"Embedded {count}/{len(rows)} methodology entries.")
    return count


async def backfill_briefings(force: bool = False) -> int:
    """Generate embeddings for all briefing entries missing them."""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, slug, title, summary, domain
            FROM briefings
            {"WHERE embedding IS NULL" if not force else ""}
            ORDER BY id
        """)).fetchall()

    if not rows:
        logger.info("No briefings need embeddings.")
        return 0

    logger.info(f"Generating embeddings for {len(rows)} briefings...")

    texts = []
    ids = []
    for r in rows:
        m = r._mapping
        text_input = build_briefing_text(
            slug=m["slug"],
            title=m["title"],
            summary=m["summary"],
            domain=m["domain"],
        )
        texts.append(text_input)
        ids.append(m["id"])

    vectors = await embed_batch(texts)

    count = 0
    with engine.connect() as conn:
        for bid, vec in zip(ids, vectors):
            if vec is not None:
                conn.execute(text("""
                    UPDATE briefings SET embedding = :vec WHERE id = :bid
                """), {"vec": str(vec), "bid": bid})
                conn.commit()
                count += 1

    logger.info(f"Embedded {count}/{len(rows)} briefings.")
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
                conn.commit()
                count += 1

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
                conn.commit()
                count += 1

    logger.info(f"Embedded {count}/{len(rows)} newsletter topics.")
    return count


AI_REPO_EMBED_DIM = 256


async def backfill_ai_repos(force: bool = False) -> int:
    """Generate 256d embeddings for AI repos missing them."""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, name, description, topics, language, domain
            FROM ai_repos
            WHERE description IS NOT NULL
            {"AND embedding IS NULL" if not force else ""}
            ORDER BY stars DESC
        """)).fetchall()

    if not rows:
        logger.info("No AI repos need embeddings.")
        return 0

    logger.info(f"Generating {AI_REPO_EMBED_DIM}d embeddings for {len(rows)} AI repos...")

    texts = []
    ids = []
    for r in rows:
        m = r._mapping
        text_input = build_ai_repo_text(
            name=m["name"],
            description=m["description"],
            topics=list(m["topics"]) if m["topics"] else None,
            language=m["language"],
            domain=m["domain"],
        )
        texts.append(text_input)
        ids.append(m["id"])

    vectors = await embed_batch(texts, dimensions=AI_REPO_EMBED_DIM)

    tuples = [
        (sid, str(vec))
        for sid, vec in zip(ids, vectors)
        if vec is not None
    ]
    if not tuples:
        return 0

    from psycopg2.extras import execute_values
    CHUNK = 500  # 256d vectors are ~2KB each — safe batch size
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
            logger.error(f"Batch embedding write failed at chunk {i}: {e}")
        finally:
            try:
                raw_conn.close()
            except Exception:
                pass

    logger.info(f"Embedded {count}/{len(rows)} AI repos.")
    return count


API_EMBED_DIM = 256


async def backfill_public_apis(force: bool = False) -> int:
    """Generate 256d embeddings for public APIs missing them."""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, title, description, categories, provider
            FROM public_apis
            WHERE description IS NOT NULL
            {"AND embedding IS NULL" if not force else ""}
        """)).fetchall()

    if not rows:
        logger.info("No public APIs need embeddings.")
        return 0

    logger.info(f"Generating {API_EMBED_DIM}d embeddings for {len(rows)} public APIs...")

    texts = []
    ids = []
    for r in rows:
        m = r._mapping
        t = build_public_api_text(
            title=m["title"],
            description=m["description"],
            categories=list(m["categories"]) if m["categories"] else None,
            provider=m["provider"],
        )
        texts.append(t)
        ids.append(m["id"])

    vectors = await embed_batch(texts, dimensions=API_EMBED_DIM)

    tuples = [
        (sid, str(vec))
        for sid, vec in zip(ids, vectors)
        if vec is not None
    ]
    if not tuples:
        return 0

    from psycopg2.extras import execute_values
    CHUNK = 500
    count = 0

    for i in range(0, len(tuples), CHUNK):
        chunk = tuples[i : i + CHUNK]
        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            cur.execute("""
                CREATE TEMP TABLE _api_emb (
                    id INTEGER PRIMARY KEY,
                    embedding vector(256)
                ) ON COMMIT DROP
            """)
            execute_values(
                cur,
                "INSERT INTO _api_emb (id, embedding) VALUES %s",
                chunk,
                template="(%s, %s)",
                page_size=500,
            )
            cur.execute("""
                UPDATE public_apis p
                SET embedding = b.embedding
                FROM _api_emb b
                WHERE p.id = b.id
            """)
            count += cur.rowcount
            raw_conn.commit()
        except Exception as e:
            try:
                raw_conn.rollback()
            except Exception:
                pass
            logger.error(f"API embedding write failed at chunk {i}: {e}")
        finally:
            try:
                raw_conn.close()
            except Exception:
                pass

    logger.info(f"Embedded {count}/{len(rows)} public APIs.")
    return count


HF_EMBED_DIM = 256


async def backfill_hf_datasets(force: bool = False) -> int:
    """Generate 256d embeddings for HF datasets missing them."""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, hf_id, description, task_categories, languages
            FROM hf_datasets
            WHERE (description IS NOT NULL OR hf_id IS NOT NULL)
            {"AND embedding IS NULL" if not force else ""}
            ORDER BY downloads DESC
        """)).fetchall()

    if not rows:
        logger.info("No HF datasets need embeddings.")
        return 0

    logger.info(f"Generating {HF_EMBED_DIM}d embeddings for {len(rows)} HF datasets...")

    texts = []
    ids = []
    for r in rows:
        m = r._mapping
        t = build_hf_dataset_text(
            name=m["hf_id"],
            description=m["description"],
            task_categories=list(m["task_categories"]) if m["task_categories"] else None,
            languages=list(m["languages"]) if m["languages"] else None,
        )
        texts.append(t)
        ids.append(m["id"])

    vectors = await embed_batch(texts, dimensions=HF_EMBED_DIM)

    tuples = [
        (sid, str(vec))
        for sid, vec in zip(ids, vectors)
        if vec is not None
    ]
    if not tuples:
        return 0

    from psycopg2.extras import execute_values
    CHUNK = 500
    count = 0

    for i in range(0, len(tuples), CHUNK):
        chunk = tuples[i:i + CHUNK]
        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            cur.execute("""
                CREATE TEMP TABLE _ds_emb (
                    id INTEGER PRIMARY KEY,
                    embedding vector(256)
                ) ON COMMIT DROP
            """)
            execute_values(
                cur,
                "INSERT INTO _ds_emb (id, embedding) VALUES %s",
                chunk,
                template="(%s, %s)",
                page_size=500,
            )
            cur.execute("""
                UPDATE hf_datasets d
                SET embedding = b.embedding
                FROM _ds_emb b
                WHERE d.id = b.id
            """)
            count += cur.rowcount
            raw_conn.commit()
        except Exception as e:
            try:
                raw_conn.rollback()
            except Exception:
                pass
            logger.error(f"HF dataset embedding write failed at chunk {i}: {e}")
        finally:
            try:
                raw_conn.close()
            except Exception:
                pass

    logger.info(f"Embedded {count}/{len(rows)} HF datasets.")
    return count


async def backfill_hf_models(force: bool = False) -> int:
    """Generate 256d embeddings for HF models missing them."""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, hf_id, description, pipeline_tag, library_name, languages
            FROM hf_models
            WHERE (description IS NOT NULL OR hf_id IS NOT NULL)
            {"AND embedding IS NULL" if not force else ""}
            ORDER BY downloads DESC
        """)).fetchall()

    if not rows:
        logger.info("No HF models need embeddings.")
        return 0

    logger.info(f"Generating {HF_EMBED_DIM}d embeddings for {len(rows)} HF models...")

    texts = []
    ids = []
    for r in rows:
        m = r._mapping
        t = build_hf_model_text(
            name=m["hf_id"],
            description=m["description"],
            pipeline_tag=m["pipeline_tag"],
            library_name=m["library_name"],
            languages=list(m["languages"]) if m["languages"] else None,
        )
        texts.append(t)
        ids.append(m["id"])

    vectors = await embed_batch(texts, dimensions=HF_EMBED_DIM)

    tuples = [
        (sid, str(vec))
        for sid, vec in zip(ids, vectors)
        if vec is not None
    ]
    if not tuples:
        return 0

    from psycopg2.extras import execute_values
    CHUNK = 500
    count = 0

    for i in range(0, len(tuples), CHUNK):
        chunk = tuples[i:i + CHUNK]
        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            cur.execute("""
                CREATE TEMP TABLE _model_emb (
                    id INTEGER PRIMARY KEY,
                    embedding vector(256)
                ) ON COMMIT DROP
            """)
            execute_values(
                cur,
                "INSERT INTO _model_emb (id, embedding) VALUES %s",
                chunk,
                template="(%s, %s)",
                page_size=500,
            )
            cur.execute("""
                UPDATE hf_models m
                SET embedding = b.embedding
                FROM _model_emb b
                WHERE m.id = b.id
            """)
            count += cur.rowcount
            raw_conn.commit()
        except Exception as e:
            try:
                raw_conn.rollback()
            except Exception:
                pass
            logger.error(f"HF model embedding write failed at chunk {i}: {e}")
        finally:
            try:
                raw_conn.close()
            except Exception:
                pass

    logger.info(f"Embedded {count}/{len(rows)} HF models.")
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
    briefings = await backfill_briefings(force=force)
    releases = await backfill_releases(force=force)
    newsletters = await backfill_newsletters(force=force)
    ai_repos = await backfill_ai_repos(force=force)
    public_apis = await backfill_public_apis(force=force)
    hf_datasets = await backfill_hf_datasets(force=force)
    hf_models = await backfill_hf_models(force=force)

    logger.info(
        f"Backfill complete: {projects} projects, {methodology} methodology, "
        f"{briefings} briefings, {releases} releases, {newsletters} newsletter topics, "
        f"{ai_repos} AI repos, {public_apis} public APIs, "
        f"{hf_datasets} HF datasets, {hf_models} HF models."
    )


if __name__ == "__main__":
    asyncio.run(main())
