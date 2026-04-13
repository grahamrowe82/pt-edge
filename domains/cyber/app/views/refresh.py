"""Materialized view refresh — dependency-ordered refresh with snapshot capture."""

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.models import SyncLog

logger = logging.getLogger(__name__)

# Views in dependency order — entity scores first, aggregates last
VIEWS_IN_ORDER = [
    "mv_cve_scores",
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
    """Capture daily score snapshots from materialized views."""
    try:
        with engine.connect() as conn:
            # CVE score snapshots
            conn.execute(text("""
                INSERT INTO cve_score_snapshots
                    (cve_id, snapshot_date, composite_score, severity,
                     exploitability, exposure, patch_availability, quality_tier)
                SELECT id, CURRENT_DATE, composite_score, severity,
                       exploitability, exposure, patch_availability, quality_tier
                FROM mv_cve_scores
                ON CONFLICT (cve_id, snapshot_date) DO UPDATE SET
                    composite_score = EXCLUDED.composite_score,
                    severity = EXCLUDED.severity,
                    exploitability = EXCLUDED.exploitability,
                    exposure = EXCLUDED.exposure,
                    patch_availability = EXCLUDED.patch_availability,
                    quality_tier = EXCLUDED.quality_tier
            """))

            # Software score snapshots
            conn.execute(text("""
                INSERT INTO software_score_snapshots
                    (software_id, snapshot_date, composite_score, severity,
                     exploitability, exposure, patch_availability, quality_tier)
                SELECT id, CURRENT_DATE, composite_score, severity,
                       exploitability, exposure, patch_availability, quality_tier
                FROM mv_software_scores
                ON CONFLICT (software_id, snapshot_date) DO UPDATE SET
                    composite_score = EXCLUDED.composite_score,
                    severity = EXCLUDED.severity,
                    exploitability = EXCLUDED.exploitability,
                    exposure = EXCLUDED.exposure,
                    patch_availability = EXCLUDED.patch_availability,
                    quality_tier = EXCLUDED.quality_tier
            """))

            # Vendor score snapshots
            conn.execute(text("""
                INSERT INTO vendor_score_snapshots
                    (vendor_id, snapshot_date, composite_score, severity,
                     exploitability, exposure, patch_availability, quality_tier)
                SELECT id, CURRENT_DATE, composite_score, severity,
                       exploitability, exposure, patch_availability, quality_tier
                FROM mv_vendor_scores
                ON CONFLICT (vendor_id, snapshot_date) DO UPDATE SET
                    composite_score = EXCLUDED.composite_score,
                    severity = EXCLUDED.severity,
                    exploitability = EXCLUDED.exploitability,
                    exposure = EXCLUDED.exposure,
                    patch_availability = EXCLUDED.patch_availability,
                    quality_tier = EXCLUDED.quality_tier
            """))

            # Weakness score snapshots
            conn.execute(text("""
                INSERT INTO weakness_score_snapshots
                    (weakness_id, snapshot_date, composite_score, severity,
                     exploitability, exposure, patch_availability, quality_tier)
                SELECT id, CURRENT_DATE, composite_score, severity,
                       exploitability, exposure, patch_availability, quality_tier
                FROM mv_weakness_scores
                ON CONFLICT (weakness_id, snapshot_date) DO UPDATE SET
                    composite_score = EXCLUDED.composite_score,
                    severity = EXCLUDED.severity,
                    exploitability = EXCLUDED.exploitability,
                    exposure = EXCLUDED.exposure,
                    patch_availability = EXCLUDED.patch_availability,
                    quality_tier = EXCLUDED.quality_tier
            """))

            # Technique score snapshots
            conn.execute(text("""
                INSERT INTO technique_score_snapshots
                    (technique_id, snapshot_date, composite_score, severity,
                     exploitability, exposure, patch_availability, quality_tier)
                SELECT id, CURRENT_DATE, composite_score, severity,
                       exploitability, exposure, patch_availability, quality_tier
                FROM mv_technique_scores
                ON CONFLICT (technique_id, snapshot_date) DO UPDATE SET
                    composite_score = EXCLUDED.composite_score,
                    severity = EXCLUDED.severity,
                    exploitability = EXCLUDED.exploitability,
                    exposure = EXCLUDED.exposure,
                    patch_availability = EXCLUDED.patch_availability,
                    quality_tier = EXCLUDED.quality_tier
            """))

            # Pattern score snapshots
            conn.execute(text("""
                INSERT INTO pattern_score_snapshots
                    (pattern_id, snapshot_date, composite_score, severity,
                     exploitability, exposure, patch_availability, quality_tier)
                SELECT id, CURRENT_DATE, composite_score, severity,
                       exploitability, exposure, patch_availability, quality_tier
                FROM mv_pattern_scores
                ON CONFLICT (pattern_id, snapshot_date) DO UPDATE SET
                    composite_score = EXCLUDED.composite_score,
                    severity = EXCLUDED.severity,
                    exploitability = EXCLUDED.exploitability,
                    exposure = EXCLUDED.exposure,
                    patch_availability = EXCLUDED.patch_availability,
                    quality_tier = EXCLUDED.quality_tier
            """))

            conn.commit()
            logger.info("  Score snapshots captured")
    except Exception as e:
        logger.error(f"  Score snapshot failed: {e}")
