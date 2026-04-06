"""Enrich task: generate a domain landscape brief via Gemini.

Pure enrich — reads project data from mv_project_summary for a single
domain, calls Gemini with the domain brief prompt, writes to
domain_briefs table. No external API calls.

Previously ran only on Sundays. Now staleness-driven: the scheduler
creates tasks when a domain's brief is >7 days old or missing.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine
from app.ingest.llm import call_llm
from app.settings import settings

logger = logging.getLogger(__name__)

DOMAIN_BRIEF_PROMPT = """\
You are an AI infrastructure analyst writing domain landscape briefs for
technology consultancies.

Write a landscape overview for the "{domain}" domain based on these projects.

Your brief must:
1. Identify the dominant player(s) by downloads and stars
2. Name the fastest-growing project(s) by 30-day deltas
3. Note any hype vs adoption mismatches
4. Identify gaps or emerging sub-segments
5. Give a 1-sentence verdict on domain maturity

Output — return valid JSON only:
{{"domain": "{domain}", "title": "<headline claim, max 120 chars>", "summary": "<3-5 sentences of comparative landscape analysis>", "evidence": [{{"type": "project", "slug": "<slug>", "metric": "<metric>", "value": <number>, "as_of": "{today}"}}]}}

Rules:
- Every project mentioned must appear in the evidence array
- Lead with the most interesting structural finding, not a list
- Compare — don't just describe each project independently
- Use concrete numbers throughout

Projects in {domain} (sorted by stars desc):
{projects_text}"""


def _format_project_line(row: dict) -> str:
    return (
        f"{row['id']} | {row['slug']} | {row['name']} | {row.get('domain', 'n/a')} | "
        f"{row.get('stack_layer', 'n/a')} | n/a | "
        f"★{row.get('stars', 0)} | ↓{row.get('monthly_downloads', 0)} | "
        f"Δ★30d:{row.get('stars_30d_delta', 0)} | Δ↓30d:{row.get('dl_30d_delta', 0)} | "
        f"commits:{row.get('commits_30d', 0)} | {row.get('hype_bucket', 'n/a')} | "
        f"{row.get('lifecycle_stage', 'n/a')} | {row.get('velocity_band', 'n/a')} | "
        f"T{row.get('tier', 4)} | rel:{row.get('days_since_release', 'n/a')}d ago"
    )


async def handle_enrich_domain_brief(task: dict) -> dict:
    """Generate a landscape brief for a single domain.

    subject_id is the domain name (e.g., "mcp", "agents").

    Returns:
        {"status": "generated"} on success
        {"status": "no_projects"} if the domain has no projects

    Raises:
        RuntimeError on LLM failure — triggers requeue
    """
    if not settings.GEMINI_API_KEY:
        return {"status": "skipped", "reason": "no API key"}

    domain = task["subject_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                s.project_id AS id, s.slug, s.name, s.domain, s.stack_layer,
                COALESCE(s.stars, 0) AS stars,
                COALESCE(s.monthly_downloads, 0) AS monthly_downloads,
                COALESCE(s.stars_30d_delta, 0) AS stars_30d_delta,
                COALESCE(s.dl_30d_delta, 0) AS dl_30d_delta,
                COALESCE(s.commits_30d, 0) AS commits_30d,
                s.lifecycle_stage,
                COALESCE(v.velocity_band, 'n/a') AS velocity_band,
                s.hype_bucket,
                s.days_since_release,
                COALESCE(s.tier, 4) AS tier
            FROM mv_project_summary s
            LEFT JOIN mv_velocity v ON s.project_id = v.project_id
            WHERE s.domain = :domain
            ORDER BY s.stars DESC NULLS LAST
        """), {"domain": domain}).fetchall()

    if not rows:
        return {"status": "no_projects"}

    project_lines = [_format_project_line(dict(r._mapping)) for r in rows]
    projects_text = "\n".join(project_lines)

    prompt = DOMAIN_BRIEF_PROMPT.format(
        domain=domain,
        projects_text=projects_text,
        today=today,
    )

    result = await call_llm(prompt, max_tokens=2048)
    if not result or not isinstance(result, dict):
        raise RuntimeError(f"LLM returned no valid result for domain '{domain}'")

    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO domain_briefs (domain, title, summary, evidence, generated_at, updated_at)
            VALUES (:domain, :title, :summary, CAST(:evidence AS jsonb), NOW(), NOW())
            ON CONFLICT (domain) DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                evidence = EXCLUDED.evidence,
                generated_at = EXCLUDED.generated_at,
                updated_at = EXCLUDED.updated_at
        """), {
            "domain": domain,
            "title": result.get("title", "")[:300],
            "summary": result.get("summary", ""),
            "evidence": json.dumps(result.get("evidence", [])),
        })
        conn.commit()

    return {"status": "generated"}
