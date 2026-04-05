"""Enrich task: generate a domain landscape brief via Gemini.

Reads domain-level project data from DB, calls Gemini with the domain brief
prompt, writes to domain_briefs table. Staleness-driven (>7 days old or
missing) — no longer tied to day-of-week.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine
from app.ingest.llm import call_llm

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
    """Format a single project line for the LLM prompt."""
    return (
        f"{row['id']} | {row['slug']} | {row['name']} | {row.get('domain', 'n/a')} | "
        f"{row.get('stack_layer', 'n/a')} | "
        f"★{row.get('stars', 0)} | ↓{row.get('monthly_downloads', 0)} | "
        f"Δ★30d:{row.get('stars_30d_delta', 0)} | Δ↓30d:{row.get('dl_30d_delta', 0)} | "
        f"commits:{row.get('commits_30d', 0)} | {row.get('hype_bucket', 'n/a')} | "
        f"{row.get('lifecycle_stage', 'n/a')} | {row.get('velocity_band', 'n/a')} | "
        f"T{row.get('tier', 4)} | rel:{row.get('days_since_release', 'n/a')}d ago"
    )


async def handle_enrich_domain_brief(task: dict) -> dict:
    """Generate a domain landscape brief.

    subject_id is the domain name (e.g., "mcp", "agents").

    Returns:
        {"status": "generated"} on success
        {"status": "up_to_date"} if brief is <7 days old
        {"status": "no_projects"} if domain has no projects

    Raises:
        RuntimeError on LLM failure — triggers requeue
    """
    domain = task["subject_id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Check if existing brief is fresh enough (<7 days)
    with engine.connect() as conn:
        existing = conn.execute(text("""
            SELECT generated_at FROM domain_briefs WHERE domain = :domain
        """), {"domain": domain}).fetchone()

    if existing and existing[0]:
        age_days = (datetime.now(timezone.utc) - existing[0].replace(tzinfo=timezone.utc)).days
        if age_days < 7:
            return {"status": "up_to_date"}

    # Read domain projects
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

    # Upsert domain brief
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO domain_briefs (domain, title, summary, evidence, generated_at, updated_at)
            VALUES (:domain, :title, :summary, :evidence::jsonb, NOW(), NOW())
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
