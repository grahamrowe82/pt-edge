"""Fetch and cache OpenAPI/Swagger specs for public APIs.

Pre-fetches raw specs for APIs that have spec_url but no cached spec_json.
Rate-limited, incremental. Runs as part of the main ingest cycle.

Run standalone:  python -m app.ingest.api_specs
"""
import asyncio
import json as json_mod
import logging
from datetime import datetime, timezone

import httpx
import yaml
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import SyncLog

logger = logging.getLogger(__name__)

MAX_SPEC_BYTES = 10 * 1024 * 1024  # 10 MB


def _is_valid_spec(data: dict) -> bool:
    """Check if parsed JSON/YAML looks like an OpenAPI/Swagger spec."""
    return isinstance(data, dict) and ("openapi" in data or "swagger" in data)


async def _fetch_one(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    api_id: int,
    spec_url: str,
) -> tuple[int, dict | None, str | None]:
    """Fetch a single spec. Returns (id, spec_dict_or_None, error_or_None)."""
    async with semaphore:
        try:
            resp = await client.get(spec_url, follow_redirects=True)
            await asyncio.sleep(0.5)
        except httpx.HTTPError as e:
            return (api_id, None, f"HTTP error: {type(e).__name__}: {e}")

    if resp.status_code != 200:
        return (api_id, None, f"HTTP {resp.status_code}")

    if len(resp.content) > MAX_SPEC_BYTES:
        return (api_id, None, f"Spec too large: {len(resp.content):,} bytes")

    # Try JSON first, then YAML
    try:
        data = resp.json()
    except Exception:
        try:
            data = yaml.safe_load(resp.text)
        except Exception as e:
            return (api_id, None, f"Parse error: {type(e).__name__}")

    if not _is_valid_spec(data):
        return (api_id, None, "Not a valid OpenAPI/Swagger spec")

    return (api_id, data, None)


def _batch_write_specs(results: list[tuple[int, dict | None, str | None]]) -> int:
    """Batch write spec_json / spec_error to public_apis."""
    from psycopg2.extras import execute_values

    successes = [(r[0], json_mod.dumps(r[1])) for r in results if r[1] is not None]
    failures = [(r[0], (r[2] or "unknown")[:500]) for r in results if r[1] is None and r[2]]

    count = 0
    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()

        if successes:
            cur.execute("""
                CREATE TEMP TABLE _spec_ok (
                    id INTEGER PRIMARY KEY,
                    spec_json JSONB
                ) ON COMMIT DROP
            """)
            execute_values(
                cur,
                "INSERT INTO _spec_ok (id, spec_json) VALUES %s",
                successes,
                template="(%s, %s::jsonb)",
                page_size=50,
            )
            cur.execute("""
                UPDATE public_apis p SET
                    spec_json = b.spec_json,
                    spec_fetched_at = NOW(),
                    spec_error = NULL
                FROM _spec_ok b WHERE p.id = b.id
            """)
            count += cur.rowcount

        if failures:
            cur.execute("""
                CREATE TEMP TABLE _spec_err (
                    id INTEGER PRIMARY KEY,
                    spec_error VARCHAR(500)
                ) ON COMMIT DROP
            """)
            execute_values(
                cur,
                "INSERT INTO _spec_err (id, spec_error) VALUES %s",
                failures,
                template="(%s, %s)",
                page_size=100,
            )
            cur.execute("""
                UPDATE public_apis p SET
                    spec_error = b.spec_error,
                    spec_fetched_at = NOW()
                FROM _spec_err b WHERE p.id = b.id
            """)

        raw_conn.commit()
    except Exception as e:
        try:
            raw_conn.rollback()
        except Exception:
            pass
        logger.error(f"Batch write specs failed: {e}")
    finally:
        try:
            raw_conn.close()
        except Exception:
            pass

    return count


async def ingest_api_specs(batch_limit: int = 500) -> dict:
    """Fetch and cache OpenAPI specs for public APIs."""
    started_at = datetime.now(timezone.utc)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, spec_url
            FROM public_apis
            WHERE spec_url IS NOT NULL
              AND spec_json IS NULL
              AND spec_error IS NULL
            ORDER BY id
            LIMIT :lim
        """), {"lim": batch_limit}).fetchall()

    if not rows:
        logger.info("No specs to fetch")
        return {"fetched": 0, "cached": 0, "errors": 0}

    logger.info(f"Fetching specs for {len(rows)} APIs")
    semaphore = asyncio.Semaphore(5)
    results: list[tuple[int, dict | None, str | None]] = []

    async with httpx.AsyncClient(
        headers={"User-Agent": "pt-edge/1.0"}, timeout=30.0
    ) as client:
        for r in rows:
            m = r._mapping
            result = await _fetch_one(client, semaphore, m["id"], m["spec_url"])
            results.append(result)

    cached = _batch_write_specs(results)
    errors = sum(1 for r in results if r[1] is None)

    _log_sync(started_at, cached, f"{errors} errors" if errors else None)

    result = {"fetched": len(rows), "cached": cached, "errors": errors}
    logger.info(f"api_specs complete: {result}")
    return result


def _log_sync(started_at: datetime, records: int, error: str | None) -> None:
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="api_specs",
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
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    result = await ingest_api_specs(batch_limit=limit)
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
