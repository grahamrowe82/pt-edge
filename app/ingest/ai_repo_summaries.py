"""Generate practitioner-focused problem briefs for ai_repos.

Produces a problem brief (summary, use_this_if, not_ideal_if, domain_tags)
written for the person who has the problem — scientists, marketers, traders,
HR managers — not developers. Also caches the README text for future
enrichment passes without re-fetching from GitHub.

Processes repos prioritised by allocation budget. Uses cached README when
available (re-fetches if cache is >90 days old).

Run standalone:  python -m app.ingest.ai_repo_summaries [--limit 200] [--min-score 0]
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
from app.ingest.llm import call_haiku
from app.settings import settings

logger = logging.getLogger(__name__)

MAX_PER_RUN = 2000
MIN_QUALITY_SCORE = 0
README_MAX_CHARS = 8000
MIN_README_LENGTH = 100  # skip READMEs shorter than this
README_CACHE_DAYS = 90  # re-fetch README if cache is older than this

PROBLEM_BRIEF_PROMPT = """\
You are writing a short problem brief for an open-source project. Your audience is NOT a developer — \
it's the person who has the problem this project solves. That might be a scientist, a marketer, \
a trader, an HR manager, a teacher, an operations engineer — whoever benefits from this existing.

From the README below, produce a JSON object with these fields:

1. "summary": 2-3 sentences covering:
   - What real-world task or workflow this helps with, in plain language
   - What goes in and what comes out (in terms the practitioner understands, not API terms)
   - Who would use this — the actual end-user persona, not "Python developers"

2. "use_this_if": One sentence starting with "Use this if..." describing the ideal use case

3. "not_ideal_if": One sentence starting with "Not ideal if..." describing when to look elsewhere

4. "domain_tags": 3-5 tags in the vocabulary of the end user, NOT the developer. \
   Use job/field/workflow terms like "spectroscopy", "competitor-analysis", "portfolio-backtesting", \
   "resume-screening" — not technology terms like "contrastive-learning", "multi-agent", "transformer".

Rules:
- Write for the person who has the problem, in their language
- Be specific and concrete — name the domain, the data type, the workflow
- If this is genuinely a developer tool (library, SDK, infrastructure), then the developer IS the end user — write in their language
- Don't mention GitHub stars, scores, or popularity
- Don't start with "This project..." — start with the substance
- Maximum 80 words for the summary

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
    """Find repos needing problem briefs, prioritised by allocation budget."""
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
                           ar.readme_cache, ar.readme_cached_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY ar.domain, ar.subcategory
                               ORDER BY ar.stars DESC NULLS LAST
                           ) AS rn
                    FROM ai_repos ar
                    JOIN budget b ON ar.domain = b.domain
                                 AND ar.subcategory = b.subcategory
                    WHERE ar.problem_domains IS NULL
                      AND ar.description IS NOT NULL
                      AND ar.description <> ''
                )
                SELECT r.id, r.full_name, r.description,
                       r.readme_cache, r.readme_cached_at
                FROM ranked r
                JOIN budget b ON r.domain = b.domain
                             AND r.subcategory = b.subcategory
                WHERE r.rn <= b.row_limit
            """)).fetchall()
            logger.info(f"Budget-driven: {len(rows)} candidates from content_budget")
        else:
            # Fallback: original behaviour
            rows = conn.execute(text("""
                SELECT ar.id, ar.full_name, ar.description,
                       ar.readme_cache, ar.readme_cached_at
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
                WHERE ar.problem_domains IS NULL
                  AND q.quality_score >= :min_score
                ORDER BY q.quality_score DESC
                LIMIT :limit
            """), {"min_score": min_score, "limit": limit}).fetchall()
            logger.info(f"Fallback: {len(rows)} candidates by quality_score")

    return [dict(r._mapping) for r in rows]


def _save_readme_cache(repo_id: int, readme: str):
    """Cache the README text for future enrichment passes."""
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE ai_repos
            SET readme_cache = :readme, readme_cached_at = NOW()
            WHERE id = :id
        """), {"readme": readme, "id": repo_id})
        conn.commit()


def _save_problem_brief(repo_id: int, summary: str, use_this_if: str,
                        not_ideal_if: str, domain_tags: list[str]):
    """Save the problem brief fields to ai_repos."""
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE ai_repos
            SET ai_summary = :summary,
                use_this_if = :use_this_if,
                not_ideal_if = :not_ideal_if,
                problem_domains = :domain_tags,
                ai_summary_at = NOW()
            WHERE id = :id
        """), {
            "summary": summary,
            "use_this_if": use_this_if,
            "not_ideal_if": not_ideal_if,
            "domain_tags": domain_tags,
            "id": repo_id,
        })
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


def _readme_cache_fresh(repo: dict) -> bool:
    """Check if the cached README is fresh enough to use."""
    if not repo.get("readme_cache"):
        return False
    cached_at = repo.get("readme_cached_at")
    if not cached_at:
        return False
    age_days = (datetime.now(timezone.utc) - cached_at).days
    return age_days < README_CACHE_DAYS


async def generate_ai_summaries(
    limit: int = MAX_PER_RUN,
    min_score: int = MIN_QUALITY_SCORE,
) -> dict:
    """Fetch READMEs and generate problem briefs for repos missing them."""
    candidates = _find_candidates(limit, min_score)
    if not candidates:
        return {"processed": 0, "generated": 0, "skipped": 0, "cache_hits": 0}

    logger.info(f"Generating problem briefs for {len(candidates)} repos (min_score={min_score})")

    generated = 0
    skipped = 0
    cache_hits = 0
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
            # Use cached README if fresh, otherwise fetch from GitHub
            if _readme_cache_fresh(repo):
                readme = repo["readme_cache"]
                cache_hits += 1
            else:
                async with sem:
                    readme = await fetch_readme(client, repo["full_name"])
                    await asyncio.sleep(0.2)  # respect GitHub rate limits

                if readme:
                    _save_readme_cache(repo["id"], readme)

            if not readme:
                _mark_skipped(repo["id"])
                skipped += 1
                continue

            # Generate problem brief via Gemini
            prompt = PROBLEM_BRIEF_PROMPT.format(
                full_name=repo["full_name"],
                description=repo["description"] or "No description provided",
                readme_text=readme,
            )
            result = await call_haiku(prompt, max_tokens=400)

            if result and isinstance(result, dict) and result.get("summary"):
                _save_problem_brief(
                    repo["id"],
                    summary=result["summary"],
                    use_this_if=result.get("use_this_if", ""),
                    not_ideal_if=result.get("not_ideal_if", ""),
                    domain_tags=result.get("domain_tags", []),
                )
                generated += 1
            else:
                _mark_skipped(repo["id"])
                skipped += 1

            if (i + 1) % 50 == 0:
                logger.info(
                    f"  {i + 1}/{len(candidates)} processed "
                    f"({generated} generated, {skipped} skipped, {cache_hits} cache hits)"
                )

    result = {
        "processed": len(candidates),
        "generated": generated,
        "skipped": skipped,
        "cache_hits": cache_hits,
    }
    logger.info(f"Problem briefs: {result}")
    return result


async def _main():
    parser = argparse.ArgumentParser(description="Generate problem briefs for repos")
    parser.add_argument("--limit", type=int, default=MAX_PER_RUN)
    parser.add_argument("--min-score", type=int, default=MIN_QUALITY_SCORE)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    result = await generate_ai_summaries(limit=args.limit, min_score=args.min_score)
    print(f"Done: {result}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    asyncio.run(_main())
