"""Materialized view refresh — dependency-ordered refresh with snapshot capture."""

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.models import SyncLog

logger = logging.getLogger(__name__)

# Views in dependency order — entity scores first, aggregates last
# Refresh in dependency order: pre-computed layers first, then scoring,
# then downstream aggregates. Each refresh is a separate transaction so
# the DB gets breathing room between queries.
VIEWS_IN_ORDER = [
    # Layer 1+2: pre-compute expensive aggregations (lightweight)
    "mv_cve_software_counts",
    "mv_cve_exploit_flags",
    # Layer 3: CVE scoring (reads from layers 1+2, no inline aggregation)
    "mv_cve_scores",
    # Layer 3b: Product scoring (reads from exploit flags + base tables)
    "mv_product_scores",
    # Downstream: aggregate from mv_cve_scores
    "mv_software_scores",
    "mv_vendor_scores",
    "mv_weakness_scores",
    "mv_technique_scores",
    "mv_pattern_scores",
    "mv_entity_summary",
]


def refresh_all_views():
    """Refresh all materialized views in dependency order, then snapshot scores."""
    started = datetime.now(timezone.utc)
    refreshed = 0
    errors = []

    with engine.connect() as conn:
        for view_name in VIEWS_IN_ORDER:
            try:
                # Try CONCURRENTLY first (requires unique index)
                conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view_name}"))
                conn.commit()
                refreshed += 1
                logger.info(f"  Refreshed {view_name} (concurrent)")
            except Exception:
                conn.rollback()
                try:
                    conn.execute(text(f"REFRESH MATERIALIZED VIEW {view_name}"))
                    conn.commit()
                    refreshed += 1
                    logger.info(f"  Refreshed {view_name} (non-concurrent)")
                except Exception as e2:
                    conn.rollback()
                    errors.append(f"{view_name}: {e2}")
                    logger.error(f"  Failed to refresh {view_name}: {e2}")

    # Snapshot scores after refresh
    _snapshot_scores()

    # Log sync
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="views",
            status="success" if not errors else "partial",
            records_written=refreshed,
            error_message="; ".join(errors) if errors else None,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    logger.info(f"View refresh complete: {refreshed}/{len(VIEWS_IN_ORDER)} refreshed")


def _snapshot_scores():
    """Capture daily score snapshots from materialized views.

    Snapshot tables still have patch_availability columns (nullable) for
    historical data, but we no longer populate them — that dimension was
    removed in migration 013 because has_fix only covers 0.3% of CVEs.

    For proportion-based entities (vendor, weakness, technique, pattern),
    we map active_threat → severity column and exploit_availability →
    exploitability column in the snapshot table.
    """
    try:
        with engine.connect() as conn:
            # CVE score snapshots (3 dimensions, no patch_availability)
            conn.execute(text("""
                INSERT INTO cve_score_snapshots
                    (cve_id, snapshot_date, composite_score, severity,
                     exploitability, exposure, quality_tier)
                SELECT id, CURRENT_DATE, composite_score, severity,
                       exploitability, exposure, quality_tier
                FROM mv_cve_scores
                ON CONFLICT (cve_id, snapshot_date) DO UPDATE SET
                    composite_score = EXCLUDED.composite_score,
                    severity = EXCLUDED.severity,
                    exploitability = EXCLUDED.exploitability,
                    exposure = EXCLUDED.exposure,
                    quality_tier = EXCLUDED.quality_tier
            """))

            # Software score snapshots (3 dimensions, no patch_availability)
            conn.execute(text("""
                INSERT INTO software_score_snapshots
                    (software_id, snapshot_date, composite_score, severity,
                     exploitability, exposure, quality_tier)
                SELECT id, CURRENT_DATE, composite_score, severity,
                       exploitability, exposure, quality_tier
                FROM mv_software_scores
                ON CONFLICT (software_id, snapshot_date) DO UPDATE SET
                    composite_score = EXCLUDED.composite_score,
                    severity = EXCLUDED.severity,
                    exploitability = EXCLUDED.exploitability,
                    exposure = EXCLUDED.exposure,
                    quality_tier = EXCLUDED.quality_tier
            """))

            # Vendor score snapshots (proportion-based: active_threat → severity, exploit_availability → exploitability)
            conn.execute(text("""
                INSERT INTO vendor_score_snapshots
                    (vendor_id, snapshot_date, composite_score, severity,
                     exploitability, quality_tier)
                SELECT id, CURRENT_DATE, composite_score,
                       active_threat, exploit_availability, quality_tier
                FROM mv_vendor_scores
                ON CONFLICT (vendor_id, snapshot_date) DO UPDATE SET
                    composite_score = EXCLUDED.composite_score,
                    severity = EXCLUDED.severity,
                    exploitability = EXCLUDED.exploitability,
                    quality_tier = EXCLUDED.quality_tier
            """))

            # Weakness score snapshots (proportion-based)
            conn.execute(text("""
                INSERT INTO weakness_score_snapshots
                    (weakness_id, snapshot_date, composite_score, severity,
                     exploitability, quality_tier)
                SELECT id, CURRENT_DATE, composite_score,
                       active_threat, exploit_availability, quality_tier
                FROM mv_weakness_scores
                ON CONFLICT (weakness_id, snapshot_date) DO UPDATE SET
                    composite_score = EXCLUDED.composite_score,
                    severity = EXCLUDED.severity,
                    exploitability = EXCLUDED.exploitability,
                    quality_tier = EXCLUDED.quality_tier
            """))

            # Technique score snapshots (proportion-based)
            conn.execute(text("""
                INSERT INTO technique_score_snapshots
                    (technique_id, snapshot_date, composite_score, severity,
                     exploitability, quality_tier)
                SELECT id, CURRENT_DATE, composite_score,
                       active_threat, exploit_availability, quality_tier
                FROM mv_technique_scores
                ON CONFLICT (technique_id, snapshot_date) DO UPDATE SET
                    composite_score = EXCLUDED.composite_score,
                    severity = EXCLUDED.severity,
                    exploitability = EXCLUDED.exploitability,
                    quality_tier = EXCLUDED.quality_tier
            """))

            # Pattern score snapshots (proportion-based)
            conn.execute(text("""
                INSERT INTO pattern_score_snapshots
                    (pattern_id, snapshot_date, composite_score, severity,
                     exploitability, quality_tier)
                SELECT id, CURRENT_DATE, composite_score,
                       active_threat, exploit_availability, quality_tier
                FROM mv_pattern_scores
                ON CONFLICT (pattern_id, snapshot_date) DO UPDATE SET
                    composite_score = EXCLUDED.composite_score,
                    severity = EXCLUDED.severity,
                    exploitability = EXCLUDED.exploitability,
                    quality_tier = EXCLUDED.quality_tier
            """))

            conn.commit()
            logger.info("  Score snapshots captured")
    except Exception as e:
        logger.error(f"  Score snapshot failed: {e}")
