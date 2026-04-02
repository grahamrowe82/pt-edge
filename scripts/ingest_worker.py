"""Background worker for daily ingest — replaces Render cron job.

Render cron jobs have a hard 12-hour timeout that cannot be changed.
This worker runs permanently with no timeout, sleeping until 6 AM UTC
each day before triggering the full ingest pipeline.
"""
import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_worker")

TARGET_HOUR_UTC = 6  # 6:00 AM UTC
HEARTBEAT_INTERVAL = 1800  # log every 30 minutes while sleeping


def seconds_until_next_run() -> float:
    """Return seconds until the next TARGET_HOUR_UTC:00 UTC."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=TARGET_HOUR_UTC, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def main_loop():
    from app.ingest.runner import run_all, acquire_ingest_lock, release_ingest_lock

    logger.info("Ingest worker started")

    while True:
        wait = seconds_until_next_run()
        logger.info(
            f"Next ingest in {wait / 3600:.1f}h "
            f"(at {TARGET_HOUR_UTC:02d}:00 UTC)"
        )

        # Sleep with periodic heartbeat so logs show the worker is alive
        while wait > 0:
            chunk = min(wait, HEARTBEAT_INTERVAL)
            await asyncio.sleep(chunk)
            wait -= chunk
            if wait > 0:
                logger.info(f"Worker alive — {wait / 3600:.1f}h until next run")

        # Acquire advisory lock to prevent concurrent runs
        if not acquire_ingest_lock():
            logger.warning("Another ingest is already running — skipping this run")
            continue

        # Run the full ingest pipeline
        logger.info("Starting daily ingest")
        start = time.time()
        try:
            results = await run_all()
            elapsed = time.time() - start
            errors = [
                k for k, v in results.items()
                if isinstance(v, dict) and "error" in v
            ]
            if errors:
                logger.warning(
                    f"Ingest done with errors ({elapsed:.0f}s): "
                    f"{', '.join(errors)}"
                )
            else:
                logger.info(f"Ingest complete ({elapsed:.0f}s)")
        except Exception:
            elapsed = time.time() - start
            logger.exception(f"Ingest crashed after {elapsed:.0f}s")
        finally:
            release_ingest_lock()


if __name__ == "__main__":
    asyncio.run(main_loop())
