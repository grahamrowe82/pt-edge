"""Enrich task: generate a comparison sentence for a repo pair via Gemini.

Pure enrich — reads repo pair metadata from the database, calls Gemini,
writes the sentence to comparison_sentences. No external API calls.
"""
import logging

from sqlalchemy import text

from app.db import engine
from app.ingest.llm import call_llm_text

logger = logging.getLogger(__name__)

PROMPT = """These two tools appear together in the "{category}" category:

A: {name_a} — {desc_a} ({stars_a:,} stars, {downloads_a:,} monthly downloads)
B: {name_b} — {desc_b} ({stars_b:,} stars, {downloads_b:,} monthly downloads)

Write one sentence explaining the relationship: are they competitors (choose one or the other), complements (use together), or ecosystem siblings (e.g. a tool and its client library)?
Be specific and technical. Do not start with the project names."""


async def handle_enrich_comparison(task: dict) -> dict:
    """Generate a comparison sentence for a repo pair.

    subject_id is the comparison_sentences row ID.

    Returns:
        {"status": "generated", "length": N} on success
        {"status": "no_pair"} if the row doesn't exist

    Raises:
        RuntimeError on LLM failure — triggers requeue
    """
    cs_id = int(task["subject_id"])

    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT cs.id, cs.domain, cs.subcategory,
                   a.full_name AS a_name, a.description AS a_desc,
                   COALESCE(a.stars, 0) AS a_stars,
                   COALESCE(a.downloads_monthly, 0) AS a_downloads,
                   b.full_name AS b_name, b.description AS b_desc,
                   COALESCE(b.stars, 0) AS b_stars,
                   COALESCE(b.downloads_monthly, 0) AS b_downloads
            FROM comparison_sentences cs
            JOIN ai_repos a ON a.id = cs.repo_a_id
            JOIN ai_repos b ON b.id = cs.repo_b_id
            WHERE cs.id = :id
        """), {"id": cs_id}).mappings().fetchone()

    if not row:
        return {"status": "no_pair"}

    prompt = PROMPT.format(
        category=row.get("subcategory") or row.get("domain", ""),
        name_a=row["a_name"],
        desc_a=(row["a_desc"] or "No description")[:200],
        stars_a=row["a_stars"],
        downloads_a=row["a_downloads"],
        name_b=row["b_name"],
        desc_b=(row["b_desc"] or "No description")[:200],
        stars_b=row["b_stars"],
        downloads_b=row["b_downloads"],
    )

    sentence = await call_llm_text(prompt, max_tokens=150)

    if not sentence or len(sentence) <= 20:
        raise RuntimeError(f"LLM returned no usable sentence for pair {cs_id}")

    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE comparison_sentences SET sentence = :sentence
            WHERE id = :id
        """), {"sentence": sentence, "id": cs_id})
        conn.commit()

    return {"status": "generated", "length": len(sentence)}
