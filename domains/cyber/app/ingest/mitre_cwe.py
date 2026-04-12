"""MITRE CWE (Common Weakness Enumeration) ingest.

Data source: https://cwe.mitre.org/
Download: https://cwe.mitre.org/data/xml/cwec_latest.xml.zip
License: Public domain (MITRE / US Government funded)

Downloads the CWE XML catalog (~900 weaknesses), enriches existing stubs
from NVD ingest with full descriptions, hierarchy, consequences, and
detection methods. Also adds CWE entries not referenced by any CVE.
"""

import io
import logging
import zipfile
from datetime import datetime, timezone

import httpx
from lxml import etree
from psycopg2.extras import execute_values
from sqlalchemy import text

from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.models import SyncLog

logger = logging.getLogger(__name__)

CWE_URL = "https://cwe.mitre.org/data/xml/cwec_latest.xml.zip"
TIMEOUT = 60
BATCH_SIZE = 500

# CWE XML namespace
NS = {"cwe": "http://cwe.mitre.org/cwe-7"}


def _log_sync(started: datetime, records: int, status: str = "success", error: str | None = None):
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="mitre_cwe",
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
        # Get all text content including nested elements
        return "".join(found.itertext()).strip() or None
    return None


def _parse_weaknesses(root) -> tuple[list[dict], list[tuple[str, str]]]:
    """Parse CWE XML Weakness elements.

    Returns:
        weaknesses: list of dicts with CWE fields
        hierarchy: list of (child_cwe_id, parent_cwe_id) tuples
    """
    weaknesses = []
    hierarchy = []

    for w in root.findall(".//cwe:Weakness", NS):
        cwe_id = f"CWE-{w.get('ID')}"
        name = w.get("Name", cwe_id)
        abstraction = w.get("Abstraction")

        description = _text(w, "cwe:Description")

        # Common consequences
        consequences = []
        for c in w.findall(".//cwe:Common_Consequences/cwe:Consequence", NS):
            scope = _text(c, "cwe:Scope")
            impact = _text(c, "cwe:Impact")
            if scope or impact:
                consequences.append({"scope": scope, "impact": impact})

        # Detection methods
        detection = []
        for d in w.findall(".//cwe:Detection_Methods/cwe:Detection_Method", NS):
            method = _text(d, "cwe:Method")
            desc = _text(d, "cwe:Description")
            if method:
                detection.append({"method": method, "description": desc})

        weaknesses.append({
            "cwe_id": cwe_id,
            "name": name,
            "description": description,
            "abstraction": abstraction,
            "common_consequences": consequences if consequences else None,
            "detection_methods": detection if detection else None,
        })

        # Parent/child hierarchy via ChildOf relationships
        for rel in w.findall(".//cwe:Related_Weaknesses/cwe:Related_Weakness", NS):
            if rel.get("Nature") == "ChildOf":
                parent_id = rel.get("CWE_ID")
                if parent_id:
                    hierarchy.append((cwe_id, f"CWE-{parent_id}"))

    return weaknesses, hierarchy


def _upsert_weaknesses(rows: list[dict], hierarchy: list[tuple[str, str]]) -> int:
    """Batch upsert weaknesses and resolve parent hierarchy."""
    if not rows:
        return 0

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        import json

        values = [
            (
                r["cwe_id"], r["name"], r["description"], r["abstraction"],
                json.dumps(r["common_consequences"]) if r["common_consequences"] else None,
                json.dumps(r["detection_methods"]) if r["detection_methods"] else None,
            )
            for r in rows
        ]

        execute_values(cur, """
            INSERT INTO weaknesses (cwe_id, name, description, abstraction,
                                    common_consequences, detection_methods)
            VALUES %s
            ON CONFLICT (cwe_id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                abstraction = EXCLUDED.abstraction,
                common_consequences = EXCLUDED.common_consequences,
                detection_methods = EXCLUDED.detection_methods,
                updated_at = now()
        """, values, page_size=BATCH_SIZE)
        upserted = cur.rowcount

        # Resolve parent hierarchy in a second pass
        if hierarchy:
            execute_values(cur, """
                UPDATE weaknesses AS w SET parent_weakness_id = p.id
                FROM (VALUES %s) AS v(child_cwe, parent_cwe)
                JOIN weaknesses p ON p.cwe_id = v.parent_cwe
                WHERE w.cwe_id = v.child_cwe
            """, hierarchy, page_size=BATCH_SIZE)
            logger.info(f"CWE hierarchy: {cur.rowcount} parent links resolved")

        raw.commit()
        return upserted
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


async def ingest_cwe() -> dict:
    """Download CWE XML and enrich weakness entries."""
    started = datetime.now(timezone.utc)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(CWE_URL, timeout=TIMEOUT, follow_redirects=True)
            resp.raise_for_status()

        # Extract XML from zip
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_names = [n for n in zf.namelist() if n.endswith(".xml")]
            if not xml_names:
                raise ValueError("No XML file found in CWE zip")
            xml_content = zf.read(xml_names[0])

        root = etree.fromstring(xml_content)
        weaknesses, hierarchy = _parse_weaknesses(root)
        logger.info(f"CWE: parsed {len(weaknesses)} weaknesses, {len(hierarchy)} hierarchy links")

        upserted = _upsert_weaknesses(weaknesses, hierarchy)
        logger.info(f"CWE ingest complete: {upserted} weaknesses upserted")

        _log_sync(started, upserted, "success")
        return {"parsed": len(weaknesses), "upserted": upserted, "hierarchy": len(hierarchy)}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.exception(f"CWE ingest failed: {error_msg}")
        _log_sync(started, 0, "failed", error_msg)
        raise
