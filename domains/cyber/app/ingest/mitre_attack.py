"""MITRE ATT&CK ingest — techniques, tactics, and CAPEC mappings.

Data source: https://attack.mitre.org/
Download: STIX 2.1 JSON from https://github.com/mitre-attack/attack-stix-data
License: Apache 2.0

Downloads the Enterprise ATT&CK STIX bundle (~700 techniques + 14 tactics),
populates the techniques table, builds technique_tactics links and
pattern_techniques links (CAPEC→ATT&CK).
"""

import logging
from datetime import datetime, timezone

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.models import SyncLog

logger = logging.getLogger(__name__)

ATTACK_URL = "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/enterprise-attack/enterprise-attack.json"
TIMEOUT = 120  # larger file
BATCH_SIZE = 500


def _log_sync(started: datetime, records: int, status: str = "success", error: str | None = None):
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="mitre_attack",
            status=status,
            records_written=records,
            error_message=error[:2000] if error else None,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()


def _parse_stix(bundle: dict) -> tuple[list[dict], list[dict], list[tuple[str, str]]]:
    """Parse STIX 2.1 bundle.

    Returns:
        techniques: list of technique dicts
        tactic_links: list of {technique_id, tactic_shortname} dicts
        capec_links: list of (technique_id, capec_id) tuples
    """
    techniques = []
    tactic_links = []
    capec_links = []

    for obj in bundle.get("objects", []):
        if obj.get("type") != "attack-pattern":
            continue
        if obj.get("revoked", False) or obj.get("x_mitre_deprecated", False):
            continue

        # Extract technique ID from external_references
        technique_id = None
        capec_ids = []
        for ref in obj.get("external_references", []):
            if ref.get("source_name") == "mitre-attack":
                technique_id = ref.get("external_id")
            elif ref.get("source_name") == "capec":
                capec_id = ref.get("external_id")
                if capec_id:
                    capec_ids.append(f"CAPEC-{capec_id}")

        if not technique_id:
            continue

        is_sub = obj.get("x_mitre_is_subtechnique", False)

        techniques.append({
            "technique_id": technique_id,
            "name": obj.get("name", technique_id),
            "description": obj.get("description"),
            "platforms": obj.get("x_mitre_platforms"),
            "data_sources": obj.get("x_mitre_data_sources"),
            "detection": obj.get("x_mitre_detection"),
            "is_subtechnique": is_sub,
        })

        # Tactic links from kill_chain_phases
        for phase in obj.get("kill_chain_phases", []):
            if phase.get("kill_chain_name") == "mitre-attack":
                tactic_links.append({
                    "technique_id": technique_id,
                    "tactic_shortname": phase["phase_name"],
                })

        # CAPEC links
        for capec_id in capec_ids:
            capec_links.append((technique_id, capec_id))

    return techniques, tactic_links, capec_links


def _parse_tactics(bundle: dict) -> dict[str, tuple[str, str]]:
    """Extract tactic shortname → (tactic_id, tactic_name) from x-mitre-tactic objects."""
    tactic_map = {}
    for obj in bundle.get("objects", []):
        if obj.get("type") != "x-mitre-tactic":
            continue
        shortname = obj.get("x_mitre_shortname")
        name = obj.get("name")
        # Extract tactic ID (e.g. TA0001) from external_references
        tactic_id = None
        for ref in obj.get("external_references", []):
            if ref.get("source_name") == "mitre-attack":
                tactic_id = ref.get("external_id")
                break
        if shortname and tactic_id:
            tactic_map[shortname] = (tactic_id, name)
    return tactic_map


def _upsert_techniques(techniques: list[dict]) -> int:
    """Batch upsert techniques and resolve parent hierarchy for sub-techniques."""
    if not techniques:
        return 0

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        values = [
            (
                t["technique_id"], t["name"], t["description"],
                t["platforms"], t["data_sources"], t["detection"],
                t["is_subtechnique"],
            )
            for t in techniques
        ]
        execute_values(cur, """
            INSERT INTO techniques (technique_id, name, description,
                                    platforms, data_sources, detection, is_subtechnique)
            VALUES %s
            ON CONFLICT (technique_id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                platforms = EXCLUDED.platforms,
                data_sources = EXCLUDED.data_sources,
                detection = EXCLUDED.detection,
                is_subtechnique = EXCLUDED.is_subtechnique,
                updated_at = now()
        """, values, page_size=BATCH_SIZE)
        upserted = cur.rowcount

        # Resolve parent_technique_id for sub-techniques
        # T1059.001 → parent T1059
        sub_parents = []
        for t in techniques:
            if t["is_subtechnique"] and "." in t["technique_id"]:
                parent_id = t["technique_id"].split(".")[0]
                sub_parents.append((t["technique_id"], parent_id))

        if sub_parents:
            execute_values(cur, """
                UPDATE techniques AS t SET parent_technique_id = p.id
                FROM (VALUES %s) AS v(child_id, parent_id)
                JOIN techniques p ON p.technique_id = v.parent_id
                WHERE t.technique_id = v.child_id
            """, sub_parents, page_size=BATCH_SIZE)
            logger.info(f"ATT&CK: {cur.rowcount} sub-technique parent links resolved")

        raw.commit()
        return upserted
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _link_technique_tactics(links: list[dict], tactic_map: dict) -> int:
    """Build technique_tactics links."""
    if not links:
        return 0

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        values = []
        for link in links:
            shortname = link["tactic_shortname"]
            mapping = tactic_map.get(shortname)
            if mapping:
                tactic_id, tactic_name = mapping
                values.append((link["technique_id"], tactic_id, tactic_name))

        if not values:
            return 0

        execute_values(cur, """
            INSERT INTO technique_tactics (technique_id, tactic_id, tactic_name)
            SELECT t.id, v.tactic_id, v.tactic_name
            FROM (VALUES %s) AS v(tech_id_str, tactic_id, tactic_name)
            JOIN techniques t ON t.technique_id = v.tech_id_str
            ON CONFLICT (technique_id, tactic_id) DO NOTHING
        """, values, page_size=BATCH_SIZE)
        count = cur.rowcount
        raw.commit()
        return count
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _link_pattern_techniques(links: list[tuple[str, str]]) -> int:
    """Build pattern_techniques links from (technique_id, capec_id) pairs."""
    if not links:
        return 0

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        execute_values(cur, """
            INSERT INTO pattern_techniques (pattern_id, technique_id)
            SELECT ap.id, t.id
            FROM (VALUES %s) AS v(tech_id_str, capec_id)
            JOIN techniques t ON t.technique_id = v.tech_id_str
            JOIN attack_patterns ap ON ap.capec_id = v.capec_id
            ON CONFLICT (pattern_id, technique_id) DO NOTHING
        """, links, page_size=BATCH_SIZE)
        count = cur.rowcount
        raw.commit()
        return count
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


async def ingest_attack() -> dict:
    """Download ATT&CK STIX JSON and populate techniques + links."""
    started = datetime.now(timezone.utc)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(ATTACK_URL, timeout=TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
            bundle = resp.json()

        techniques, tactic_links, capec_links = _parse_stix(bundle)
        tactic_map = _parse_tactics(bundle)
        logger.info(
            f"ATT&CK: parsed {len(techniques)} techniques, "
            f"{len(tactic_links)} tactic links, {len(capec_links)} CAPEC links, "
            f"{len(tactic_map)} tactics"
        )

        upserted = _upsert_techniques(techniques)
        tactic_count = _link_technique_tactics(tactic_links, tactic_map)
        capec_count = _link_pattern_techniques(capec_links)
        logger.info(
            f"ATT&CK ingest complete: {upserted} techniques, "
            f"{tactic_count} tactic links, {capec_count} CAPEC links"
        )

        _log_sync(started, upserted, "success")
        return {
            "techniques": upserted,
            "tactic_links": tactic_count,
            "capec_links": capec_count,
        }

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.exception(f"ATT&CK ingest failed: {error_msg}")
        _log_sync(started, 0, "failed", error_msg)
        raise
