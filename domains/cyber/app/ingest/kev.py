"""CISA Known Exploited Vulnerabilities (KEV) catalog ingest.

Data source: https://www.cisa.gov/known-exploited-vulnerabilities-catalog
License: Public domain (US Government)

Downloads the KEV JSON catalog (~1,559 entries) and marks matching CVEs
with is_kev=True and kev_date_added. Single HTTP request, no rate limiting.
"""

import logging
from datetime import datetime, timezone

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.models import SyncLog

logger = logging.getLogger(__name__)

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
TIMEOUT = 30
BATCH_SIZE = 500


def _is_bootstrap() -> bool:
    """Check if we've ever completed a successful KEV ingest."""
    with engine.connect() as conn:
        count = conn.execute(text("""
            SELECT COUNT(*) FROM sync_log
            WHERE sync_type = 'kev'
              AND status IN ('success', 'partial')
        """)).scalar()
    return count == 0


def _log_sync(started: datetime, records: int, status: str = "success", error: str | None = None):
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="kev",
            status=status,
            records_written=records,
            error_message=error[:2000] if error else None,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()


def _parse_entries(data: dict) -> list[dict]:
    """Extract CVE ID + dateAdded from KEV catalog."""
    entries = []
    for vuln in data.get("vulnerabilities", []):
        cve_id = vuln.get("cveID")
        date_added = vuln.get("dateAdded")
        if cve_id and date_added:
            entries.append({"cve_id": cve_id, "date_added": date_added})
    return entries


def _update_kev_flags(entries: list[dict]) -> int:
    """Mark matching CVEs as KEV-listed and reset stale flags."""
    if not entries:
        return 0

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        # Bulk update: set is_kev=True, kev_date_added for matching CVEs
        values = [(e["date_added"], e["cve_id"]) for e in entries]
        execute_values(cur, """
            UPDATE cves AS c SET
                is_kev = TRUE,
                kev_date_added = v.date_added::date,
                updated_at = now()
            FROM (VALUES %s) AS v(date_added, cve_id)
            WHERE c.cve_id = v.cve_id
        """, values, page_size=BATCH_SIZE)
        updated = cur.rowcount

        # Reset stale flags: CVEs removed from KEV (rare but happens)
        kev_cve_ids = [e["cve_id"] for e in entries]
        # Build a parameterized IN clause
        cur.execute("""
            UPDATE cves SET is_kev = FALSE, kev_date_added = NULL, updated_at = now()
            WHERE is_kev = TRUE AND cve_id != ALL(%s)
        """, (kev_cve_ids,))
        reset_count = cur.rowcount

        raw.commit()
        if reset_count > 0:
            logger.info(f"Reset {reset_count} stale KEV flags")
        return updated
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


async def ingest_kev() -> dict:
    """Download CISA KEV catalog and mark matching CVEs."""
    started = datetime.now(timezone.utc)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(KEV_URL, timeout=TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
            data = resp.json()

        catalog_count = data.get("count", 0)
        entries = _parse_entries(data)
        logger.info(f"KEV catalog: {catalog_count} entries, parsed {len(entries)}")

        updated = _update_kev_flags(entries)
        logger.info(f"KEV ingest complete: {updated} CVEs marked as KEV-listed")

        _log_sync(started, updated, "success")
        return {"catalog_count": catalog_count, "updated": updated}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.exception(f"KEV ingest failed: {error_msg}")
        _log_sync(started, 0, "failed", error_msg)
        raise
