"""Generate weekly LLM-powered landscape briefs per ecosystem layer.

Each landscape brief provides a weekly overview of an ecosystem layer —
MCP gateways, agent perception tools, etc. — including breakout projects,
traction distribution, and structural findings.

Follows the domain_briefs pattern: staleness via generation_hash,
upsert into landscape_briefs table, call_llm for generation.

Runs weekly on Sundays via the ingest pipeline.

Run standalone:  python -m app.ingest.landscape_briefs
"""
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine, SessionLocal
from app.ingest.llm import call_llm
from app.models import SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

# Each layer maps to a SQL WHERE clause fragment for ai_repos + projects
LANDSCAPE_LAYERS = [
    ("mcp-gateway", "ar.domain = 'mcp' AND ar.subcategory = 'gateway'",
     "MCP gateway and aggregator tools — service mesh for AI agents"),
    ("mcp-transport", "ar.domain = 'mcp' AND ar.subcategory = 'transport'",
     "MCP transport bridges — stdio, HTTP/SSE, format conversion"),
    ("mcp-security", "ar.domain = 'mcp' AND ar.subcategory = 'security'",
     "MCP auth and credential management tools"),
    ("mcp-framework", "ar.domain = 'mcp' AND ar.subcategory = 'framework'",
     "MCP server frameworks and SDKs"),
    ("mcp-ide", "ar.domain = 'mcp' AND ar.subcategory = 'ide'",
     "MCP IDE and domain-specific bridges"),
    ("agents", "ar.domain = 'agents'",
     "Agent frameworks, orchestration, and autonomous systems"),
    ("ai-coding", "ar.domain = 'ai-coding'",
     "AI coding assistants, code generation, and developer tools"),
    ("nlp", "ar.domain = 'nlp'",
     "NLP tools, text processing, and language understanding"),
    ("llm-tools", "ar.domain = 'llm-tools'",
     "LLM tooling — proxies, routers, prompt engineering, eval"),
    ("computer-vision", "ar.domain = 'computer-vision'",
     "Computer vision, image/video understanding, multimodal AI"),
]

LANDSCAPE_PROMPT = """\
You are an AI infrastructure analyst writing a weekly ecosystem layer brief.

Write a landscape overview for the "{layer}" layer ({description}).

Based on the repo data below, your brief must:
1. Identify the dominant project(s) by stars and downloads
2. Name the fastest-growing projects (by star growth and traction score)
3. Identify structural patterns — is this layer consolidating or fragmenting?
4. Flag notable signals: adoption mismatches, new entrants, shifting momentum
5. Call out the traction buckets — which projects are "infrastructure" (high deps, high forks),
   which are "hype" (stars >> downloads), which are "stealth adoption" (downloads >> stars)?

Rules:
- Make specific quantitative claims with real numbers
- Focus on what's HAPPENING this week, not what projects DO
- If the layer is small (<5 repos), note that the ecosystem is nascent
- Maximum 400 words

Top repos in this layer (sorted by stars):
{repos_text}

Breakouts this week (small repos with fastest % growth):
{breakouts_text}

Return valid JSON:
{{"title": "<headline claim, max 120 chars>", "summary": "<the full landscape brief>"}}"""


async def generate_landscape_briefs() -> dict:
    """Generate LLM landscape briefs for each ecosystem layer."""
    if not settings.GEMINI_API_KEY:
        logger.info("No GEMINI_API_KEY — skipping landscape briefs")
        return {"generated": 0, "skipped": "no API key"}

    started_at = datetime.now(timezone.utc)
    total_generated = 0
    errors = 0

    for layer_name, where_clause, description in LANDSCAPE_LAYERS:
        try:
            with engine.connect() as conn:
                # Get top repos in this layer with traction data
                repos = conn.execute(text(f"""
                    SELECT
                        ar.full_name, ar.stars, ar.forks, ar.language,
                        ar.downloads_monthly, ar.dependency_count, ar.commits_30d,
                        ts.traction_score, ts.traction_bucket,
                        dt.dl_trend,
                        COALESCE(gs_now.stars, 0) - COALESCE(gs_prev.stars, 0) AS star_gain_7d
                    FROM ai_repos ar
                    LEFT JOIN projects p ON p.ai_repo_id = ar.id
                    LEFT JOIN mv_traction_score ts ON ts.project_id = p.id
                    LEFT JOIN mv_download_trends dt ON dt.project_id = p.id
                    LEFT JOIN LATERAL (
                        SELECT stars FROM github_snapshots
                        WHERE project_id = p.id
                        ORDER BY snapshot_date DESC LIMIT 1
                    ) gs_now ON true
                    LEFT JOIN LATERAL (
                        SELECT stars FROM github_snapshots
                        WHERE project_id = p.id
                          AND snapshot_date <= (SELECT MAX(snapshot_date) - 7 FROM github_snapshots)
                        ORDER BY snapshot_date DESC LIMIT 1
                    ) gs_prev ON true
                    WHERE {where_clause}
                      AND ar.archived = false
                    ORDER BY ar.stars DESC NULLS LAST
                    LIMIT 30
                """)).fetchall()

                # Get breakouts in this layer
                breakouts = conn.execute(text(f"""
                    WITH then_snap AS (
                        SELECT DISTINCT ON (project_id) project_id, stars AS s1
                        FROM github_snapshots
                        WHERE snapshot_date <= (SELECT MAX(snapshot_date) - 7 FROM github_snapshots)
                        ORDER BY project_id, snapshot_date DESC
                    ),
                    now_snap AS (
                        SELECT DISTINCT ON (project_id) project_id, stars AS s2
                        FROM github_snapshots
                        ORDER BY project_id, snapshot_date DESC
                    )
                    SELECT ar.full_name, then_snap.s1 AS was, now_snap.s2 AS now,
                           now_snap.s2 - then_snap.s1 AS gain,
                           ROUND(100.0 * (now_snap.s2 - then_snap.s1) / NULLIF(then_snap.s1, 0), 1) AS pct
                    FROM ai_repos ar
                    JOIN projects p ON p.ai_repo_id = ar.id
                    JOIN now_snap ON now_snap.project_id = p.id
                    JOIN then_snap ON then_snap.project_id = p.id
                    WHERE {where_clause}
                      AND then_snap.s1 BETWEEN 50 AND 10000
                      AND now_snap.s2 > then_snap.s1
                    ORDER BY pct DESC
                    LIMIT 10
                """)).fetchall()

            if not repos:
                logger.info(f"Landscape layer '{layer_name}': no repos found, skipping")
                continue

            # Format repo data for the prompt
            repo_lines = []
            for r in repos:
                m = r._mapping
                line = (
                    f"{m['full_name']} | ★{m['stars'] or 0} | ↓{m['downloads_monthly'] or 0}/mo | "
                    f"deps:{m['dependency_count'] or 0} | commits30d:{m['commits_30d'] or 0} | "
                    f"traction:{m['traction_score'] or 'n/a'} ({m['traction_bucket'] or 'n/a'}) | "
                    f"dl_trend:{m['dl_trend'] or 'n/a'} | +★7d:{m['star_gain_7d'] or 0}"
                )
                repo_lines.append(line)
            repos_text = "\n".join(repo_lines)

            breakout_lines = []
            for b in breakouts:
                bm = b._mapping
                breakout_lines.append(
                    f"{bm['full_name']} | {bm['was']} → {bm['now']} stars (+{bm['pct']}%)"
                )
            breakouts_text = "\n".join(breakout_lines) if breakout_lines else "(no breakouts this week)"

            # Check staleness via hash
            hash_input = json.dumps([
                {k: r._mapping.get(k) for k in ["full_name", "stars", "downloads_monthly", "traction_score"]}
                for r in repos[:10]
            ], sort_keys=True, default=str)
            new_hash = hashlib.sha256(hash_input.encode()).hexdigest()

            with engine.connect() as conn:
                existing = conn.execute(text("""
                    SELECT generation_hash FROM landscape_briefs WHERE layer = :layer
                """), {"layer": layer_name}).fetchone()

            if existing and existing._mapping["generation_hash"] == new_hash:
                logger.info(f"Landscape '{layer_name}': hash unchanged, skipping")
                continue

            # Generate via LLM
            prompt = LANDSCAPE_PROMPT.format(
                layer=layer_name,
                description=description,
                repos_text=repos_text,
                breakouts_text=breakouts_text,
            )

            result = await call_llm(prompt, max_tokens=2048)
            if not result or not isinstance(result, dict):
                logger.warning(f"Landscape brief for '{layer_name}': LLM returned no valid result")
                errors += 1
                continue

            # Build evidence
            evidence = [
                {"type": "layer_stat", "layer": layer_name, "total_repos": len(repos),
                 "as_of": datetime.now(timezone.utc).isoformat()}
            ]
            for r in repos[:5]:
                m = r._mapping
                evidence.append({
                    "type": "project", "slug": m["full_name"],
                    "metric": "stars", "value": m["stars"] or 0,
                    "as_of": datetime.now(timezone.utc).isoformat(),
                })

            # Upsert
            with engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO landscape_briefs (layer, title, summary, evidence, generation_hash, generated_at, updated_at)
                    VALUES (:layer, :title, :summary, :evidence::jsonb, :hash, NOW(), NOW())
                    ON CONFLICT (layer) DO UPDATE SET
                        title = EXCLUDED.title,
                        summary = EXCLUDED.summary,
                        evidence = EXCLUDED.evidence,
                        generation_hash = EXCLUDED.generation_hash,
                        generated_at = EXCLUDED.generated_at,
                        updated_at = EXCLUDED.updated_at
                """), {
                    "layer": layer_name,
                    "title": result.get("title", "")[:300],
                    "summary": result.get("summary", ""),
                    "evidence": json.dumps(evidence),
                    "hash": new_hash,
                })
                conn.commit()
            total_generated += 1
            logger.info(f"Landscape brief generated: {layer_name}")

        except Exception as e:
            logger.exception(f"Landscape brief for '{layer_name}' failed: {e}")
            errors += 1

    # Sync log
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="landscape_briefs",
            status="success" if not errors else "partial",
            records_written=total_generated,
            error_message=f"{errors} errors" if errors else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    result_dict = {"generated": total_generated, "layers": len(LANDSCAPE_LAYERS), "errors": errors}
    logger.info(f"Landscape brief generation complete: {result_dict}")
    return result_dict


async def main():
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = await generate_landscape_briefs()
    logger.info(f"Landscape briefs: {result}")


if __name__ == "__main__":
    asyncio.run(main())
