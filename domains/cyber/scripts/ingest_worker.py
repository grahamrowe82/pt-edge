"""Background worker: task queue scheduler + worker loop.

Runs continuously on Render as a persistent worker service. The scheduler
creates tasks in the database based on staleness, the worker loop claims
and executes them by priority. All task types are handled.

Auto-deploy is disabled (render.yaml) so code pushes don't interrupt
running tasks. The worker triggers its own redeploy via the Render API
periodically to pick up code changes.
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_worker")

SELF_DEPLOY_INTERVAL = 86400  # trigger self-deploy once per day


def trigger_self_deploy():
    """Trigger a redeploy of this worker to pick up code changes from main."""
    api_key = os.environ.get("RENDER_API_KEY", "")
    service_id = os.environ.get("RENDER_SERVICE_ID", "")
    if not api_key or not service_id:
        logger.info("No RENDER_API_KEY or RENDER_SERVICE_ID — skipping self-deploy")
        return

    import json
    import urllib.request

    url = f"https://api.render.com/v1/services/{service_id}/deploys"
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


async def self_deploy_loop():
    """Trigger a self-deploy once per day to pick up code changes."""
    while True:
        await asyncio.sleep(SELF_DEPLOY_INTERVAL)
        try:
            trigger_self_deploy()
        except Exception as e:
            logger.warning(f"Self-deploy loop error: {e}")


async def main():
    from domains.cyber.app.queue.worker import worker_loop
    from domains.cyber.app.queue.scheduler import scheduler_loop

    logger.info("Task queue worker starting (all jobs via task queue)")

    await asyncio.gather(
        worker_loop(),
        scheduler_loop(),
        self_deploy_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())
