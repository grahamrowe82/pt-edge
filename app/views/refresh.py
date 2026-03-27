import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine
from app.db import SessionLocal
from app.models import SyncLog

logger = logging.getLogger(__name__)

VIEWS_IN_ORDER = [
    "mv_momentum",             # base: no dependencies
    "mv_hype_ratio",           # base: no dependencies
    "mv_lab_velocity",         # base: no dependencies
    "mv_project_tier",         # base: no dependencies
    "mv_velocity",             # base: no dependencies
    "mv_download_trends",      # base: no MV dependencies (uses download_snapshots)
    "mv_lifecycle",            # depends on: mv_momentum
    "mv_traction_score",       # depends on: mv_velocity, mv_download_trends
    "mv_project_summary",      # depends on: mv_momentum, mv_hype_ratio, mv_project_tier, mv_velocity, mv_lifecycle, mv_traction_score, mv_download_trends
    "mv_usage_sessions",       # standalone: tool_usage only
    "mv_usage_daily_summary",  # depends on: mv_usage_sessions
    "mv_ai_repo_ecosystem",    # standalone: ai_repos stats by domain+subcategory
]


def refresh_all_views():
    """Refresh all materialized views in dependency order."""
    started_at = datetime.now(timezone.utc)
    refreshed = 0
    errors = []

    with engine.connect() as conn:
        for view_name in VIEWS_IN_ORDER:
            try:
                conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view_name}"))
                conn.commit()
                refreshed += 1
                logger.info(f"Refreshed {view_name}")
            except Exception as e:
                # CONCURRENTLY requires unique index; fall back to regular refresh
                conn.rollback()
                try:
                    conn.execute(text(f"REFRESH MATERIALIZED VIEW {view_name}"))
                    conn.commit()
                    refreshed += 1
                    logger.info(f"Refreshed {view_name} (non-concurrent)")
                except Exception as e2:
                    conn.rollback()
                    errors.append(f"{view_name}: {e2}")
                    logger.error(f"Failed to refresh {view_name}: {e2}")

    # Snapshot lifecycle stages for transition tracking
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO lifecycle_history (project_id, lifecycle_stage, snapshot_date)
                SELECT project_id, lifecycle_stage, CURRENT_DATE
                FROM mv_lifecycle
                ON CONFLICT (project_id, snapshot_date) DO UPDATE
                SET lifecycle_stage = EXCLUDED.lifecycle_stage
            """))
            conn.commit()
            logger.info("Snapshotted lifecycle stages to lifecycle_history")
    except Exception as e:
        logger.warning(f"Could not snapshot lifecycle stages: {e}")

    # Log sync
    session = SessionLocal()
    try:
        log = SyncLog(
            sync_type="views",
            status="success" if not errors else "partial",
            records_written=refreshed,
            error_message="; ".join(errors) if errors else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        session.add(log)
        session.commit()
    finally:
        session.close()

    return {"refreshed": refreshed, "errors": errors}
