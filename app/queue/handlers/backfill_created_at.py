"""Fetch task: backfill a single repo's created_at from GitHub.

Fine-grained — one GitHub API call per task. At priority 2, these
naturally yield to all higher-priority work. The scheduler creates
them in batches of 1000, capping pending tasks at 500 to avoid
flooding the table.

No delay between requests needed — the resource_budgets table handles
rate limiting at the claim level (4500/hr GitHub budget).
"""
import logging

import httpx
from sqlalchemy import text

from app.db import engine
from app.ingest.budget import ResourceThrottledError
from app.queue.errors import PermanentTaskError
from app.settings import settings

logger = logging.getLogger(__name__)


async def handle_backfill_created_at(task: dict) -> dict:
    """Fetch created_at for a single repo and write to ai_repos.

    subject_id is the ai_repos.id.

    Returns:
        {"status": "updated", "created_at": "..."} on success
        {"status": "not_found"} if repo doesn't exist on GitHub (404)
        {"status": "no_data"} if response has no created_at field

    Raises:
        RuntimeError on 403 (rate limited) or other HTTP errors
    """
    repo_id = int(task["subject_id"])

    # Look up full_name
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT full_name FROM ai_repos WHERE id = :id"
        ), {"id": repo_id}).fetchone()

    if not row:
        return {"status": "repo_not_in_db"}

    full_name = row[0]

    headers = {"Accept": "application/vnd.github+json"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    async with httpx.AsyncClient(headers=headers, timeout=10) as client:
        resp = await client.get(f"https://api.github.com/repos/{full_name}")

    if resp.status_code == 404:
        return {"status": "not_found"}

    if resp.status_code == 403:
        raise ResourceThrottledError(f"GitHub rate limited (403) for {full_name}")

    if resp.status_code in (451, 410):
        raise PermanentTaskError(f"GitHub {resp.status_code} for {full_name}")

    if resp.status_code != 200:
        raise RuntimeError(f"GitHub {resp.status_code} for {full_name}")

    created_at = resp.json().get("created_at")
    if not created_at:
        return {"status": "no_data"}

    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE ai_repos SET created_at = :created_at
            WHERE id = :id AND created_at IS NULL
        """), {"created_at": created_at, "id": repo_id})
        conn.commit()

    return {"status": "updated", "created_at": created_at}
