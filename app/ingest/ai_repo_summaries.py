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

MAX_PER_RUN = 200
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


async def fetch_readme(client: httpx.AsyncClient, full_name: str) -> str | None:
    """Fetch raw README text from GitHub. Returns truncated text or None."""
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
        logger.warning(f"GitHub README {resp.status_code} for {full_name}")
        return None
    except httpx.HTTPError as e:
        logger.warning(f"GitHub README fetch error for {full_name}: {e}")
        return None


def _find_candidates(limit: int, min_score: int):
    """Find repos needing summaries, ordered by quality score descending."""
    with engine.connect() as conn:
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
