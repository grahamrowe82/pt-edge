"""Hypothesis engine — deterministic insight generation from the knowledge graph.

Surfaces structural anomalies: unpatched high-severity CVEs, incomplete
kill chain triangles, vendor patch rate outliers, and EPSS momentum without
public exploits. Each hypothesis is a mechanical consequence of the data,
scored by surprise + evidence + actionability.

Pre-computes and caches in structural_cache for static site generation.
"""

import json
import logging
import math
from datetime import datetime, timezone

from sqlalchemy import text

from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.models import SyncLog

logger = logging.getLogger(__name__)


def _log_sync(started: datetime, records: int, status: str = "success", error: str | None = None):
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="compute_hypotheses",
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


def _score_hypothesis(surprise: float, evidence: float, actionability: float) -> int:
    """Composite hypothesis score: surprise (0-50) + evidence (0-30) + actionability (0-20)."""
    return min(100, int(
        min(50, max(0, surprise)) +
        min(30, max(0, evidence)) +
        min(20, max(0, actionability))
    ))


# ---------------------------------------------------------------------------
# Hypothesis Type 1: Unpatched Exposure Gaps
# ---------------------------------------------------------------------------

def _compute_unpatched_exposure() -> list[dict]:
    """High severity + wide deployment + no fix = critical gap."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT c.cve_id, cs.severity, cs.exploitability, cs.exposure,
                   cs.composite_score, cs.quality_tier, c.epss_score,
                   COALESCE(sw.cnt, 0) AS affected_products
            FROM mv_cve_scores cs
            JOIN cves c ON c.id = cs.id
            LEFT JOIN (SELECT cve_id, COUNT(*) AS cnt FROM cve_software GROUP BY cve_id) sw
                ON sw.cve_id = c.id
            WHERE cs.severity >= 20
              AND cs.exposure >= 7
              AND (c.has_fix IS NULL OR c.has_fix = false)
            ORDER BY cs.composite_score DESC
            LIMIT 5000
        """)).mappings().fetchall()

    results = []
    for r in rows:
        d = dict(r)
        # Surprise: high severity without fix (most high-severity CVEs get patched)
        surprise = min(50, d["severity"] * 2)
        # Evidence: product spread
        evidence = min(30, math.log(d["affected_products"] + 1) * 5)
        # Actionability: high EPSS = urgent
        epss = d.get("epss_score") or 0
        actionability = min(20, 20 if epss > 0.5 else (10 if epss > 0.1 else 5))
        d["hypothesis_score"] = _score_hypothesis(surprise, evidence, actionability)
        d["hypothesis_type"] = "unpatched_exposure"
        results.append(d)

    results.sort(key=lambda x: x["hypothesis_score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Hypothesis Type 2: Attack Chain Gaps
# ---------------------------------------------------------------------------

def _compute_chain_gaps() -> list[dict]:
    """Software has weakness exposure to a technique but no verified exploit proves the chain."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT s.name AS software_name, t.technique_id, t.name AS technique_name,
                   w.cwe_id, w.name AS weakness_name,
                   COUNT(DISTINCT cw.cve_id) AS weakness_cve_count
            FROM software s
            JOIN cve_software csvw ON s.id = csvw.software_id
            JOIN cve_weaknesses cw ON csvw.cve_id = cw.cve_id
            JOIN weakness_patterns wp ON cw.weakness_id = wp.weakness_id
            JOIN pattern_techniques pt ON wp.pattern_id = pt.pattern_id
            JOIN techniques t ON pt.technique_id = t.id
            JOIN weaknesses w ON cw.weakness_id = w.id
            LEFT JOIN (
                SELECT cs2.software_id, pt2.technique_id
                FROM cve_software cs2
                JOIN cve_weaknesses cw2 ON cs2.cve_id = cw2.cve_id
                JOIN weakness_patterns wp2 ON cw2.weakness_id = wp2.weakness_id
                JOIN pattern_techniques pt2 ON wp2.pattern_id = pt2.pattern_id
                JOIN cve_exploits ce ON ce.cve_id = cs2.cve_id AND ce.verified = true
            ) direct ON direct.software_id = s.id AND direct.technique_id = t.id
            WHERE direct.software_id IS NULL
            GROUP BY s.name, t.technique_id, t.name, w.cwe_id, w.name
            HAVING COUNT(DISTINCT cw.cve_id) >= 3
            ORDER BY COUNT(DISTINCT cw.cve_id) DESC
            LIMIT 20000
        """)).mappings().fetchall()

    results = []
    for r in rows:
        d = dict(r)
        cve_count = d["weakness_cve_count"]
        surprise = min(50, math.log(cve_count + 1) * 12)
        evidence = min(30, cve_count * 2)
        actionability = 10  # chain gaps are informational
        d["hypothesis_score"] = _score_hypothesis(surprise, evidence, actionability)
        d["hypothesis_type"] = "chain_gap"
        results.append(d)

    results.sort(key=lambda x: x["hypothesis_score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Hypothesis Type 3: Vendor Risk Anomalies
# ---------------------------------------------------------------------------

def _compute_vendor_anomalies() -> list[dict]:
    """Retired — patch_availability dimension removed (has_fix only covers 0.3% of CVEs).
    Returns empty list. Will be redesigned to use proportion-based signals."""
    return []
    # Original implementation below for reference (dead code):
    """Vendors with patch_availability above their score bracket mean."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            WITH brackets AS (
                SELECT id, name, slug, composite_score, patch_availability,
                       (composite_score / 10) * 10 AS bracket
                FROM mv_vendor_scores
                WHERE composite_score >= 20
            ),
            stats AS (
                SELECT bracket,
                       AVG(patch_availability) AS avg_patch,
                       STDDEV(patch_availability) AS std_patch,
                       COUNT(*) AS bracket_size
                FROM brackets
                GROUP BY bracket
                HAVING COUNT(*) >= 3
            )
            SELECT b.name AS vendor_name, b.slug AS vendor_slug,
                   b.composite_score AS vendor_score, b.patch_availability,
                   s.avg_patch AS bracket_avg, s.std_patch AS bracket_std,
                   b.patch_availability - s.avg_patch AS gap
            FROM brackets b
            JOIN stats s ON b.bracket = s.bracket
            WHERE s.std_patch > 0
              AND b.patch_availability > s.avg_patch + s.std_patch
            ORDER BY (b.patch_availability - s.avg_patch) / GREATEST(s.std_patch, 1) DESC
            LIMIT 500
        """)).mappings().fetchall()

    results = []
    for r in rows:
        d = dict(r)
        std = d.get("bracket_std") or 1
        gap = d.get("gap") or 0
        z_score = gap / max(std, 1)
        surprise = min(50, z_score * 15)
        evidence = min(30, math.log(d.get("vendor_score", 1) + 1) * 5)
        actionability = min(20, 15 if gap > 10 else 5)
        d["hypothesis_score"] = _score_hypothesis(surprise, evidence, actionability)
        d["hypothesis_type"] = "vendor_anomaly"
        results.append(d)

    results.sort(key=lambda x: x["hypothesis_score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Hypothesis Type 4: Exploit Momentum Divergences
# ---------------------------------------------------------------------------

def _compute_momentum_divergences() -> list[dict]:
    """CVEs where EPSS >= 0.3 but no public exploit exists."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT c.cve_id, c.epss_score, c.is_kev,
                   cs.severity, cs.composite_score, cs.quality_tier
            FROM cves c
            JOIN mv_cve_scores cs ON cs.id = c.id
            LEFT JOIN cve_exploits ce ON ce.cve_id = c.id
            WHERE c.epss_score >= 0.3
              AND ce.id IS NULL
            ORDER BY c.epss_score DESC
            LIMIT 1000
        """)).mappings().fetchall()

    results = []
    for r in rows:
        d = dict(r)
        epss = d.get("epss_score") or 0
        surprise = min(50, epss * 50)  # higher EPSS without exploit = more surprising
        evidence = min(30, d.get("severity", 0))  # severity validates the signal
        actionability = min(20, 20 if d.get("is_kev") else 10)
        d["hypothesis_score"] = _score_hypothesis(surprise, evidence, actionability)
        d["hypothesis_type"] = "momentum_divergence"
        results.append(d)

    results.sort(key=lambda x: x["hypothesis_score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def compute_all_hypotheses() -> dict:
    """Compute all 4 hypothesis types, score, and cache."""
    started = datetime.now(timezone.utc)

    try:
        unpatched = _compute_unpatched_exposure()
        logger.info(f"Computed {len(unpatched):,} unpatched exposure hypotheses")
        _cache_json("hypothesis_unpatched_exposure", unpatched)

        chains = _compute_chain_gaps()
        logger.info(f"Computed {len(chains):,} chain gap hypotheses")
        _cache_json("hypothesis_chain_gaps", chains)

        vendors = _compute_vendor_anomalies()
        logger.info(f"Computed {len(vendors):,} vendor anomaly hypotheses")
        _cache_json("hypothesis_vendor_anomalies", vendors)

        momentum = _compute_momentum_divergences()
        logger.info(f"Computed {len(momentum):,} momentum divergence hypotheses")
        _cache_json("hypothesis_momentum_divergences", momentum)

        total = len(unpatched) + len(chains) + len(vendors) + len(momentum)
        _log_sync(started, total, "success")

        return {
            "unpatched_exposure": len(unpatched),
            "chain_gaps": len(chains),
            "vendor_anomalies": len(vendors),
            "momentum_divergences": len(momentum),
            "total": total,
        }

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.exception(f"Hypothesis computation failed: {error_msg}")
        _log_sync(started, 0, "failed", error_msg)
        raise
