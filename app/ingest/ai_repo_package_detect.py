"""LLM-assisted package detection for ai_repos.

For repos where syntactic name matching (dash/underscore variants) fails,
use an LLM to predict the likely PyPI/npm/crate package name, then verify
against the registry before saving.

Examples the LLM catches that regex can't:
  pytorch → torch (semantic rename)
  chroma  → chromadb (name extension)
  tokenizers → tokenizers (Rust repo with Python bindings, blocked by language gate)

Idempotent: only processes repos where all package columns are NULL and
downloads_checked_at is set (i.e., syntactic detection already ran and failed).

Run standalone:  python -m app.ingest.ai_repo_package_detect [limit]
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.ingest.ai_repo_downloads import (
    _batch_update,
    _pypi_matches_repo,
    _npm_matches_repo,
    _crate_matches_repo,
)
from app.ingest.downloads import (
    fetch_pypi_downloads,
    fetch_npm_downloads,
    fetch_crate_downloads,
)
from app.ingest.rate_limit import ANTHROPIC_LIMITER
from app.models import SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 20
MIN_STARS = 100

DETECT_PROMPT = """\
You are a package registry expert. Given a list of GitHub repos, predict the \
most likely published package name on PyPI, npm, or crates.io for each.

Rules:
- Only predict a package if you are confident it exists on that registry.
- If the repo is NOT a published package (tutorial, demo, web app, Docker-only \
platform, curated list, educational content, desktop app), return null for all.
- The package name often differs from the repo name (e.g., pytorch → torch, \
chroma → chromadb, opencv → opencv-python).
- A Rust repo can also have a Python package (e.g., tokenizers, pydantic-core).
- Return valid JSON only — an array of objects.

Return format:
[{{"id": <repo_id>, "pypi": "<name or null>", "npm": "<name or null>", "crate": "<name or null>"}}, ...]

Repos:
{repos_text}"""


async def _call_llm(repos_text: str) -> list[dict] | None:
    """Call Anthropic to predict package names for a batch of repos."""
    prompt = DETECT_PROMPT.format(repos_text=repos_text)

    for attempt in range(3):
        await ANTHROPIC_LIMITER.acquire()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 2048,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
        except httpx.HTTPError as e:
            logger.warning(f"LLM HTTP error (attempt {attempt + 1}/3): {e}")
            await asyncio.sleep(2 ** attempt * 5)
            continue

        if resp.status_code == 429:
            wait = min(2 ** attempt * 15, 120)
            logger.warning(f"Anthropic 429, backing off {wait}s (attempt {attempt + 1}/3)")
            await asyncio.sleep(wait)
            continue

        if resp.status_code != 200:
            logger.warning(f"Anthropic API {resp.status_code}: {resp.text[:200]}")
            return None

        try:
            data = resp.json()
            text_content = data.get("content", [{}])[0].get("text", "").strip()
            # Extract JSON from response (may have markdown fences)
            if "```" in text_content:
                text_content = text_content.split("```")[1]
                if text_content.startswith("json"):
                    text_content = text_content[4:]
            return json.loads(text_content)
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return None

    return None


async def _verify_and_fetch(
    client: httpx.AsyncClient,
    prediction: dict,
    owner: str,
    repo: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str | None, str | None, str | None, int]:
    """Verify LLM prediction against registries and fetch downloads.

    Returns (pypi_pkg, npm_pkg, crate_pkg, downloads_monthly).
    """
    pypi_pkg = None
    npm_pkg = None
    crate_pkg = None
    dl_monthly = 0

    # Verify PyPI prediction
    predicted_pypi = prediction.get("pypi")
    if predicted_pypi:
        async with semaphore:
            try:
                resp = await client.get(f"https://pypi.org/pypi/{predicted_pypi}/json")
                await asyncio.sleep(0.5)
                if resp.status_code == 200:
                    data = resp.json()
                    if _pypi_matches_repo(data, owner, repo):
                        pypi_pkg = predicted_pypi
                        stats = await fetch_pypi_downloads(client, pypi_pkg)
                        if stats:
                            dl_monthly += stats["last_month"]
                    else:
                        logger.debug(
                            f"PyPI {predicted_pypi} exists but doesn't link to {owner}/{repo}"
                        )
            except httpx.HTTPError:
                pass

    # Verify npm prediction
    predicted_npm = prediction.get("npm")
    if predicted_npm:
        async with semaphore:
            try:
                resp = await client.get(f"https://registry.npmjs.org/{predicted_npm}")
                await asyncio.sleep(0.3)
                if resp.status_code == 200:
                    data = resp.json()
                    if _npm_matches_repo(data, owner, repo):
                        npm_pkg = predicted_npm
                        stats = await fetch_npm_downloads(client, npm_pkg)
                        if stats:
                            dl_monthly += stats["last_month"]
                    else:
                        logger.debug(
                            f"npm {predicted_npm} exists but doesn't link to {owner}/{repo}"
                        )
            except httpx.HTTPError:
                pass

    # Verify crate prediction
    predicted_crate = prediction.get("crate")
    if predicted_crate:
        async with semaphore:
            try:
                resp = await client.get(
                    f"https://crates.io/api/v1/crates/{predicted_crate}",
                    headers={"User-Agent": "pt-edge/1.0 (https://github.com/pt-edge)"},
                )
                await asyncio.sleep(1.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if _crate_matches_repo(data, owner, repo):
                        crate_pkg = predicted_crate
                        stats = await fetch_crate_downloads(client, crate_pkg)
                        if stats:
                            dl_monthly += stats["last_month"]
                    else:
                        logger.debug(
                            f"crate {predicted_crate} exists but doesn't link to {owner}/{repo}"
                        )
            except httpx.HTTPError:
                pass

    return pypi_pkg, npm_pkg, crate_pkg, dl_monthly


async def detect_packages_llm(limit: int = 500) -> dict:
    """Use LLM to detect package names for repos that syntactic detection missed."""
    if not settings.ANTHROPIC_API_KEY:
        logger.info("No ANTHROPIC_API_KEY — skipping LLM package detection")
        return {"predicted": 0, "verified": 0, "skipped": "no API key"}

    started_at = datetime.now(timezone.utc)

    # Fetch repos that were checked but found no match
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, name, github_owner, github_repo, language,
                   LEFT(description, 150) AS description
            FROM ai_repos
            WHERE downloads_checked_at IS NOT NULL
              AND pypi_package IS NULL
              AND npm_package IS NULL
              AND crate_package IS NULL
              AND stars >= :min_stars
            ORDER BY stars DESC
            LIMIT :lim
        """), {"min_stars": MIN_STARS, "lim": limit}).fetchall()

    if not rows:
        logger.info("No unchecked repos to process with LLM")
        return {"predicted": 0, "verified": 0}

    logger.info(f"LLM package detection: processing {len(rows)} repos (stars >= {MIN_STARS})")

    # Build batches
    batches = []
    for i in range(0, len(rows), BATCH_SIZE):
        batches.append(rows[i : i + BATCH_SIZE])

    # Build a lookup from id → (owner, repo)
    repo_lookup: dict[int, tuple[str, str]] = {}
    for r in rows:
        m = r._mapping
        repo_lookup[m["id"]] = (m["github_owner"], m["github_repo"])

    total_predicted = 0
    total_verified = 0
    all_updates: list[tuple] = []
    errors = 0

    registry_sem = asyncio.Semaphore(3)

    async with httpx.AsyncClient(
        headers={"User-Agent": "pt-edge/1.0"}, timeout=30.0
    ) as client:

        for batch_idx, batch in enumerate(batches):
            # Build prompt text
            lines = []
            for r in batch:
                m = r._mapping
                desc = (m["description"] or "").replace("\n", " ").strip()
                lines.append(
                    f'{m["id"]}. {m["github_owner"]}/{m["github_repo"]} '
                    f'({m["language"] or "unknown"}) — "{desc}"'
                )
            repos_text = "\n".join(lines)

            # Call LLM
            predictions = await _call_llm(repos_text)
            if not predictions:
                logger.warning(f"Batch {batch_idx + 1}/{len(batches)}: LLM returned no results")
                errors += 1
                continue

            # Count predictions (non-null package names)
            batch_predicted = sum(
                1 for p in predictions
                if p.get("pypi") or p.get("npm") or p.get("crate")
            )
            total_predicted += batch_predicted

            # Verify each prediction against registries
            for pred in predictions:
                rid = pred.get("id")
                if not rid or rid not in repo_lookup:
                    continue
                if not (pred.get("pypi") or pred.get("npm") or pred.get("crate")):
                    continue  # LLM said no package — skip

                owner, repo = repo_lookup[rid]
                pypi_pkg, npm_pkg, crate_pkg, dl_monthly = await _verify_and_fetch(
                    client, pred, owner, repo, registry_sem
                )

                if pypi_pkg or npm_pkg or crate_pkg:
                    all_updates.append((rid, pypi_pkg, npm_pkg, crate_pkg, dl_monthly))
                    total_verified += 1
                    logger.info(
                        f"  {owner}/{repo} → pypi={pypi_pkg} npm={npm_pkg} "
                        f"crate={crate_pkg} dl={dl_monthly:,}/mo"
                    )

            logger.info(
                f"Batch {batch_idx + 1}/{len(batches)}: "
                f"{batch_predicted} predicted, {total_verified} verified so far"
            )

    # Batch write all verified detections
    if all_updates:
        written = _batch_update(all_updates)
        logger.info(f"LLM detection: wrote {written} package matches to DB")
    else:
        written = 0

    # Sync log
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="ai_repo_package_detect",
            status="success" if not errors else "partial",
            records_written=written,
            error_message=f"{errors} LLM errors" if errors else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    result = {"predicted": total_predicted, "verified": total_verified, "written": written, "errors": errors}
    logger.info(f"LLM package detection complete: {result}")
    return result


async def main():
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    result = await detect_packages_llm(limit=lim)
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
