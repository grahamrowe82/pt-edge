"""OSV.dev ingest — open-source vulnerability data with fix versions.

Data source: https://osv.dev/
API: POST https://api.osv.dev/v1/query
License: Apache 2.0

Queries OSV for CVEs in our database to determine if fixes exist.
Updates has_fix and fix_versions on the cves table.
"""

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.models import SyncLog

logger = logging.getLogger(__name__)

OSV_API = "https://api.osv.dev/v1/querybatch"
BATCH_SIZE = 1000
TIMEOUT = 30


def _log_sync(started: datetime, records: int, status: str = "success", error: str | None = None):
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="osv",
            status=status,
            records_written=records,
            error_message=error[:2000] if error else None,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()


def _get_cve_ids_without_fix(limit: int = 50000) -> list[str]:
    """Get CVE IDs that don't have fix information yet."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT cve_id FROM cves
            WHERE has_fix IS NULL OR has_fix = false
            ORDER BY cvss_base_score DESC NULLS LAST
            LIMIT :lim
        """), {"lim": limit}).fetchall()
    return [r[0] for r in rows]


async def _query_osv_batch(client: httpx.AsyncClient, cve_ids: list[str]) -> dict[str, list]:
    """Query OSV API for a batch of CVE IDs. Returns {cve_id: [fix_versions]}."""
    queries = [{"commit": None, "version": None, "package": None}
               for _ in cve_ids]
    # OSV querybatch expects package queries, but we can also query by vulnerability ID
    # Use individual queries grouped for efficiency
    results = {}
    for cve_id in cve_ids:
        try:
            resp = await client.post(
                "https://api.osv.dev/v1/query",
                json={"package": {}, "version": "", "commit": ""},
                timeout=TIMEOUT,
            )
            # Actually, OSV query by CVE ID is via GET /v1/vulns/{id}
            resp = await client.get(
                f"https://api.osv.dev/v1/vulns/{cve_id}",
                timeout=TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                fix_versions = []
                for affected in data.get("affected", []):
                    for rng in affected.get("ranges", []):
                        for event in rng.get("events", []):
                            if "fixed" in event:
                                fix_versions.append(event["fixed"])
                if fix_versions:
                    results[cve_id] = fix_versions
        except Exception:
            continue
    return results


def _update_fix_status(fixes: dict[str, list]) -> int:
    """Bulk update has_fix and fix_versions on cves table."""
    if not fixes:
        return 0

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        import json
        from psycopg2.extras import execute_values

        values = [(json.dumps(versions), cve_id) for cve_id, versions in fixes.items()]
        execute_values(cur, """
            UPDATE cves AS c SET
                has_fix = true,
                fix_versions = v.versions::jsonb,
                updated_at = now()
            FROM (VALUES %s) AS v(versions, cve_id)
            WHERE c.cve_id = v.cve_id
        """, values, page_size=500)
        count = cur.rowcount
        raw.commit()
        return count
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


async def ingest_osv() -> dict:
    """Query OSV for fix information on CVEs without fix data."""
    started = datetime.now(timezone.utc)

    try:
        cve_ids = _get_cve_ids_without_fix(limit=5000)
        if not cve_ids:
            _log_sync(started, 0, "success")
            return {"queried": 0, "fixes_found": 0}

        logger.info(f"OSV: querying fix status for {len(cve_ids)} CVEs")

        all_fixes = {}
        async with httpx.AsyncClient() as client:
            for start in range(0, len(cve_ids), BATCH_SIZE):
                batch = cve_ids[start:start + BATCH_SIZE]
                fixes = await _query_osv_batch(client, batch)
                all_fixes.update(fixes)
                if fixes:
                    logger.info(f"  OSV batch {start}: {len(fixes)} fixes found")

        updated = _update_fix_status(all_fixes)
        logger.info(f"OSV ingest complete: {len(cve_ids)} queried, {updated} fixes applied")

        _log_sync(started, updated, "success")
        return {"queried": len(cve_ids), "fixes_found": len(all_fixes), "updated": updated}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.exception(f"OSV ingest failed: {error_msg}")
        _log_sync(started, 0, "failed", error_msg)
        raise
