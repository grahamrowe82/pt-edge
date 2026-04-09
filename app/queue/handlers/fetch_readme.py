"""Fetch task: download a README from GitHub and store it in raw_cache.

Pure fetch — no LLM calls, no enrichment, no processing. The only job
is to get the raw README text into the database so enrich tasks can
read it later.

Also updates ai_repos.readme_cache for backwards compatibility during
the migration period.
"""
import logging

from sqlalchemy import text

from app.db import engine
from app.github_client import GitHubRateLimitError, get_github_client
from app.queue.errors import PermanentTaskError

logger = logging.getLogger(__name__)

README_MAX_CHARS = 8000
MIN_README_LENGTH = 100


def _upsert_raw_cache(source: str, subject_id: str, payload: str | None) -> None:
    """Write a raw API response to the cache."""
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO raw_cache (source, subject_id, fetched_at, payload)
            VALUES (:source, :subject_id, now(), :payload)
            ON CONFLICT (source, subject_id)
            DO UPDATE SET fetched_at = now(), payload = EXCLUDED.payload
        """), {"source": source, "subject_id": subject_id, "payload": payload})
        conn.commit()


async def handle_fetch_readme(task: dict) -> dict:
    """Fetch README from GitHub, store in raw_cache.

    Returns:
        {"status": "cached", "length": N} on success
        {"status": "no_readme"} if repo has no README (404)
        {"status": "too_short"} if README is under MIN_README_LENGTH

    Raises:
        GitHubRateLimitError on rate limit (triggers requeue via worker)
        PermanentTaskError on 451/410 (DMCA, gone)
        PermanentTaskError on access-denied 403 (private repo)
        RuntimeError on other HTTP errors (triggers retry)
    """
    full_name = task["subject_id"]
    gh = get_github_client()

    resp = await gh.get(
        f"/repos/{full_name}/readme",
        caller="handler.fetch_readme",
        accept="application/vnd.github.raw+json",
    )

    if resp.status_code == 404:
        _upsert_raw_cache("github_readme", full_name, None)
        return {"status": "no_readme"}

    if resp.status_code == 403:
        kind = gh.classify_403(resp)
        if kind == "rate_limit":
            raise GitHubRateLimitError(gh._core_reset)
        elif kind == "secondary_rate_limit":
            raise GitHubRateLimitError(gh._core_reset)
        else:
            # Access denied — private repo, DMCA, etc. Don't retry.
            raise PermanentTaskError(f"GitHub 403 access denied for {full_name}")

    if resp.status_code in (451, 410):
        raise PermanentTaskError(f"GitHub {resp.status_code} for {full_name}")

    if resp.status_code != 200:
        raise RuntimeError(f"GitHub {resp.status_code} for {full_name}")

    readme_text = resp.text[:README_MAX_CHARS]
    if len(readme_text) < MIN_README_LENGTH:
        _upsert_raw_cache("github_readme", full_name, None)
        return {"status": "too_short", "length": len(readme_text)}

    # Store in raw_cache (the canonical location)
    _upsert_raw_cache("github_readme", full_name, readme_text)

    # Also update ai_repos.readme_cache for backwards compatibility
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE ai_repos
            SET readme_cache = :readme, readme_cached_at = now()
            WHERE full_name = :fn
        """), {"readme": readme_text, "fn": full_name})
        conn.commit()

    return {"status": "cached", "length": len(readme_text)}
