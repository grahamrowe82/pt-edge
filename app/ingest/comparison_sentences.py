"""Generate decision sentences for comparison pages via Haiku.

Finds comparison pairs without sentences and fills them in.
2,000 per run, integrated into the daily ingest pipeline.

Run standalone: python -m app.ingest.comparison_sentences [--limit 100]
"""
import asyncio
import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine, readonly_engine
from app.ingest.llm import call_llm_text

logger = logging.getLogger(__name__)

MAX_PER_RUN = 2000

PROMPT = """These two tools appear together in the "{category}" category:

A: {name_a} — {desc_a} ({stars_a:,} stars, {downloads_a:,} monthly downloads)
B: {name_b} — {desc_b} ({stars_b:,} stars, {downloads_b:,} monthly downloads)

Write one sentence explaining the relationship: are they competitors (choose one or the other), complements (use together), or ecosystem siblings (e.g. a tool and its client library)?
Be specific and technical. Do not start with the project names."""


def _find_candidates(limit):
    """Find comparison pairs without sentences, prioritised by allocation budget."""
    with readonly_engine.connect() as conn:
        has_budget = conn.execute(text(
            "SELECT 1 FROM content_budget WHERE pipeline = 'comparison_sentences' LIMIT 1"
        )).fetchone()

        if has_budget:
            rows = conn.execute(text("""
                WITH budget AS (
                    SELECT domain, subcategory, row_limit
                    FROM content_budget
                    WHERE pipeline = 'comparison_sentences'
                ),
                ranked AS (
                    SELECT cs.id, cs.domain, cs.subcategory,
                           a.full_name as a_name, a.description as a_desc,
                           a.stars as a_stars, a.downloads_monthly as a_downloads,
                           b.full_name as b_name, b.description as b_desc,
                           b.stars as b_stars, b.downloads_monthly as b_downloads,
                           ROW_NUMBER() OVER (
                               PARTITION BY cs.domain, cs.subcategory
                               ORDER BY GREATEST(a.stars, b.stars) DESC
                           ) AS rn
                    FROM comparison_sentences cs
                    JOIN ai_repos a ON a.id = cs.repo_a_id
                    JOIN ai_repos b ON b.id = cs.repo_b_id
                    JOIN budget bu ON cs.domain = bu.domain
                                  AND cs.subcategory = bu.subcategory
                    WHERE cs.sentence IS NULL
                )
                SELECT r.id, r.domain, r.subcategory,
                       r.a_name, r.a_desc, r.a_stars, r.a_downloads,
                       r.b_name, r.b_desc, r.b_stars, r.b_downloads
                FROM ranked r
                JOIN budget b ON r.domain = b.domain
                             AND r.subcategory = b.subcategory
                WHERE r.rn <= b.row_limit
            """)).fetchall()
            logger.info(f"Budget-driven: {len(rows)} comparison candidates")
        else:
            rows = conn.execute(text("""
                SELECT cs.id, cs.domain, cs.subcategory,
                       a.full_name as a_name, a.description as a_desc,
                       a.stars as a_stars, a.downloads_monthly as a_downloads,
                       b.full_name as b_name, b.description as b_desc,
                       b.stars as b_stars, b.downloads_monthly as b_downloads
                FROM comparison_sentences cs
                JOIN ai_repos a ON a.id = cs.repo_a_id
                JOIN ai_repos b ON b.id = cs.repo_b_id
                WHERE cs.sentence IS NULL
                ORDER BY GREATEST(a.stars, b.stars) DESC
                LIMIT :limit
            """), {"limit": limit}).fetchall()
            logger.info(f"Fallback: {len(rows)} comparison candidates by stars")

    return [dict(r._mapping) for r in rows]


async def generate_comparison_sentences(limit=MAX_PER_RUN):
    """Fill in decision sentences for comparison pairs."""
    candidates = _find_candidates(limit)
    if not candidates:
        return {"processed": 0, "generated": 0}

    logger.info(f"Generating decision sentences for {len(candidates)} comparison pairs")
    generated = 0

    for i, c in enumerate(candidates):
        # Get scores from the appropriate quality view
        score_a, score_b = 0, 0
        try:
            with readonly_engine.connect() as conn:
                # Simple approach: just get the scores
                for name, var in [(c["a_name"], "a"), (c["b_name"], "b")]:
                    row = conn.execute(text("""
                        SELECT quality_score FROM ai_repos ar
                        WHERE ar.full_name = :name
                    """), {"name": name}).fetchone()
                    # quality_score isn't on ai_repos, approximate from stars
                    pass
        except Exception:
            pass

        prompt = PROMPT.format(
            category=c.get("subcategory") or c.get("domain", ""),
            name_a=c["a_name"],
            desc_a=(c["a_desc"] or "No description")[:200],
            score_a=0,  # We don't have the score easily here
            stars_a=c["a_stars"] or 0,
            downloads_a=c["a_downloads"] or 0,
            name_b=c["b_name"],
            desc_b=(c["b_desc"] or "No description")[:200],
            score_b=0,
            stars_b=c["b_stars"] or 0,
            downloads_b=c["b_downloads"] or 0,
        )

        sentence = await call_llm_text(prompt, max_tokens=150)

        if sentence and len(sentence) > 20:
            with engine.connect() as conn:
                conn.execute(text("""
                    UPDATE comparison_sentences SET sentence = :sentence
                    WHERE id = :id
                """), {"sentence": sentence, "id": c["id"]})
                conn.commit()
            generated += 1

        if (i + 1) % 100 == 0:
            logger.info(f"  {i + 1}/{len(candidates)} processed ({generated} generated)")

    result = {"processed": len(candidates), "generated": generated}
    logger.info(f"Comparison sentences: {result}")
    return result


async def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=MAX_PER_RUN)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    result = await generate_comparison_sentences(limit=args.limit)
    print(f"Done: {result}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    asyncio.run(_main())
