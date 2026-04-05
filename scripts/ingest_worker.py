"""Background worker: task queue + legacy daily ingest.

Two systems run side by side during migration:

1. Task queue (always running): a scheduler creates tasks in the
   database, a worker loop claims and executes them continuously.
   This handles fetch_readme and enrich_summary (more task types
   will be added as the migration progresses).

2. Legacy daily ingest (06:00 UTC): spawns ingest_all.py as a
   subprocess, which runs all remaining non-migrated jobs via
   runner.py. As task types are ported, jobs are removed from
   runner.py until it is empty and can be deleted.

The task queue runs in a background thread with its own asyncio
event loop. The legacy daily ingest remains synchronous in the
main thread.

Auto-deploy is disabled (render.yaml) so code pushes don't interrupt
running jobs. After each successful ingest, the worker triggers its own
redeploy via the Render API to pick up any code changes from the day.
"""
import asyncio
import logging
import os
import subprocess
import sys
import threading
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
    """Check sync_log to decide if today's ingest should run.

    Logic:
    - Any 'success' entry today → done, don't run
    - 2+ 'partial'/'failed' entries today → gave up, don't run
    - Otherwise → OK to run (allows one retry after a partial)
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
            SELECT
                COUNT(*) FILTER (WHERE status = 'success') AS successes,
                COUNT(*) FILTER (WHERE status IN ('partial', 'failed')) AS attempts
            FROM sync_log
            WHERE sync_type = 'daily_ingest'
              AND started_at::date = CURRENT_DATE
        """)
        row = cur.fetchone()
        successes, attempts = row[0], row[1]
        cur.close()
        conn.close()
        if successes > 0:
            return True
        if attempts >= 2:
            logger.warning(f"Daily ingest attempted {attempts} times today — giving up")
            return True
        return False
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


def _start_task_queue():
    """Start the task queue worker + scheduler in a background thread.

    Runs an asyncio event loop with both coroutines. If the task queue
    crashes, the legacy ingest continues unaffected.
    """
    async def _run():
        from app.queue.worker import worker_loop
        from app.queue.scheduler import scheduler_loop
        await asyncio.gather(
            worker_loop(),
            scheduler_loop(),
        )

    def _thread_target():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run())
        except Exception:
            logger.exception("Task queue thread crashed — will restart on next deploy")

    thread = threading.Thread(target=_thread_target, daemon=True, name="task-queue")
    thread.start()
    logger.info("Task queue started in background thread")


def main_loop():
    logger.info("Ingest worker started (task queue + legacy subprocess mode)")

    # Start the task queue worker + scheduler in background
    _start_task_queue()

    # Self-healing: if today's run hasn't completed, run immediately
    if not today_run_completed():
        logger.info("Today's ingest has not completed — running now")
        run_ingest()

    while True:
        wait = seconds_until_next_run()
        logger.info(
            f"Next legacy ingest in {wait / 3600:.1f}h "
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
