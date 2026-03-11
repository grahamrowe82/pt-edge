"""Ingest public APIs from the APIs.guru directory.

Fetches the full catalog (~2,500 APIs) in one GET, upserts into
public_apis table, and generates 256d embeddings for semantic search.

Run standalone:  python -m app.ingest.public_apis
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.embeddings import build_public_api_text, embed_batch, is_enabled
from app.models import SyncLog

logger = logging.getLogger(__name__)

CATALOG_URL = "https://api.apis.guru/v2/list.json"
EMBED_DIM = 256


def _parse_catalog(data: dict) -> list[dict]:
    """Parse APIs.guru catalog JSON into flat rows."""
    rows = []
    for key, entry in data.items():
        preferred = entry.get("preferred")
        versions = entry.get("versions", {})
        if not preferred or preferred not in versions:
            # Fall back to first available version
            if not versions:
                continue
            preferred = next(iter(versions))

        ver = versions[preferred]
        info = ver.get("info", {})

        # Provider and service from the key (e.g. "googleapis.com:youtube")
        parts = key.split(":", 1)
        provider = parts[0]
        service_name = parts[1] if len(parts) > 1 else ""

        # Extract contact URL
        contact = info.get("contact") or {}
        contact_url = contact.get("url")

        # Extract logo URL
        logo = info.get("x-logo") or {}
        logo_url = logo.get("url")

        # Categories
        categories = info.get("x-apisguru-categories") or []

        # Description — strip HTML
        description = info.get("description") or ""
        if description:
            description = re.sub(r"<[^>]+>", "", description).strip()

        rows.append({
            "provider": provider,
            "service_name": service_name,
            "title": info.get("title") or key,
            "description": description or None,
            "categories": categories if categories else None,
            "openapi_version": ver.get("openapiVer"),
            "spec_url": ver.get("swaggerUrl"),
            "logo_url": logo_url,
            "contact_url": contact_url,
            "api_version": preferred,
            "added_at": ver.get("added"),
            "updated_at": ver.get("updated"),
        })

    return rows


def _batch_upsert(rows: list[dict]) -> int:
    """Batch upsert APIs via psycopg2 execute_values."""
    if not rows:
        return 0
    from psycopg2.extras import execute_values

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        tuples = [
            (
                r["provider"], r["service_name"], r["title"], r["description"],
                r["categories"], r["openapi_version"], r["spec_url"],
                r["logo_url"], r["contact_url"], r["api_version"],
                r["added_at"], r["updated_at"],
            )
            for r in rows
        ]
        execute_values(
            cur,
            """
            INSERT INTO public_apis (
                provider, service_name, title, description, categories,
                openapi_version, spec_url, logo_url, contact_url,
                api_version, added_at, updated_at
            ) VALUES %s
            ON CONFLICT (provider, service_name) DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                categories = EXCLUDED.categories,
                openapi_version = EXCLUDED.openapi_version,
                spec_url = EXCLUDED.spec_url,
                logo_url = EXCLUDED.logo_url,
                contact_url = EXCLUDED.contact_url,
                api_version = EXCLUDED.api_version,
                updated_at = EXCLUDED.updated_at
            """,
            tuples,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
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


async def _embed_new_apis() -> int:
    """Generate 256d embeddings for APIs missing them."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, title, description, categories, provider
            FROM public_apis
            WHERE description IS NOT NULL AND embedding IS NULL
        """)).fetchall()

    if not rows:
        return 0

    logger.info(f"Embedding {len(rows)} APIs at {EMBED_DIM}d")

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
            logger.error(f"Embedding write failed at chunk {i}: {e}")
        finally:
            try:
                raw_conn.close()
            except Exception:
                pass

    logger.info(f"Embedded {count}/{len(rows)} APIs")
    return count


async def ingest_public_apis() -> dict:
    """Fetch APIs.guru catalog, upsert, and embed."""
    started_at = datetime.now(timezone.utc)

    async with httpx.AsyncClient(
        headers={"User-Agent": "pt-edge/1.0"}, timeout=60.0
    ) as client:
        resp = await client.get(CATALOG_URL)
        resp.raise_for_status()
        catalog = resp.json()

    logger.info(f"Fetched APIs.guru catalog: {len(catalog)} entries")

    rows = _parse_catalog(catalog)
    logger.info(f"Parsed {len(rows)} APIs")

    upserted = _batch_upsert(rows)
    logger.info(f"Upserted {upserted} APIs")

    embedded = 0
    if is_enabled():
        embedded = await _embed_new_apis()

    _log_sync(started_at, upserted, None)
    return {"fetched": len(catalog), "upserted": upserted, "embedded": embedded}


def _log_sync(started_at: datetime, records: int, error: str | None) -> None:
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="public_apis",
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
    result = await ingest_public_apis()
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
