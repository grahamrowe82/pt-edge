"""Generate AI summaries for ai_repos by fetching README + calling Haiku.

Produces a 2-3 sentence qualitative description of what the project does,
its key features, and what it integrates with. The summary is stored in
ai_repos.ai_summary and displayed on directory pages alongside live metrics.

Processes repos in descending quality_score order. Skips repos with empty
or unhelpful READMEs.

Run standalone:  python -m app.ingest.ai_repo_summaries [--limit 200] [--min-score 30]
"""
import asyncio
import argparse
import logging
import sys
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine
from app.ingest.llm import call_haiku_text
from app.settings import settings

logger = logging.getLogger(__name__)

MAX_PER_RUN = 2000
MIN_QUALITY_SCORE = 30
README_MAX_CHARS = 8000
MIN_README_LENGTH = 100  # skip READMEs shorter than this

SUMMARY_PROMPT = """\
You are writing a technical summary of an open-source project for a developer directory.

The project's one-line GitHub description is already shown on the page:
"{description}"

Your job is to go DEEPER than that description. From the README, write 2-3 sentences covering:
- Key features or capabilities the description doesn't mention
- How it works — the architecture, approach, or key technology choices
- What it integrates with, or what ecosystem/framework it targets

Rules:
- Do NOT repeat or paraphrase the GitHub description — it's already visible
- Be specific and technical ("uses stdio transport with automatic reconnection") not vague ("easy to use")
- Don't mention stars, downloads, or popularity — those are shown separately
- Don't start with "This project..." or the project name — start with the substance
- Maximum 3 sentences, ~50-80 words total

Project: {full_name}
GitHub description: {description}

README (truncated):
{readme_text}"""


def _github_headers():
    headers = {"Accept": "application/vnd.github.raw+json"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"token {settings.GITHUB_TOKEN}"
    return headers


_readme_rate_limited = False


async def fetch_readme(client: httpx.AsyncClient, full_name: str) -> str | None:
    """Fetch raw README text from GitHub. Returns truncated text or None."""
    global _readme_rate_limited
    if _readme_rate_limited:
        return None
    try:
        resp = await client.get(
            f"https://api.github.com/repos/{full_name}/readme",
            headers=_github_headers(),
        )
        if resp.status_code == 200:
            text = resp.text[:README_MAX_CHARS]
            if len(text) < MIN_README_LENGTH:
                return None
            return text
        if resp.status_code == 404:
            return None
        if resp.status_code == 403:
            _readme_rate_limited = True
            logger.error(f"GitHub 403 for README {full_name} — aborting remaining fetches")
            return None
        logger.warning(f"GitHub README {resp.status_code} for {full_name}")
        return None
    except httpx.HTTPError as e:
        logger.warning(f"GitHub README fetch error for {full_name}: {e}")
        return None


def _find_candidates(limit: int, min_score: int):
    """Find repos needing summaries, prioritised by allocation budget."""
    with engine.connect() as conn:
        # Check if allocation budget is available
        has_budget = conn.execute(text(
            "SELECT 1 FROM content_budget WHERE pipeline = 'ai_repo_summaries' LIMIT 1"
        )).fetchone()

        if has_budget:
            rows = conn.execute(text("""
                WITH budget AS (
                    SELECT domain, subcategory, row_limit
                    FROM content_budget
                    WHERE pipeline = 'ai_repo_summaries'
                ),
                ranked AS (
                    SELECT ar.id, ar.full_name, ar.description,
                           ar.domain, ar.subcategory,
                           ROW_NUMBER() OVER (
                               PARTITION BY ar.domain, ar.subcategory
                               ORDER BY ar.stars DESC NULLS LAST
                           ) AS rn
                    FROM ai_repos ar
                    JOIN budget b ON ar.domain = b.domain
                                 AND ar.subcategory = b.subcategory
                    WHERE ar.ai_summary IS NULL
                      AND ar.description IS NOT NULL
                      AND ar.description <> ''
                )
                SELECT r.id, r.full_name, r.description
                FROM ranked r
                JOIN budget b ON r.domain = b.domain
                             AND r.subcategory = b.subcategory
                WHERE r.rn <= b.row_limit
            """)).fetchall()
            logger.info(f"Budget-driven: {len(rows)} candidates from content_budget")
        else:
            # Fallback: original behaviour
            rows = conn.execute(text("""
                SELECT ar.id, ar.full_name, ar.description
                FROM ai_repos ar
                JOIN (
                    SELECT id, quality_score FROM mv_mcp_quality
                    UNION ALL SELECT id, quality_score FROM mv_agents_quality
                    UNION ALL SELECT id, quality_score FROM mv_rag_quality
                    UNION ALL SELECT id, quality_score FROM mv_ai_coding_quality
                    UNION ALL SELECT id, quality_score FROM mv_voice_ai_quality
                    UNION ALL SELECT id, quality_score FROM mv_diffusion_quality
                    UNION ALL SELECT id, quality_score FROM mv_vector_db_quality
                    UNION ALL SELECT id, quality_score FROM mv_embeddings_quality
                    UNION ALL SELECT id, quality_score FROM mv_prompt_eng_quality
                ) q ON ar.id = q.id
                WHERE ar.ai_summary IS NULL
                  AND q.quality_score >= :min_score
                ORDER BY q.quality_score DESC
                LIMIT :limit
            """), {"min_score": min_score, "limit": limit}).fetchall()
            logger.info(f"Fallback: {len(rows)} candidates by quality_score")

    return [dict(r._mapping) for r in rows]


def _save_summary(repo_id: int, summary: str):
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE ai_repos
            SET ai_summary = :summary, ai_summary_at = NOW()
            WHERE id = :id
        """), {"summary": summary, "id": repo_id})
        conn.commit()


def _mark_skipped(repo_id: int):
    """Mark as attempted so we don't retry every run. Use empty string."""
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE ai_repos
            SET ai_summary_at = NOW()
            WHERE id = :id AND ai_summary IS NULL
        """), {"id": repo_id})
        conn.commit()


async def generate_ai_summaries(
    limit: int = MAX_PER_RUN,
    min_score: int = MIN_QUALITY_SCORE,
) -> dict:
    """Fetch READMEs and generate AI summaries for top repos missing them."""
    candidates = _find_candidates(limit, min_score)
    if not candidates:
        return {"processed": 0, "generated": 0, "skipped": 0}

    logger.info(f"Generating AI summaries for {len(candidates)} repos (min_score={min_score})")

    generated = 0
    skipped = 0
    sem = asyncio.Semaphore(5)  # max 5 concurrent GitHub fetches

    # Pre-flight: check GitHub API before fetching thousands of READMEs
    global _readme_rate_limited
    _readme_rate_limited = False
    async with httpx.AsyncClient(timeout=30) as test_client:
        try:
            resp = await test_client.get(
                "https://api.github.com/rate_limit",
                headers=_github_headers(),
            )
            if resp.status_code == 403:
                logger.error("GitHub rate-limited (403) — skipping all README fetches")
                return {"processed": 0, "generated": 0, "skipped": "github_rate_limited"}
            if resp.status_code == 200:
                remaining = resp.json().get("resources", {}).get("core", {}).get("remaining", 0)
                if remaining < 100:
                    logger.warning(f"GitHub near limit ({remaining} remaining) — skipping README fetches")
                    return {"processed": 0, "generated": 0, "skipped": "github_rate_limited"}
        except Exception as e:
            logger.warning(f"GitHub rate limit check failed: {e}")

    async with httpx.AsyncClient(timeout=30) as client:
        for i, repo in enumerate(candidates):
            # Fetch README with concurrency limit
            async with sem:
                readme = await fetch_readme(client, repo["full_name"])
                await asyncio.sleep(0.2)  # respect GitHub rate limits

            if not readme:
                _mark_skipped(repo["id"])
                skipped += 1
                continue

            # Generate summary via Haiku
            prompt = SUMMARY_PROMPT.format(
                full_name=repo["full_name"],
                description=repo["description"] or "No description provided",
                readme_text=readme,
            )
            summary = await call_haiku_text(prompt, max_tokens=200)

            if summary and len(summary) > 20:
                _save_summary(repo["id"], summary)
                generated += 1
            else:
                _mark_skipped(repo["id"])
                skipped += 1

            if (i + 1) % 50 == 0:
                logger.info(f"  {i + 1}/{len(candidates)} processed ({generated} generated, {skipped} skipped)")

    result = {"processed": len(candidates), "generated": generated, "skipped": skipped}
    logger.info(f"AI summaries: {result}")
    return result


async def _main():
    parser = argparse.ArgumentParser(description="Generate AI summaries for repos")
    parser.add_argument("--limit", type=int, default=MAX_PER_RUN)
    parser.add_argument("--min-score", type=int, default=MIN_QUALITY_SCORE)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    result = await generate_ai_summaries(limit=args.limit, min_score=args.min_score)
    print(f"Done: {result}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    asyncio.run(_main())
