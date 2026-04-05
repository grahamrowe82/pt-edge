"""Export task: trigger static site rebuild via Render deploy hook.

Pure export — reads nothing, POSTs to the Render deploy webhook URL.
The web service regenerates all 18 domain sites on startup.
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)


async def handle_export_static_site(task: dict) -> dict:
    """Trigger a static site rebuild via the Render deploy hook.

    subject_id is unused.

    Returns:
        {"status": "deploy_triggered", "code": N} on success
        {"status": "skipped"} if no RENDER_DEPLOY_HOOK_URL configured

    Raises:
        RuntimeError on HTTP failure
    """
    deploy_hook = os.environ.get("RENDER_DEPLOY_HOOK_URL")
    if not deploy_hook:
        return {"status": "skipped", "reason": "no RENDER_DEPLOY_HOOK_URL"}

    resp = httpx.post(deploy_hook, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Deploy hook returned {resp.status_code}")

    return {"status": "deploy_triggered", "code": resp.status_code}
