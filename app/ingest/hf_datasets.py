"""Ingest HuggingFace Hub datasets into the hf_datasets table.

Fetches dataset metadata from the HF Hub API, filters to datasets with
meaningful download counts, and generates 256d embeddings for semantic
search via find_dataset().

Run standalone:  python -m app.ingest.hf_datasets
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.embeddings import build_hf_dataset_text, embed_batch, is_enabled
from app.ingest.hf_common import fetch_hf_pages, parse_hf_tags
from app.models import SyncLog

logger = logging.getLogger(__name__)

HF_DATASETS_URL = "https://huggingface.co/api/datasets"
EMBED_DIM = 256
MIN_DOWNLOADS = 100


def _parse_dataset(item: dict) -> dict:
    """Parse a single HF Hub API dataset item into a flat row."""
    hf_id = item.get("id", "")
    author = item.get("author") or (hf_id.split("/")[0] if "/" in hf_id else None)
    card_data = item.get("cardData") or {}

    # Description: prefer cardData description, fall back to card_data.pretty_name
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
        "task_categories": parsed["task_categories"] or None,
        "languages": parsed["languages"] or None,
        "downloads": item.get("downloads", 0) or 0,
        "likes": item.get("likes", 0) or 0,
        "created_at": item.get("createdAt"),
        "last_modified": item.get("lastModified"),
    }


def _batch_upsert(rows: list[dict]) -> int:
    """Batch upsert datasets via psycopg2 execute_values."""
    if not rows:
        return 0
    from psycopg2.extras import execute_values

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        tuples = [
            (
                r["hf_id"], r["pretty_name"], r["description"], r["author"],
                r["tags"], r["task_categories"], r["languages"],
                r["downloads"], r["likes"], r["created_at"], r["last_modified"],
            )
            for r in rows
        ]
        execute_values(
            cur,
            """
            INSERT INTO hf_datasets (
                hf_id, pretty_name, description, author,
                tags, task_categories, languages,
                downloads, likes, created_at, last_modified, updated_at
            ) VALUES %s
            ON CONFLICT (hf_id) DO UPDATE SET
                pretty_name = EXCLUDED.pretty_name,
                description = EXCLUDED.description,
                tags = EXCLUDED.tags,
                task_categories = EXCLUDED.task_categories,
                languages = EXCLUDED.languages,
                downloads = EXCLUDED.downloads,
                likes = EXCLUDED.likes,
                last_modified = EXCLUDED.last_modified,
                updated_at = NOW()
            """,
            tuples,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
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


async def _embed_new_datasets() -> int:
    """Generate 256d embeddings for datasets missing them."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, hf_id, description, task_categories, languages
            FROM hf_datasets
            WHERE embedding IS NULL
              AND (description IS NOT NULL OR hf_id IS NOT NULL)
            ORDER BY downloads DESC
        """)).fetchall()

    if not rows:
        return 0

    logger.info(f"Embedding {len(rows)} datasets at {EMBED_DIM}d")

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
            logger.error(f"Embedding write failed at chunk {i}: {e}")
        finally:
            try:
                raw_conn.close()
            except Exception:
                pass

    logger.info(f"Embedded {count}/{len(rows)} datasets")
    return count


async def ingest_hf_datasets(batch_limit: int = 50000) -> dict:
    """Fetch HuggingFace datasets, upsert, and embed."""
    started_at = datetime.now(timezone.utc)

    async with httpx.AsyncClient(
        headers={"User-Agent": "pt-edge/1.0"},
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        raw_items = await fetch_hf_pages(
            client,
            HF_DATASETS_URL,
            params={
                "sort": "downloads",
                "direction": "-1",
                "full": "true",
                "limit": "1000",
            },
            min_downloads=MIN_DOWNLOADS,
        )

    logger.info(f"Fetched {len(raw_items)} datasets from HF Hub")

    # Parse and filter
    rows = []
    for item in raw_items:
        parsed = _parse_dataset(item)
        if parsed["downloads"] >= MIN_DOWNLOADS:
            rows.append(parsed)

    if len(rows) > batch_limit:
        logger.warning(f"Truncating {len(rows)} datasets to batch_limit={batch_limit}")
        rows = rows[:batch_limit]

    logger.info(f"Parsed {len(rows)} datasets with >={MIN_DOWNLOADS} downloads")

    upserted = _batch_upsert(rows)
    logger.info(f"Upserted {upserted} datasets")

    embedded = 0
    if is_enabled():
        embedded = await _embed_new_datasets()

    _log_sync(started_at, upserted, None)
    return {"fetched": len(raw_items), "upserted": upserted, "embedded": embedded}


def _log_sync(started_at: datetime, records: int, error: str | None) -> None:
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="hf_datasets",
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
    result = await ingest_hf_datasets()
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
