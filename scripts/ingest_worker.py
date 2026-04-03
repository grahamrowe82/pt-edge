"""Background scheduler for daily ingest — replaces Render cron job.

Render cron jobs have a hard 12-hour timeout that cannot be changed.
This worker runs permanently with no timeout, sleeping until 6 AM UTC
each day before spawning ingest_all.py as a subprocess.

The subprocess gets a clean process with fresh memory, replicating the
cron's process-per-run semantics while removing the timeout constraint.

On startup, checks whether today's run has already completed. If not,
runs immediately before entering the normal sleep loop. This makes the
worker self-healing after crashes and allows manual triggering via a
service restart.
"""
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_worker")

TARGET_HOUR_UTC = 6  # 6:00 AM UTC
HEARTBEAT_INTERVAL = 1800  # log every 30 minutes while sleeping
SCRIPT = str(Path(__file__).parent / "ingest_all.py")


def seconds_until_next_run() -> float:
    """Return seconds until the next TARGET_HOUR_UTC:00 UTC."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=TARGET_HOUR_UTC, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def today_run_completed() -> bool:
    """Check sync_log for a successful views refresh today (late-stage phase).

    Checking 'github' (the first phase) is wrong — a crashed run may have
    completed early phases before OOM. 'views' only runs near the end,
    so its presence means the pipeline got most of the way through.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        logger.warning("No DATABASE_URL — cannot check sync_log, skipping")
        return True  # assume done to avoid accidental runs

    import psycopg2
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM sync_log
            WHERE sync_type = 'views'
              AND status IN ('success', 'partial')
              AND started_at::date = CURRENT_DATE
        """)
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count > 0
    except Exception as e:
        logger.warning(f"Could not check sync_log: {e}")
        return True  # assume done to avoid accidental runs


def run_ingest():
    """Spawn ingest_all.py as a subprocess and log the result."""
    logger.info("Spawning ingest_all.py")
    start = time.time()
    result = subprocess.run(
        [sys.executable, SCRIPT],
        timeout=None,  # no timeout — that's the whole point
    )
    elapsed = time.time() - start

    if result.returncode == 0:
        logger.info(f"Ingest complete ({elapsed:.0f}s)")
    else:
        logger.error(
            f"Ingest failed with exit code {result.returncode} ({elapsed:.0f}s)"
        )


def main_loop():
    logger.info("Ingest worker started (subprocess mode)")

    # Self-healing: if today's run hasn't completed, run immediately
    if not today_run_completed():
        logger.info("Today's ingest has not completed — running now")
        run_ingest()

    while True:
        wait = seconds_until_next_run()
        logger.info(
            f"Next ingest in {wait / 3600:.1f}h "
            f"(at {TARGET_HOUR_UTC:02d}:00 UTC)"
        )

        # Sleep with periodic heartbeat so logs show the worker is alive
        while wait > 0:
            chunk = min(wait, HEARTBEAT_INTERVAL)
            time.sleep(chunk)
            wait -= chunk
            if wait > 0:
                logger.info(f"Worker alive — {wait / 3600:.1f}h until next run")

        run_ingest()


if __name__ == "__main__":
    main_loop()
