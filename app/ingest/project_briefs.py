"""Generate LLM-powered project and domain intelligence briefs.

Per-project briefs: headline + 2-3 sentence grounded narrative for each project.
Per-domain briefs: comparative landscape narrative for each populated domain.

Uses generation_hash (SHA-256 of key metrics) for staleness detection —
only regenerates when metrics change or brief is >30 days old.

Run standalone:  python -m app.ingest.project_briefs
"""
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from app.db import engine, SessionLocal
from app.ingest.llm import call_haiku
from app.models import SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 10
MAX_BRIEFS_PER_RUN = 100

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


def _format_domain_context(conn, domain: str, exclude_ids: list[int]) -> str:
    """Get top 5 peers in domain for comparative context."""
    rows = conn.execute(text("""
        SELECT slug, stars, monthly_downloads, lifecycle_stage
        FROM mv_project_summary
        WHERE domain = :domain AND project_id != ALL(:exclude)
        ORDER BY stars DESC NULLS LAST
        LIMIT 5
    """), {"domain": domain, "exclude": exclude_ids}).fetchall()

    if not rows:
        return "No other projects in this domain."

    lines = []
    for r in rows:
        m = r._mapping
        lines.append(
            f"  {m['slug']}: ★{m.get('stars', 0)} ↓{m.get('monthly_downloads', 0)} "
            f"{m.get('lifecycle_stage', 'n/a')}"
        )
    return "\n".join(lines)


def _validate_brief(brief: dict, input_rows: dict[int, dict]) -> bool:
    """Validate that evidence values match input data."""
    if not isinstance(brief, dict):
        return False
    if not brief.get("title") or not brief.get("summary"):
        return False

    evidence = brief.get("evidence", [])
    if not isinstance(evidence, list):
        return False

    pid = brief.get("id")
    if pid not in input_rows:
        return False

    row = input_rows[pid]
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        metric = ev.get("metric")
        value = ev.get("value")
        if metric and metric in row:
            expected = row[metric]
            # Allow minor floating point differences
            try:
                if expected is not None and abs(float(value) - float(expected)) > 1:
                    logger.warning(
                        f"Evidence mismatch for project {pid}: {metric}={value} "
                        f"(expected {expected})"
                    )
                    return False
            except (ValueError, TypeError):
                pass  # Non-numeric metrics, skip validation

    return True


def _batch_upsert_project_briefs(updates: list[dict]) -> int:
    """Upsert project briefs using psycopg2 execute_values."""
    if not updates:
        return 0
    from psycopg2.extras import execute_values

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        execute_values(
            cur,
            """
            INSERT INTO project_briefs (project_id, title, summary, evidence, generation_hash, generated_at, updated_at)
            VALUES %s
            ON CONFLICT (project_id) DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                evidence = EXCLUDED.evidence,
                generation_hash = EXCLUDED.generation_hash,
                generated_at = EXCLUDED.generated_at,
                updated_at = EXCLUDED.updated_at
            """,
            [
                (
                    u["project_id"], u["title"], u["summary"],
                    json.dumps(u["evidence"]) if u.get("evidence") else None,
                    u["generation_hash"],
                    datetime.now(timezone.utc), datetime.now(timezone.utc),
                )
                for u in updates
            ],
            template="(%s, %s, %s, %s::jsonb, %s, %s, %s)",
            page_size=100,
        )
        count = cur.rowcount
        raw_conn.commit()
        return count
    except Exception as e:
        try:
            raw_conn.rollback()
        except Exception:
            pass
        logger.error(f"Batch upsert project_briefs failed: {e}")
        return 0
    finally:
        try:
            raw_conn.close()
        except Exception:
            pass


async def generate_project_briefs(limit: int = 500) -> dict:
    """Generate or refresh LLM project briefs for stale/missing projects."""
    if not settings.ANTHROPIC_API_KEY:
        logger.info("No ANTHROPIC_API_KEY — skipping project briefs")
        return {"generated": 0, "skipped": "no API key"}

    started_at = datetime.now(timezone.utc)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    with engine.connect() as conn:
        rows = conn.execute(text("""
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
            WHERE p.is_active = true
            ORDER BY s.stars DESC NULLS LAST
            LIMIT :lim
        """), {"lim": limit}).fetchall()

    if not rows:
        logger.info("No projects found for brief generation")
        return {"generated": 0, "batches": 0}

    # Filter to stale/missing briefs
    stale_rows = []
    for r in rows:
        m = dict(r._mapping)
        new_hash = _brief_hash(m)
        if (
            m["existing_hash"] is None  # No brief yet
            or m["existing_hash"] != new_hash  # Metrics changed
            or (m["existing_generated_at"] and m["existing_generated_at"] < stale_cutoff)  # >30 days old
        ):
            m["_new_hash"] = new_hash
            stale_rows.append(m)

    if not stale_rows:
        logger.info("All project briefs are up to date")
        return {"generated": 0, "skipped": len(rows), "batches": 0}

    # Cap at MAX_BRIEFS_PER_RUN
    stale_rows = stale_rows[:MAX_BRIEFS_PER_RUN]
    logger.info(f"Generating briefs for {len(stale_rows)} projects ({len(rows)} total checked)")

    # Group by domain for batching
    batches = [stale_rows[i:i + BATCH_SIZE] for i in range(0, len(stale_rows), BATCH_SIZE)]

    total_generated = 0
    errors = 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for batch_idx, batch in enumerate(batches):
        # Build input rows lookup
        input_rows = {r["id"]: r for r in batch}

        # Format project lines
        project_lines = [_format_project_line(r) for r in batch]
        projects_text = "\n".join(project_lines)

        # Build domain context
        batch_ids = [r["id"] for r in batch]
        domains_in_batch = {r.get("domain") for r in batch if r.get("domain")}
        domain_context_parts = []
        with engine.connect() as conn:
            for domain in domains_in_batch:
                if domain:
                    ctx = _format_domain_context(conn, domain, batch_ids)
                    domain_context_parts.append(f"[{domain}]\n{ctx}")

        domain_context = "\n\n".join(domain_context_parts) if domain_context_parts else "No domain context available."

        prompt = PROJECT_BRIEF_PROMPT.format(
            projects_text=projects_text,
            domain_context=domain_context,
            today=today,
        )

        predictions = await call_haiku(prompt, max_tokens=4096)
        if not predictions:
            logger.warning(f"Batch {batch_idx + 1}/{len(batches)}: LLM returned no results")
            errors += 1
            continue

        if not isinstance(predictions, list):
            predictions = [predictions]

        updates = []
        for pred in predictions:
            if not isinstance(pred, dict):
                continue
            pid = pred.get("id")
            if pid not in input_rows:
                continue
            if not _validate_brief(pred, input_rows):
                logger.warning(f"Brief validation failed for project {pid}")
                continue
            updates.append({
                "project_id": pid,
                "title": pred["title"][:300],
                "summary": pred["summary"],
                "evidence": pred.get("evidence", []),
                "generation_hash": input_rows[pid]["_new_hash"],
            })

        if updates:
            written = _batch_upsert_project_briefs(updates)
            total_generated += written

        logger.info(
            f"Batch {batch_idx + 1}/{len(batches)}: "
            f"{len(updates)} generated, {total_generated} total"
        )

    # Sync log
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="project_briefs",
            status="success" if not errors else "partial",
            records_written=total_generated,
            error_message=f"{errors} LLM errors" if errors else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    result = {
        "generated": total_generated,
        "checked": len(rows),
        "stale": len(stale_rows),
        "batches": len(batches),
        "errors": errors,
    }
    logger.info(f"Project brief generation complete: {result}")
    return result


async def generate_domain_briefs() -> dict:
    """Generate LLM domain landscape briefs for each populated domain."""
    if not settings.ANTHROPIC_API_KEY:
        logger.info("No ANTHROPIC_API_KEY — skipping domain briefs")
        return {"generated": 0, "skipped": "no API key"}

    started_at = datetime.now(timezone.utc)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with engine.connect() as conn:
        domains = conn.execute(text("""
            SELECT DISTINCT domain FROM mv_project_summary
            WHERE domain IS NOT NULL
            ORDER BY domain
        """)).fetchall()

    if not domains:
        logger.info("No populated domains found")
        return {"generated": 0}

    total_generated = 0
    errors = 0

    for domain_row in domains:
        domain = domain_row._mapping["domain"]

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
            continue

        project_lines = [_format_project_line(dict(r._mapping)) for r in rows]
        projects_text = "\n".join(project_lines)

        prompt = DOMAIN_BRIEF_PROMPT.format(
            domain=domain,
            projects_text=projects_text,
            today=today,
        )

        result = await call_haiku(prompt, max_tokens=2048)
        if not result or not isinstance(result, dict):
            logger.warning(f"Domain brief for '{domain}': LLM returned no valid result")
            errors += 1
            continue

        # Upsert domain brief
        try:
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
            total_generated += 1
        except Exception as e:
            logger.error(f"Failed to upsert domain brief for '{domain}': {e}")
            errors += 1

        logger.info(f"Domain brief generated: {domain}")

    # Sync log
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="domain_briefs",
            status="success" if not errors else "partial",
            records_written=total_generated,
            error_message=f"{errors} LLM errors" if errors else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    result_dict = {"generated": total_generated, "domains": len(domains), "errors": errors}
    logger.info(f"Domain brief generation complete: {result_dict}")
    return result_dict


REPO_BRIEF_PROMPT = """\
You are an AI infrastructure analyst writing intelligence briefs for
a directory site that ranks open-source AI tools by quality.

Write a brief for each repository below. Each brief must:
1. Lead with the most interesting metric or trend
2. Make concrete claims with specific numbers
3. Flag noteworthy signals: adoption, momentum, or lack thereof

Output format — return valid JSON only:
[{{"id": <repo_id>, "title": "<headline claim, max 120 chars>", "summary": "<2-3 sentences of grounded analysis>", "evidence": [{{"type": "project", "slug": "<full_name>", "metric": "<metric_name>", "value": <number>, "as_of": "{today}"}}]}}]

Rules:
- Title must include at least one specific number
- Summary must contain at least 2 concrete numbers
- Do NOT describe what the repo does — focus on what is HAPPENING
- Evidence array must include every metric cited

Repositories:
{repos_text}"""


async def generate_repo_briefs() -> dict:
    """Generate briefs for repos selected by allocation budget.

    Works against ai_repos directly (not the legacy projects table).
    Reads content_budget to determine which categories to prioritise.
    """
    if not settings.ANTHROPIC_API_KEY:
        logger.info("No ANTHROPIC_API_KEY — skipping repo briefs")
        return {"generated": 0, "skipped": "no API key"}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get allocated repos from content_budget
    with engine.connect() as conn:
        has_budget = conn.execute(text(
            "SELECT 1 FROM content_budget WHERE pipeline = 'repo_briefs' LIMIT 1"
        )).fetchone()

        if not has_budget:
            logger.info("No content_budget for repo_briefs — skipping")
            return {"generated": 0, "skipped": "no budget"}

        rows = conn.execute(text("""
            WITH budget AS (
                SELECT domain, subcategory, row_limit
                FROM content_budget
                WHERE pipeline = 'repo_briefs'
            ),
            ranked AS (
                SELECT ar.id, ar.full_name, ar.name, ar.domain, ar.subcategory,
                       COALESCE(ar.stars, 0) AS stars,
                       COALESCE(ar.downloads_monthly, 0) AS monthly_downloads,
                       COALESCE(ar.forks, 0) AS forks,
                       COALESCE(ar.commits_30d, 0) AS commits_30d,
                       ar.description,
                       ROW_NUMBER() OVER (
                           PARTITION BY ar.domain, ar.subcategory
                           ORDER BY ar.stars DESC NULLS LAST
                       ) AS rn
                FROM ai_repos ar
                JOIN budget b ON ar.domain = b.domain AND ar.subcategory = b.subcategory
                LEFT JOIN repo_briefs rb ON rb.ai_repo_id = ar.id
                WHERE rb.id IS NULL
                  AND ar.description IS NOT NULL AND ar.description <> ''
            )
            SELECT r.id, r.full_name, r.name, r.domain, r.subcategory,
                   r.stars, r.monthly_downloads, r.forks, r.commits_30d, r.description
            FROM ranked r
            JOIN budget b ON r.domain = b.domain AND r.subcategory = b.subcategory
            WHERE r.rn <= b.row_limit
        """)).fetchall()

    if not rows:
        logger.info("All allocated repos already have briefs")
        return {"generated": 0, "checked": 0}

    logger.info(f"Generating repo briefs for {len(rows)} repos")

    # Batch into groups of BATCH_SIZE
    all_rows = [dict(r._mapping) for r in rows]
    batches = [all_rows[i:i + BATCH_SIZE] for i in range(0, len(all_rows), BATCH_SIZE)]
    total_generated = 0
    errors = 0

    for batch_idx, batch in enumerate(batches):
        # Format repo lines
        lines = []
        for r in batch:
            lines.append(
                f"{r['id']} | {r['full_name']} | {r.get('domain', 'n/a')} | "
                f"★{r['stars']} | ↓{r['monthly_downloads']} | "
                f"forks:{r['forks']} | commits_30d:{r['commits_30d']} | "
                f"{(r.get('description') or '')[:100]}"
            )
        repos_text = "\n".join(lines)
        prompt = REPO_BRIEF_PROMPT.format(repos_text=repos_text, today=today)

        result = await call_haiku(prompt, max_tokens=4096)
        if not result or not isinstance(result, list):
            logger.warning(f"Batch {batch_idx + 1}/{len(batches)}: LLM returned no results")
            errors += 1
            continue

        batch_generated = 0
        for brief in result:
            repo_id = brief.get("id")
            title = brief.get("title", "")[:300]
            summary = brief.get("summary", "")
            evidence = brief.get("evidence", [])

            if not repo_id or not title or not summary:
                continue

            try:
                with engine.connect() as conn:
                    conn.execute(text("""
                        INSERT INTO repo_briefs (ai_repo_id, title, summary, evidence,
                                                 generated_at, updated_at)
                        VALUES (:repo_id, :title, :summary, :evidence::jsonb, NOW(), NOW())
                        ON CONFLICT (ai_repo_id) DO UPDATE SET
                            title = EXCLUDED.title,
                            summary = EXCLUDED.summary,
                            evidence = EXCLUDED.evidence,
                            updated_at = EXCLUDED.updated_at
                    """), {
                        "repo_id": repo_id,
                        "title": title,
                        "summary": summary,
                        "evidence": json.dumps(evidence),
                    })
                    conn.commit()
                batch_generated += 1
            except Exception as e:
                logger.warning(f"Failed to upsert repo brief for {repo_id}: {e}")

        total_generated += batch_generated
        logger.info(
            f"Batch {batch_idx + 1}/{len(batches)}: "
            f"{batch_generated} generated, {total_generated} total"
        )

    result_dict = {
        "generated": total_generated,
        "checked": len(all_rows),
        "batches": len(batches),
        "errors": errors,
    }
    logger.info(f"Repo brief generation complete: {result_dict}")
    return result_dict


async def main():
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = await generate_project_briefs()
    logger.info(f"Project briefs: {result}")
    result = await generate_domain_briefs()
    logger.info(f"Domain briefs: {result}")


if __name__ == "__main__":
    asyncio.run(main())
