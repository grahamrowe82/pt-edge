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

Auto-deploy is disabled (render.yaml) so code pushes don't interrupt
running jobs. After each successful ingest, the worker triggers its own
redeploy via the Render API to pick up any code changes from the day.
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
SERVICE_ID = "srv-d77c6s14tr6s739h798g"


def seconds_until_next_run() -> float:
    """Return seconds until the next TARGET_HOUR_UTC:00 UTC."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=TARGET_HOUR_UTC, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def today_run_completed() -> bool:
    """Check sync_log for an explicit 'daily_ingest' entry today.

    ingest_all.py writes this entry only after the full pipeline completes.
    No ambiguity about which phase counts as 'done'.
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
            WHERE sync_type = 'daily_ingest'
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
    return result.returncode == 0


def trigger_self_deploy():
    """Trigger a redeploy of this worker to pick up code changes from main."""
    api_key = os.environ.get("RENDER_API_KEY", "")
    if not api_key:
        logger.info("No RENDER_API_KEY — skipping self-deploy")
        return

    import urllib.request
    import json

    url = f"https://api.render.com/v1/services/{SERVICE_ID}/deploys"
    data = json.dumps({"clearCache": "do_not_clear"}).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            logger.info(f"Self-deploy triggered ({resp.status})")
    except Exception as e:
        logger.warning(f"Self-deploy failed (non-fatal): {e}")


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

        success = run_ingest()

        # After a successful run, redeploy to pick up any code changes
        if success:
            trigger_self_deploy()


if __name__ == "__main__":
    main_loop()
