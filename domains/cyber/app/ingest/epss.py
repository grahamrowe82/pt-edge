"""EPSS (Exploit Prediction Scoring System) ingest.

Data source: https://www.first.org/epss/
License: Public domain
Download: https://epss.cyentia.com/epss_scores-current.csv.gz

Downloads the daily EPSS scores CSV (~270K CVEs) and bulk updates
epss_score + epss_percentile on the cves table. Single HTTP request,
no rate limiting. Uses temp table + UPDATE JOIN for performance.
"""

import csv
import gzip
import io
import logging
from datetime import datetime, timezone

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.models import SyncLog

logger = logging.getLogger(__name__)

EPSS_URL = "https://epss.cyentia.com/epss_scores-current.csv.gz"
TIMEOUT = 120  # larger file, allow more time
BATCH_SIZE = 5000  # larger batches for ~270K rows


def _is_bootstrap() -> bool:
    """Check if we've ever completed a successful EPSS ingest."""
    with engine.connect() as conn:
        count = conn.execute(text("""
            SELECT COUNT(*) FROM sync_log
            WHERE sync_type = 'epss'
              AND status IN ('success', 'partial')
        """)).scalar()
    return count == 0


def _log_sync(started: datetime, records: int, status: str = "success", error: str | None = None):
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="epss",
            status=status,
            records_written=records,
            error_message=error[:2000] if error else None,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()


def _parse_csv(raw_bytes: bytes) -> list[tuple[str, float, float]]:
    """Parse EPSS gzipped CSV into list of (cve_id, epss, percentile).

    CSV format:
        # model_version:...,score_date:...
        cve,epss,percentile
        CVE-2021-44228,0.97564,0.99998
        ...
    """
    decompressed = gzip.decompress(raw_bytes)
    text_data = decompressed.decode("utf-8")

    scores = []
    reader = csv.reader(io.StringIO(text_data))
    for row in reader:
        # Skip comment lines and header
        if not row or row[0].startswith("#"):
            continue
        if row[0] == "cve":
            continue

        try:
            cve_id = row[0]
            epss = float(row[1])
            percentile = float(row[2])
            scores.append((cve_id, epss, percentile))
        except (IndexError, ValueError):
            continue

    return scores


def _update_epss_scores(scores: list[tuple[str, float, float]]) -> int:
    """Bulk update cves table with EPSS scores via temp table + UPDATE JOIN."""
    if not scores:
        return 0

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        # Create temp table for staging
        cur.execute("""
            CREATE TEMP TABLE _epss_staging (
                cve_id text NOT NULL,
                epss float NOT NULL,
                percentile float NOT NULL
            ) ON COMMIT DROP
        """)

        # Bulk insert into staging table
        execute_values(cur, """
            INSERT INTO _epss_staging (cve_id, epss, percentile) VALUES %s
        """, scores, page_size=BATCH_SIZE)
        logger.info(f"EPSS staging: {len(scores):,} rows loaded")

        # Update cves table via JOIN
        cur.execute("""
            UPDATE cves c SET
                epss_score = s.epss,
                epss_percentile = s.percentile,
                updated_at = now()
            FROM _epss_staging s
            WHERE c.cve_id = s.cve_id
        """)
        updated = cur.rowcount

        raw.commit()
        return updated
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


async def ingest_epss() -> dict:
    """Download EPSS scores and update all CVEs."""
    started = datetime.now(timezone.utc)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(EPSS_URL, timeout=TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
            raw_bytes = resp.content

        scores = _parse_csv(raw_bytes)
        logger.info(f"EPSS: parsed {len(scores):,} scores")

        updated = _update_epss_scores(scores)
        logger.info(f"EPSS ingest complete: {updated:,} CVEs updated")

        _log_sync(started, updated, "success")
        return {"parsed": len(scores), "updated": updated}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.exception(f"EPSS ingest failed: {error_msg}")
        _log_sync(started, 0, "failed", error_msg)
        raise
