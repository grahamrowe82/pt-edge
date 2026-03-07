import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine
from app.db import SessionLocal
from app.models import SyncLog

logger = logging.getLogger(__name__)

VIEWS_IN_ORDER = [
    "mv_momentum",
    "mv_hype_ratio",
    "mv_lab_velocity",
    "mv_project_summary",  # depends on all above
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
