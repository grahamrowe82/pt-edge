"""Fetch task: backfill a single repo's created_at from GitHub.

Fine-grained — one GitHub API call per task. At priority 2, these
naturally yield to all higher-priority work. The scheduler creates
them in batches of 1000, capping pending tasks at 500 to avoid
flooding the table.
"""
import logging

from sqlalchemy import text

from app.db import engine
from app.github_client import GitHubRateLimitError, get_github_client
from app.queue.errors import PermanentTaskError

logger = logging.getLogger(__name__)


async def handle_backfill_created_at(task: dict) -> dict:
    """Fetch created_at for a single repo and write to ai_repos.

    subject_id is the ai_repos.id.

    Returns:
        {"status": "updated", "created_at": "..."} on success
        {"status": "not_found"} if repo doesn't exist on GitHub (404)
        {"status": "no_data"} if response has no created_at field

    Raises:
        GitHubRateLimitError on rate limit (triggers requeue via worker)
        PermanentTaskError on 451/410 or access-denied 403
        RuntimeError on other HTTP errors (triggers retry)
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
    gh = get_github_client()

    resp = await gh.get(f"/repos/{full_name}", caller="handler.backfill_created_at")

    if resp.status_code == 404:
        return {"status": "not_found"}

    if resp.status_code == 403:
        kind = gh.classify_403(resp)
        if kind == "rate_limit":
            raise GitHubRateLimitError(gh._core_reset)
        elif kind == "secondary_rate_limit":
            raise GitHubRateLimitError(gh._core_reset)
        else:
            raise PermanentTaskError(f"GitHub 403 access denied for {full_name}")

    if resp.status_code in (451, 410):
        raise PermanentTaskError(f"GitHub {resp.status_code} for {full_name}")

    if resp.status_code != 200:
        raise RuntimeError(f"GitHub {resp.status_code} for {full_name}")

    data = resp.json()
    created_at = data.get("created_at")
    if not created_at:
        return {"status": "no_data"}

    # Detect renames: if GitHub's canonical full_name differs from ours,
    # update ai_repos and raw_cache so downstream handlers use the new name.
    api_full_name = data.get("full_name", "")
    renamed = False
    if api_full_name and api_full_name.lower() != full_name.lower():
        logger.info(f"Repo renamed: {full_name} → {api_full_name}")
        new_owner, new_repo = api_full_name.split("/", 1)
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE ai_repos
                SET full_name = :new_name,
                    github_owner = :new_owner,
                    github_repo = :new_repo
                WHERE id = :id
            """), {
                "new_name": api_full_name,
                "new_owner": new_owner,
                "new_repo": new_repo,
                "id": repo_id,
            })
            conn.execute(text("""
                UPDATE raw_cache SET subject_id = :new_name
                WHERE source = 'github_readme' AND subject_id = :old_name
            """), {"new_name": api_full_name, "old_name": full_name})
            conn.commit()
        renamed = True

    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE ai_repos SET created_at = :created_at
            WHERE id = :id AND created_at IS NULL
        """), {"created_at": created_at, "id": repo_id})
        conn.commit()

    result = {"status": "updated", "created_at": created_at}
    if renamed:
        result["renamed_to"] = api_full_name
    return result
