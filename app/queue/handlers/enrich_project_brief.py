"""Enrich task: generate a project intelligence brief via Gemini.

Reads project data + metrics from DB, calls Gemini with the project brief
prompt, writes to project_briefs table. Uses generation_hash for staleness
detection — only regenerates when metrics change or brief is >30 days old.

Follows the same pattern as the existing project_briefs pipeline but runs
as individual tasks via the task queue instead of bulk batches.
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import engine
from app.ingest.llm import call_llm

logger = logging.getLogger(__name__)

HASH_KEYS = [
    "stars", "monthly_downloads", "stars_30d_delta", "dl_30d_delta",
    "commits_30d", "lifecycle_stage", "velocity_band", "hype_bucket",
    "days_since_release", "tier",
]

PROJECT_BRIEF_PROMPT = """\
You are an AI infrastructure analyst writing project intelligence briefs for
technology consultancies evaluating open-source AI tools.

Write a brief for each project below. Each brief must:
1. Lead with the most interesting or surprising metric or trend
2. Make concrete claims with specific numbers (not "growing rapidly" but "+3,200 stars this month")
3. Contextualize within the project's domain — how it compares to peers
4. Flag noteworthy signals: hype vs adoption mismatch, velocity changes, lifecycle stage

Output format — return valid JSON only:
[{{"id": <project_id>, "title": "<headline claim, max 120 chars, lead with the key number>", "summary": "<2-3 sentences of grounded analysis>", "evidence": [{{"type": "project", "slug": "<project_slug>", "metric": "<metric_name>", "value": <number>, "as_of": "{today}"}}]}}]

Rules:
- Title must make a specific quantitative claim (e.g. "CrewAI grows 40% in downloads while star growth slows")
- Summary must contain at least 2 concrete numbers
- Do NOT describe what the project does — the reader already knows. Focus on what is HAPPENING.
- If a project has zero downloads and few stars, say so honestly — "limited adoption signal"
- Hype buckets: "hype" means stars >> downloads (GitHub tourism). "quiet_adoption" means downloads >> stars (real usage, no buzz). Flag these.
- Lifecycle: "emerging" or "launching" with high velocity is interesting. "fading" is a warning. "established" + "slow" is stable infrastructure.
- A project with 0 downloads may still be Docker/binary distribution — note "no package manager signal" not "no adoption"
- Evidence array must include every metric you cite in the title or summary

METRIC REFERENCE:
- stars_30d_delta: star change last 30 days (can be negative)
- dl_30d_delta: download change last 30 days
- hype_bucket: no_downloads | hype | star_heavy | balanced | quiet_adoption
- lifecycle_stage: dormant | fading | emerging | launching | growing | established | stable
- velocity_band: dormant | slow | moderate | fast | hyperspeed
- tier: 1 (mega) to 4 (emerging)

Projects:
{projects_text}

Domain context — other projects in same domain(s) for comparison:
{domain_context}"""


def _brief_hash(row: dict) -> str:
    """SHA-256 of key metrics for staleness detection."""
    payload = json.dumps({k: row.get(k) for k in HASH_KEYS}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _format_project_line(row: dict) -> str:
    """Format a single project line for the LLM prompt."""
    return (
        f"{row['id']} | {row['slug']} | {row['name']} | {row.get('domain', 'n/a')} | "
        f"{row.get('stack_layer', 'n/a')} | {row.get('lab', 'n/a')} | "
        f"★{row.get('stars', 0)} | ↓{row.get('monthly_downloads', 0)} | "
        f"Δ★30d:{row.get('stars_30d_delta', 0)} | Δ↓30d:{row.get('dl_30d_delta', 0)} | "
        f"commits:{row.get('commits_30d', 0)} | {row.get('hype_bucket', 'n/a')} | "
        f"{row.get('lifecycle_stage', 'n/a')} | {row.get('velocity_band', 'n/a')} | "
        f"T{row.get('tier', 4)} | rel:{row.get('days_since_release', 'n/a')}d ago"
    )


async def handle_enrich_project_brief(task: dict) -> dict:
    """Generate a project intelligence brief for a single project.

    subject_id is the project_id (as a string).

    Returns:
        {"status": "generated"} on success
        {"status": "up_to_date"} if hash unchanged and brief is fresh
        {"status": "project_not_found"} if project doesn't exist

    Raises:
        RuntimeError on LLM failure — triggers requeue
    """
    project_id = int(task["subject_id"])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Read project data
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT
                s.project_id AS id, s.slug, s.name, s.domain, s.stack_layer,
                COALESCE(l.name, 'n/a') AS lab,
                COALESCE(s.stars, 0) AS stars,
                COALESCE(s.monthly_downloads, 0) AS monthly_downloads,
                COALESCE(s.stars_30d_delta, 0) AS stars_30d_delta,
                COALESCE(s.dl_30d_delta, 0) AS dl_30d_delta,
                COALESCE(s.commits_30d, 0) AS commits_30d,
                s.lifecycle_stage,
                COALESCE(v.velocity_band, 'n/a') AS velocity_band,
                s.hype_bucket,
                s.days_since_release,
                COALESCE(s.tier, 4) AS tier,
                pb.generation_hash AS existing_hash,
                pb.generated_at AS existing_generated_at
            FROM mv_project_summary s
            LEFT JOIN projects p ON s.project_id = p.id
            LEFT JOIN labs l ON p.lab_id = l.id
            LEFT JOIN mv_velocity v ON s.project_id = v.project_id
            LEFT JOIN project_briefs pb ON s.project_id = pb.project_id
            WHERE s.project_id = :pid AND p.is_active = true
        """), {"pid": project_id}).fetchone()

    if not row:
        return {"status": "project_not_found"}

    m = dict(row._mapping)
    new_hash = _brief_hash(m)

    # Check staleness
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    if (
        m["existing_hash"] is not None
        and m["existing_hash"] == new_hash
        and m["existing_generated_at"]
        and m["existing_generated_at"] >= stale_cutoff
    ):
        return {"status": "up_to_date"}

    # Build prompt
    projects_text = _format_project_line(m)

    # Domain context — top 5 peers
    domain = m.get("domain")
    domain_context = "No domain context available."
    if domain:
        with engine.connect() as conn:
            peers = conn.execute(text("""
                SELECT slug, stars, monthly_downloads, lifecycle_stage
                FROM mv_project_summary
                WHERE domain = :domain AND project_id != :pid
                ORDER BY stars DESC NULLS LAST
                LIMIT 5
            """), {"domain": domain, "pid": project_id}).fetchall()

        if peers:
            lines = []
            for r in peers:
                pm = r._mapping
                lines.append(
                    f"  {pm['slug']}: ★{pm.get('stars', 0)} ↓{pm.get('monthly_downloads', 0)} "
                    f"{pm.get('lifecycle_stage', 'n/a')}"
                )
            domain_context = f"[{domain}]\n" + "\n".join(lines)

    prompt = PROJECT_BRIEF_PROMPT.format(
        projects_text=projects_text,
        domain_context=domain_context,
        today=today,
    )

    result = await call_llm(prompt, max_tokens=4096)

    if not result:
        raise RuntimeError(f"LLM returned no result for project {project_id}")

    # Handle both list and dict responses
    if isinstance(result, list):
        # Find the matching project in the list
        pred = None
        for item in result:
            if isinstance(item, dict) and item.get("id") == project_id:
                pred = item
                break
        if not pred:
            pred = result[0] if result and isinstance(result[0], dict) else None
    elif isinstance(result, dict):
        pred = result
    else:
        raise RuntimeError(f"LLM returned unexpected type for project {project_id}")

    if not pred or not pred.get("title") or not pred.get("summary"):
        raise RuntimeError(f"LLM returned incomplete brief for project {project_id}")

    # Write to project_briefs
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO project_briefs (project_id, title, summary, evidence,
                                        generation_hash, generated_at, updated_at)
            VALUES (:pid, :title, :summary, :evidence::jsonb, :hash, NOW(), NOW())
            ON CONFLICT (project_id) DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                evidence = EXCLUDED.evidence,
                generation_hash = EXCLUDED.generation_hash,
                generated_at = EXCLUDED.generated_at,
                updated_at = EXCLUDED.updated_at
        """), {
            "pid": project_id,
            "title": pred["title"][:300],
            "summary": pred["summary"],
            "evidence": json.dumps(pred.get("evidence", [])),
            "hash": new_hash,
        })
        conn.commit()

    return {"status": "generated"}
