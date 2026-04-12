"""MITRE CAPEC (Common Attack Pattern Enumeration and Classification) ingest.

Data source: https://capec.mitre.org/
Download: https://capec.mitre.org/data/xml/capec_latest.xml
License: Public domain (MITRE / US Government funded)

Downloads the CAPEC XML catalog (~500 attack patterns), populates the
attack_patterns table and builds weakness_patterns links (CWE→CAPEC).
"""

import logging
from datetime import datetime, timezone

import httpx
from lxml import etree
from psycopg2.extras import execute_values
from sqlalchemy import text

from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.models import SyncLog

logger = logging.getLogger(__name__)

CAPEC_URL = "https://capec.mitre.org/data/xml/capec_latest.xml"
TIMEOUT = 60
BATCH_SIZE = 500

# CAPEC XML namespace
NS = {"capec": "http://capec.mitre.org/capec-3"}


def _log_sync(started: datetime, records: int, status: str = "success", error: str | None = None):
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="mitre_capec",
            status=status,
            records_written=records,
            error_message=error[:2000] if error else None,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()


def _text(el, xpath: str) -> str | None:
    """Extract text from first matching element."""
    found = el.find(xpath, NS)
    if found is not None:
        return "".join(found.itertext()).strip() or None
    return None


def _parse_patterns(root) -> tuple[list[dict], list[tuple[str, str]]]:
    """Parse CAPEC XML Attack_Pattern elements.

    Returns:
        patterns: list of dicts with CAPEC fields
        cwe_links: list of (capec_id, cwe_id) tuples
    """
    patterns = []
    cwe_links = []

    for ap in root.findall(".//capec:Attack_Pattern", NS):
        status = ap.get("Status", "")
        if status == "Deprecated":
            continue

        capec_id = f"CAPEC-{ap.get('ID')}"
        name = ap.get("Name", capec_id)

        description = _text(ap, "capec:Description")
        severity = _text(ap, "capec:Typical_Severity")
        likelihood = _text(ap, "capec:Likelihood_Of_Attack")

        patterns.append({
            "capec_id": capec_id,
            "name": name,
            "description": description,
            "severity": severity,
            "likelihood": likelihood,
        })

        # CWE mappings
        for rw in ap.findall(".//capec:Related_Weaknesses/capec:Related_Weakness", NS):
            cwe_num = rw.get("CWE_ID")
            if cwe_num:
                cwe_links.append((capec_id, f"CWE-{cwe_num}"))

    return patterns, cwe_links


def _upsert_patterns(patterns: list[dict]) -> int:
    """Batch upsert attack patterns."""
    if not patterns:
        return 0

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        values = [
            (p["capec_id"], p["name"], p["description"], p["severity"], p["likelihood"])
            for p in patterns
        ]
        execute_values(cur, """
            INSERT INTO attack_patterns (capec_id, name, description, severity, likelihood)
            VALUES %s
            ON CONFLICT (capec_id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                severity = EXCLUDED.severity,
                likelihood = EXCLUDED.likelihood,
                updated_at = now()
        """, values, page_size=BATCH_SIZE)
        count = cur.rowcount
        raw.commit()
        return count
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _link_weakness_patterns(links: list[tuple[str, str]]) -> int:
    """Build weakness_patterns links from (capec_id, cwe_id) pairs."""
    if not links:
        return 0

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        execute_values(cur, """
            INSERT INTO weakness_patterns (weakness_id, pattern_id)
            SELECT w.id, ap.id
            FROM (VALUES %s) AS v(capec_id, cwe_id)
            JOIN weaknesses w ON w.cwe_id = v.cwe_id
            JOIN attack_patterns ap ON ap.capec_id = v.capec_id
            ON CONFLICT (weakness_id, pattern_id) DO NOTHING
        """, links, page_size=BATCH_SIZE)
        count = cur.rowcount
        raw.commit()
        return count
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


async def ingest_capec() -> dict:
    """Download CAPEC XML and populate attack patterns + CWE links."""
    started = datetime.now(timezone.utc)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(CAPEC_URL, timeout=TIMEOUT, follow_redirects=True)
            resp.raise_for_status()

        root = etree.fromstring(resp.content)
        patterns, cwe_links = _parse_patterns(root)
        logger.info(f"CAPEC: parsed {len(patterns)} patterns, {len(cwe_links)} CWE links")

        upserted = _upsert_patterns(patterns)
        linked = _link_weakness_patterns(cwe_links)
        logger.info(f"CAPEC ingest complete: {upserted} patterns, {linked} weakness links")

        _log_sync(started, upserted, "success")
        return {"parsed": len(patterns), "upserted": upserted, "weakness_links": linked}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.exception(f"CAPEC ingest failed: {error_msg}")
        _log_sync(started, 0, "failed", error_msg)
        raise
