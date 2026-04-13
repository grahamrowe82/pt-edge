"""Pre-compute relationship pairs for static site generation.

Computes CVE-software pairs, vendor weakness portfolios, and kill chain
pages, then stores them in the structural_cache table as JSON. The site
generator reads from cache — zero computation at build time.

Runs weekly via the task queue (pairs change slowly).
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.models import SyncLog

logger = logging.getLogger(__name__)


def _log_sync(started: datetime, records: int, status: str = "success", error: str | None = None):
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="compute_pairs",
            status=status,
            records_written=records,
            error_message=error[:2000] if error else None,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()


def _cache_json(key: str, data: list):
    """Upsert pre-computed data into structural_cache."""
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO structural_cache (key, value, updated_at)
            VALUES (:key, :val, now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """), {"key": key, "val": json.dumps(data)})
        conn.commit()


def _compute_cve_software_pairs() -> list[dict]:
    """Top 10 software per CVE (by software score), for CVEs with composite >= 30.

    Returns list of {cve_id, cve_score, software_name, software_slug, software_score, cve_tier}.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            WITH ranked AS (
                SELECT cs.cve_id AS cve_pk, c.cve_id, cv.composite_score AS cve_score,
                       cv.quality_tier AS cve_tier,
                       s.name AS software_name, s.cpe_id,
                       sv.composite_score AS software_score,
                       ROW_NUMBER() OVER (PARTITION BY cs.cve_id ORDER BY sv.composite_score DESC NULLS LAST) AS rn
                FROM cve_software cs
                JOIN cves c ON c.id = cs.cve_id
                JOIN mv_cve_scores cv ON cv.id = cs.cve_id
                JOIN software s ON s.id = cs.software_id
                LEFT JOIN mv_software_scores sv ON sv.id = s.id
                WHERE cv.composite_score >= 30
            )
            SELECT cve_id, cve_score, cve_tier, software_name, cpe_id, software_score
            FROM ranked WHERE rn <= 10
            ORDER BY cve_score DESC, software_score DESC NULLS LAST
        """)).mappings().fetchall()
    return [dict(r) for r in rows]


def _compute_vendor_weakness_pairs() -> list[dict]:
    """Top weaknesses per vendor by CVE count, for vendors with score >= 20.

    Returns list of {vendor_slug, vendor_name, vendor_score, cwe_id, weakness_name, cve_count}.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT v.slug AS vendor_slug, v.name AS vendor_name,
                   vs.composite_score AS vendor_score,
                   w.cwe_id, w.name AS weakness_name,
                   COUNT(DISTINCT cw.cve_id) AS cve_count
            FROM cve_vendors cv
            JOIN vendors v ON v.id = cv.vendor_id
            JOIN mv_vendor_scores vs ON vs.id = v.id
            JOIN cve_weaknesses cw ON cw.cve_id = cv.cve_id
            JOIN weaknesses w ON w.id = cw.weakness_id
            WHERE vs.composite_score >= 20
            GROUP BY v.slug, v.name, vs.composite_score, w.cwe_id, w.name
            HAVING COUNT(DISTINCT cw.cve_id) >= 2
            ORDER BY vs.composite_score DESC, cve_count DESC
        """)).mappings().fetchall()
    return [dict(r) for r in rows]


def _compute_kill_chain_pages() -> list[dict]:
    """Distinct CWE→CAPEC→ATT&CK chains with CVE counts >= 3.

    Returns list of {cwe_id, weakness_name, capec_id, pattern_name, technique_id,
                     technique_name, cve_count}.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT w.cwe_id, w.name AS weakness_name,
                   ap.capec_id, ap.name AS pattern_name,
                   t.technique_id, t.name AS technique_name,
                   COUNT(DISTINCT cw.cve_id) AS cve_count
            FROM cve_weaknesses cw
            JOIN weaknesses w ON w.id = cw.weakness_id
            JOIN weakness_patterns wp ON wp.weakness_id = w.id
            JOIN attack_patterns ap ON ap.id = wp.pattern_id
            JOIN pattern_techniques pt ON pt.pattern_id = ap.id
            JOIN techniques t ON t.id = pt.technique_id
            GROUP BY w.cwe_id, w.name, ap.capec_id, ap.name, t.technique_id, t.name
            HAVING COUNT(DISTINCT cw.cve_id) >= 3
            ORDER BY cve_count DESC
        """)).mappings().fetchall()
    return [dict(r) for r in rows]


def _compute_cve_enrichment() -> dict:
    """Pre-compute per-CVE enrichment for site generation.

    Builds a dict keyed by cve.id containing software, vendors, weaknesses,
    and kill chain data. Only includes CVEs in mv_cve_scores (those with pages).
    """
    result = {}
    with engine.connect() as conn:
        # Software links (top 20 per CVE by name)
        rows = conn.execute(text("""
            WITH ranked AS (
                SELECT cs.cve_id, s.name, s.cpe_id,
                       ROW_NUMBER() OVER (PARTITION BY cs.cve_id ORDER BY s.name) AS rn
                FROM cve_software cs
                JOIN software s ON s.id = cs.software_id
                WHERE cs.cve_id IN (SELECT id FROM mv_cve_scores)
            )
            SELECT cve_id, name, cpe_id FROM ranked WHERE rn <= 20
        """)).mappings().fetchall()
        for r in rows:
            result.setdefault(r["cve_id"], {}).setdefault("software", []).append(
                {"name": r["name"], "cpe_id": r["cpe_id"]})
        logger.info(f"  CVE enrichment: {len(rows):,} software links")

        # Vendor links
        rows = conn.execute(text("""
            SELECT cv.cve_id, v.name, v.slug
            FROM cve_vendors cv
            JOIN vendors v ON v.id = cv.vendor_id
            WHERE cv.cve_id IN (SELECT id FROM mv_cve_scores)
        """)).mappings().fetchall()
        for r in rows:
            result.setdefault(r["cve_id"], {}).setdefault("vendors", []).append(
                {"name": r["name"], "slug": r["slug"]})
        logger.info(f"  CVE enrichment: {len(rows):,} vendor links")

        # Weakness links
        rows = conn.execute(text("""
            SELECT cw.cve_id, w.cwe_id, w.name
            FROM cve_weaknesses cw
            JOIN weaknesses w ON w.id = cw.weakness_id
            WHERE cw.cve_id IN (SELECT id FROM mv_cve_scores)
        """)).mappings().fetchall()
        for r in rows:
            result.setdefault(r["cve_id"], {}).setdefault("weaknesses", []).append(
                {"cwe_id": r["cwe_id"], "name": r["name"]})
        logger.info(f"  CVE enrichment: {len(rows):,} weakness links")

        # Kill chain: CWE → CAPEC → ATT&CK (top 5 per CVE)
        rows = conn.execute(text("""
            WITH chains AS (
                SELECT DISTINCT cw.cve_id, w.cwe_id, ap.capec_id,
                       t.technique_id, t.name AS technique_name
                FROM cve_weaknesses cw
                JOIN weaknesses w ON w.id = cw.weakness_id
                JOIN weakness_patterns wp ON wp.weakness_id = w.id
                JOIN attack_patterns ap ON ap.id = wp.pattern_id
                JOIN pattern_techniques pt ON pt.pattern_id = ap.id
                JOIN techniques t ON t.id = pt.technique_id
                WHERE cw.cve_id IN (SELECT id FROM mv_cve_scores)
            ),
            ranked AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY cve_id ORDER BY technique_id) AS rn
                FROM chains
            )
            SELECT cve_id, cwe_id, capec_id, technique_id, technique_name
            FROM ranked WHERE rn <= 5
        """)).mappings().fetchall()
        for r in rows:
            result.setdefault(r["cve_id"], {}).setdefault("kill_chain", []).append(
                {"cwe_id": r["cwe_id"], "capec_id": r["capec_id"],
                 "technique_id": r["technique_id"], "technique_name": r["technique_name"]})
        logger.info(f"  CVE enrichment: {len(rows):,} kill chain paths")

    return result


async def compute_all_pairs() -> dict:
    """Pre-compute all relationship pairs and CVE enrichment, cache as JSON."""
    started = datetime.now(timezone.utc)

    try:
        cve_sw = _compute_cve_software_pairs()
        logger.info(f"Computed {len(cve_sw):,} CVE-software pairs")
        _cache_json("cve_software_pairs", cve_sw)

        vendor_weak = _compute_vendor_weakness_pairs()
        logger.info(f"Computed {len(vendor_weak):,} vendor-weakness pairs")
        _cache_json("vendor_weakness_pairs", vendor_weak)

        chains = _compute_kill_chain_pages()
        logger.info(f"Computed {len(chains):,} kill chain pages")
        _cache_json("kill_chain_pages", chains)

        enrichment = _compute_cve_enrichment()
        logger.info(f"Computed CVE enrichment for {len(enrichment):,} CVEs")
        _cache_json("cve_enrichment", enrichment)

        total = len(cve_sw) + len(vendor_weak) + len(chains) + len(enrichment)
        _log_sync(started, total, "success")

        return {
            "cve_software_pairs": len(cve_sw),
            "vendor_weakness_pairs": len(vendor_weak),
            "kill_chain_pages": len(chains),
            "cve_enrichment": len(enrichment),
            "total": total,
        }

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.exception(f"Pair computation failed: {error_msg}")
        _log_sync(started, 0, "failed", error_msg)
        raise
