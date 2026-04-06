"""Enrich task: generate a repo brief via Gemini.

Pure enrich — reads repo metadata + quality scores from the database,
calls Gemini, writes the brief to repo_briefs. No external API calls.

This handles a single repo (not a batch). The prompt is designed for
batch input but works fine with a single repo line.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine
from app.ingest.llm import call_llm

logger = logging.getLogger(__name__)

DOMAIN_VIEW_MAP = {
    "mcp": "mv_mcp_quality", "agents": "mv_agents_quality",
    "rag": "mv_rag_quality", "ai-coding": "mv_ai_coding_quality",
    "voice-ai": "mv_voice_ai_quality", "diffusion": "mv_diffusion_quality",
    "vector-db": "mv_vector_db_quality", "embeddings": "mv_embeddings_quality",
    "prompt-engineering": "mv_prompt_eng_quality",
    "ml-frameworks": "mv_ml_frameworks_quality",
    "llm-tools": "mv_llm_tools_quality", "nlp": "mv_nlp_quality",
    "transformers": "mv_transformers_quality",
    "generative-ai": "mv_generative_ai_quality",
    "computer-vision": "mv_computer_vision_quality",
    "data-engineering": "mv_data_engineering_quality",
    "mlops": "mv_mlops_quality", "perception": "mv_perception_quality",
}

REPO_BRIEF_PROMPT = """\
You are a technology consultant advising people on whether to depend on \
open-source projects. Your readers are scientists, business managers, and \
engineers — not developers. Be direct and decisive, no hedging.

For each repository below, assess:
1. **Dependability**: Active development? Broad adoption? Organisation or solo maintainer?
2. **Maturity signal**: One of: "Production-ready" (active, widely adopted, packaged), \
"Mature and stable" (established, reliable), "Research-grade" (solid for research, \
not production), "Early-stage" (promising, unproven), or "Stalled" (inactive, abandonment risk)

Output format — return valid JSON only:
[{{"id": <repo_id>, "title": "<adoption signal + key fact, max 120 chars>", "summary": "<2 sentences, max 50 words. State facts, not speculation. Be direct.>", "evidence": [{{"type": "project", "slug": "<full_name>", "metric": "<metric_name>", "value": <number>, "as_of": "{today}"}}]}}]

Rules:
- Interpret the quality scores for a non-technical reader — don't repeat the numbers
- The quality score (0-100) synthesises maintenance, adoption, maturity, and community
- A high adoption score with low maintenance means "widely used but development is slowing"
- 0 commits in 30 days does NOT mean stalled — many stable projects release infrequently. \
Check last_commit date: if within 6 months, it's active or stable, not stalled
- "Stalled" only when last commit is >1 year ago AND adoption is low
- 0 downloads may mean untracked, not unused — check stars and forks
- A project created years ago with steady stars is more dependable than a recent one
- Research paper implementations are valuable for research even with few stars
- Title must include the maturity signal and one specific number
- Do NOT describe what the project does — that's covered elsewhere on the page
- Evidence array must include every metric cited

Repositories:
{repos_text}"""


async def handle_enrich_repo_brief(task: dict) -> dict:
    """Generate a brief for a single repo.

    subject_id is the ai_repos.id (as a string).

    Returns:
        {"status": "generated"} on success
        {"status": "repo_not_found"} if repo doesn't exist

    Raises:
        RuntimeError on LLM failure — triggers requeue
    """
    repo_id = int(task["subject_id"])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Read repo metadata
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT id, full_name, name, domain, subcategory,
                   COALESCE(stars, 0) AS stars,
                   COALESCE(downloads_monthly, 0) AS monthly_downloads,
                   COALESCE(forks, 0) AS forks,
                   COALESCE(commits_30d, 0) AS commits_30d,
                   description, license, last_pushed_at, created_at
            FROM ai_repos WHERE id = :id
        """), {"id": repo_id}).mappings().fetchone()

    if not row:
        return {"status": "repo_not_found"}

    r = dict(row)

    # Fetch quality scores from domain-specific MV
    qs = ms = ads = mats = cs = 0
    view = DOMAIN_VIEW_MAP.get(r.get("domain", ""))
    if view:
        with engine.connect() as conn:
            qrow = conn.execute(text(f"""
                SELECT quality_score, maintenance_score, adoption_score,
                       maturity_score, community_score
                FROM {view} WHERE id = :id
            """), {"id": repo_id}).mappings().fetchone()
            if qrow:
                qs = qrow.get("quality_score", 0) or 0
                ms = qrow.get("maintenance_score", 0) or 0
                ads = qrow.get("adoption_score", 0) or 0
                mats = qrow.get("maturity_score", 0) or 0
                cs = qrow.get("community_score", 0) or 0

    # Format single repo line (same format as batch pipeline)
    last_push = str(r.get("last_pushed_at") or "unknown")[:10]
    created = str(r.get("created_at") or "unknown")[:10]
    repo_line = (
        f"{r['id']} | {r['full_name']} | {r.get('domain', 'n/a')} | "
        f"★{r['stars']} | ↓{r['monthly_downloads']} | "
        f"forks:{r['forks']} | commits_30d:{r['commits_30d']} | "
        f"created:{created} | last_commit:{last_push} | "
        f"license:{r.get('license') or 'none'} | "
        f"quality:{qs}/100 (maint:{ms}/25 adopt:{ads}/25 mature:{mats}/25 community:{cs}/25) | "
        f"{(r.get('description') or '')[:100]}"
    )

    prompt = REPO_BRIEF_PROMPT.format(repos_text=repo_line, today=today)
    result = await call_llm(prompt, max_tokens=4096)

    if not result or not isinstance(result, list) or len(result) == 0:
        raise RuntimeError(f"LLM returned no usable brief for repo {repo_id}")

    brief = result[0]
    title = brief.get("title", "")[:300]
    summary = brief.get("summary", "")
    evidence = brief.get("evidence", [])

    if not title or not summary:
        raise RuntimeError(f"LLM brief missing title/summary for repo {repo_id}")

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

    return {"status": "generated"}
