"""Background scheduler for daily ingest — replaces Render cron job.

Render cron jobs have a hard 12-hour timeout that cannot be changed.
This worker runs permanently with no timeout, sleeping until 6 AM UTC
each day before spawning ingest_all.py as a subprocess.

The subprocess gets a clean process with fresh memory, replicating the
cron's process-per-run semantics while removing the timeout constraint.
"""
import logging
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


def main_loop():
    logger.info("Ingest worker started (subprocess mode)")

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

        # Spawn ingest as a clean subprocess
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


if __name__ == "__main__":
    main_loop()
