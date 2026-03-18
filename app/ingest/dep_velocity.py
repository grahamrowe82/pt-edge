"""Snapshot reverse-dependency counts for velocity tracking.

Captures how many repos depend on each package (≥3 dependents),
enabling week-over-week delta computation.

Run standalone:  python -m app.ingest.dep_velocity
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import SyncLog

logger = logging.getLogger(__name__)


async def snapshot_dep_counts() -> dict:
    """Insert today's reverse-dependency counts into dep_velocity_snapshots."""
    started_at = datetime.now(timezone.utc)

    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO dep_velocity_snapshots (dep_name, source, dependent_count, snapshot_date)
            SELECT dep_name, source, COUNT(DISTINCT repo_id), CURRENT_DATE
            FROM package_deps
            GROUP BY dep_name, source
            HAVING COUNT(DISTINCT repo_id) >= 3
            ON CONFLICT (dep_name, source, snapshot_date) DO UPDATE
            SET dependent_count = EXCLUDED.dependent_count
        """))
        count = result.rowcount
        conn.commit()

    _log_sync(started_at, count, None)
    logger.info(f"dep_velocity snapshot: {count} packages recorded")
    return {"snapshots": count}


def _log_sync(started_at: datetime, records: int, error: str | None) -> None:
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="dep_velocity",
            status="success" if not error else "partial",
            records_written=records,
            error_message=error,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()


async def main():
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = await snapshot_dep_counts()
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
