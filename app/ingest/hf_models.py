"""Ingest HuggingFace Hub models into the hf_models table.

Fetches model metadata from the HF Hub API, filters to models with
meaningful download counts, and generates 256d embeddings for semantic
search via find_model().

Run standalone:  python -m app.ingest.hf_models
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.embeddings import build_hf_model_text, embed_batch, is_enabled
from app.ingest.hf_common import fetch_hf_pages, parse_hf_tags
from app.models import SyncLog

logger = logging.getLogger(__name__)

HF_MODELS_URL = "https://huggingface.co/api/models"
EMBED_DIM = 256
MIN_DOWNLOADS = 1000


def _parse_model(item: dict) -> dict:
    """Parse a single HF Hub API model item into a flat row."""
    hf_id = item.get("id", "")
    author = item.get("author") or (hf_id.split("/")[0] if "/" in hf_id else None)
    card_data = item.get("cardData") or {}

    # Description: prefer cardData description
    description = card_data.get("description") or item.get("description")

    # Parse tags into structured categories
    raw_tags = item.get("tags") or []
    parsed = parse_hf_tags(raw_tags)

    return {
        "hf_id": hf_id,
        "pretty_name": card_data.get("pretty_name"),
        "description": description,
        "author": author,
        "tags": raw_tags if raw_tags else None,
        "pipeline_tag": item.get("pipeline_tag"),
        "library_name": item.get("library_name"),
        "languages": parsed["languages"] or None,
        "downloads": item.get("downloads", 0) or 0,
        "likes": item.get("likes", 0) or 0,
        "created_at": item.get("createdAt"),
        "last_modified": item.get("lastModified"),
    }


def _batch_upsert(rows: list[dict]) -> int:
    """Batch upsert models via psycopg2 execute_values."""
    if not rows:
        return 0
    from psycopg2.extras import execute_values

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        tuples = [
            (
                r["hf_id"], r["pretty_name"], r["description"], r["author"],
                r["tags"], r["pipeline_tag"], r["library_name"], r["languages"],
                r["downloads"], r["likes"], r["created_at"], r["last_modified"],
            )
            for r in rows
        ]
        execute_values(
            cur,
            """
            INSERT INTO hf_models (
                hf_id, pretty_name, description, author,
                tags, pipeline_tag, library_name, languages,
                downloads, likes, created_at, last_modified, updated_at
            ) VALUES %s
            ON CONFLICT (hf_id) DO UPDATE SET
                pretty_name = EXCLUDED.pretty_name,
                description = EXCLUDED.description,
                tags = EXCLUDED.tags,
                pipeline_tag = EXCLUDED.pipeline_tag,
                library_name = EXCLUDED.library_name,
                languages = EXCLUDED.languages,
                downloads = EXCLUDED.downloads,
                likes = EXCLUDED.likes,
                last_modified = EXCLUDED.last_modified,
                updated_at = NOW()
            """,
            tuples,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
            page_size=500,
        )
        raw_conn.commit()
        return len(tuples)
    except Exception as e:
        try:
            raw_conn.rollback()
        except Exception:
            pass
        logger.error(f"Batch upsert failed: {e}")
        return 0
    finally:
        try:
            raw_conn.close()
        except Exception:
            pass


async def _embed_new_models() -> int:
    """Generate 256d embeddings for models missing them."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, hf_id, description, pipeline_tag, library_name, languages
            FROM hf_models
            WHERE embedding IS NULL
              AND (description IS NOT NULL OR hf_id IS NOT NULL)
            ORDER BY downloads DESC
        """)).fetchall()

    if not rows:
        return 0

    logger.info(f"Embedding {len(rows)} models at {EMBED_DIM}d")

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

    vectors = await embed_batch(texts, dimensions=EMBED_DIM)

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
            logger.error(f"Embedding write failed at chunk {i}: {e}")
        finally:
            try:
                raw_conn.close()
            except Exception:
                pass

    logger.info(f"Embedded {count}/{len(rows)} models")
    return count


async def ingest_hf_models(batch_limit: int = 50000) -> dict:
    """Fetch HuggingFace models, upsert, and embed."""
    started_at = datetime.now(timezone.utc)

    async with httpx.AsyncClient(
        headers={"User-Agent": "pt-edge/1.0"},
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        raw_items = await fetch_hf_pages(
            client,
            HF_MODELS_URL,
            params={
                "sort": "downloads",
                "direction": "-1",
                "full": "true",
                "limit": "1000",
            },
            min_downloads=MIN_DOWNLOADS,
        )

    logger.info(f"Fetched {len(raw_items)} models from HF Hub")

    # Parse and filter
    rows = []
    for item in raw_items:
        parsed = _parse_model(item)
        if parsed["downloads"] >= MIN_DOWNLOADS:
            rows.append(parsed)

    if len(rows) > batch_limit:
        rows = rows[:batch_limit]

    logger.info(f"Parsed {len(rows)} models with >={MIN_DOWNLOADS} downloads")

    upserted = _batch_upsert(rows)
    logger.info(f"Upserted {upserted} models")

    embedded = 0
    if is_enabled():
        embedded = await _embed_new_models()

    _log_sync(started_at, upserted, None)
    return {"fetched": len(raw_items), "upserted": upserted, "embedded": embedded}


def _log_sync(started_at: datetime, records: int, error: str | None) -> None:
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="hf_models",
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
    result = await ingest_hf_models()
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
