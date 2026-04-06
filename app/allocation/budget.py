"""Budget allocator: distributes content pipeline LLM spend across categories.

Reads mv_allocation_scores (opportunity_score + summary_ratio + repo_count),
computes per-category need scores, and writes a transient content_budget table
that content pipelines read instead of hardcoded ORDER BY limits.

The budget table contains row counts per pipeline per (domain, subcategory).
Total rows per pipeline scale linearly with LLM_BUDGET_MULTIPLIER.
"""

import logging
from math import log2

from sqlalchemy import text

from app.db import engine

logger = logging.getLogger(__name__)

# Base row counts at multiplier=1.0 — matches current hardcoded limits
BASE_CONTENT_ROWS = {
    "ai_repo_summaries": 8000,
    "comparison_sentences": 1000,
}


def compute_and_write_budget(multiplier: float = 1.0) -> dict:
    """Compute content budget from allocation scores and write to content_budget table.

    Returns summary dict with total rows per pipeline and top categories.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT domain, subcategory, repo_count,
                   opportunity_score, summary_ratio
            FROM mv_allocation_scores
            WHERE opportunity_score > 0
        """)).fetchall()

    if not rows:
        logger.warning("No allocation scores found — content pipelines will use fallback")
        return {"status": "empty", "categories": 0}

    # Compute need score per category:
    # high opportunity * low coverage * category size = more budget
    categories = []
    for r in rows:
        m = r._mapping
        opp = m["opportunity_score"] or 0
        coverage = float(m["summary_ratio"] or 0)
        repo_count = m["repo_count"] or 0
        need = opp * (1 - coverage) * log2(repo_count + 1)
        if need > 0:
            categories.append({
                "domain": m["domain"],
                "subcategory": m["subcategory"],
                "need": need,
                "repo_count": repo_count,
                "opportunity_score": opp,
                "summary_ratio": coverage,
            })

    if not categories:
        logger.warning("All categories fully covered — no content budget to allocate")
        return {"status": "all_covered", "categories": 0}

    # Normalise need scores to sum to 1.0
    total_need = sum(c["need"] for c in categories)
    for c in categories:
        c["share"] = c["need"] / total_need

    # Build budget rows for each pipeline
    budget_rows = []
    result_summary = {}

    for pipeline, base_rows in BASE_CONTENT_ROWS.items():
        total_rows = int(base_rows * multiplier)
        allocated = 0
        pipeline_rows = []

        # Sort by share descending for stable allocation
        for c in sorted(categories, key=lambda x: x["share"], reverse=True):
            row_limit = max(1, round(c["share"] * total_rows))
            # Don't exceed total
            if allocated + row_limit > total_rows:
                row_limit = total_rows - allocated
            if row_limit <= 0:
                continue
            pipeline_rows.append({
                "pipeline": pipeline,
                "domain": c["domain"],
                "subcategory": c["subcategory"],
                "row_limit": row_limit,
            })
            allocated += row_limit
            if allocated >= total_rows:
                break

        budget_rows.extend(pipeline_rows)
        result_summary[pipeline] = {
            "total_rows": allocated,
            "categories": len(pipeline_rows),
        }

    # Write to content_budget (TRUNCATE + INSERT)
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE content_budget"))
        if budget_rows:
            conn.execute(
                text("""
                    INSERT INTO content_budget (pipeline, domain, subcategory, row_limit)
                    VALUES (:pipeline, :domain, :subcategory, :row_limit)
                """),
                budget_rows,
            )
        conn.commit()

    # Log top 5 categories
    top5 = sorted(categories, key=lambda x: x["need"], reverse=True)[:5]
    for c in top5:
        logger.info(
            f"  Top: {c['domain']}/{c['subcategory']} "
            f"opp={c['opportunity_score']} cov={c['summary_ratio']:.0%} "
            f"share={c['share']:.1%}"
        )

    logger.info(
        f"Budget allocated: {len(budget_rows)} rows across "
        f"{len(categories)} categories (multiplier={multiplier})"
    )

    return {
        "status": "ok",
        "multiplier": multiplier,
        "categories": len(categories),
        **result_summary,
    }
