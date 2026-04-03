"""Validate novel concepts detected from YC Lightcone transcripts against PT-Edge data.

Tests 5 hypotheses by looking for behavioural traces in 226K+ repos,
HN posts, newsletter mentions, and dependency data.
"""
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import engine
from sqlalchemy import text

logger = logging.getLogger(__name__)


def query(sql: str, params: dict | None = None) -> list[dict]:
    """Run a read-only query, return list of dicts."""
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        cols = list(result.keys())
        return [dict(zip(cols, row)) for row in result.fetchall()]


# ─── Concept 1: Domain Expert Direct-Build ───────────────────────────


def validate_concept_1() -> dict:
    logger.info("=== Concept 1: Domain Expert Direct-Build ===")
    findings = []
    data = {}

    # A) New-builder cohort by month
    cohort = query("""
        SELECT DATE_TRUNC('month', created_at)::date as month,
               COUNT(*) as high_velocity_new_builders
        FROM ai_repos
        WHERE commits_30d > 300
          AND github_owner IN (
            SELECT github_owner FROM ai_repos
            GROUP BY github_owner HAVING COUNT(*) <= 2
          )
          AND created_at >= '2025-01-01'
        GROUP BY 1 ORDER BY 1
    """)
    data["new_builder_cohort"] = cohort
    total_new = sum(r["high_velocity_new_builders"] for r in cohort)
    findings.append(f"{total_new} high-velocity new builders (>300 commits/30d, <=2 repos) since Jan 2025")

    # B) Velocity distribution shift by year
    velocity = query("""
        SELECT EXTRACT(YEAR FROM created_at)::int as year,
               COUNT(*) as total_repos,
               COUNT(*) FILTER (WHERE commits_30d > 100) as over_100,
               COUNT(*) FILTER (WHERE commits_30d > 300) as over_300,
               COUNT(*) FILTER (WHERE commits_30d > 600) as over_600,
               ROUND(100.0 * COUNT(*) FILTER (WHERE commits_30d > 300) / NULLIF(COUNT(*), 0), 2) as pct_over_300
        FROM ai_repos
        WHERE created_at >= '2024-01-01'
        GROUP BY 1 ORDER BY 1
    """)
    data["velocity_distribution"] = velocity
    for row in velocity:
        findings.append(f"{row['year']}: {row['pct_over_300']}% of repos have >300 commits/30d ({row['over_300']} repos)")

    # C) Claude Code / vibe coding fingerprint
    ai_assisted = query("""
        SELECT full_name, stars, commits_30d, created_at::date as created,
               LEFT(description, 120) as desc_preview
        FROM ai_repos
        WHERE (description ILIKE '%claude code%' OR description ILIKE '%vibe cod%'
               OR description ILIKE '%cursor%agent%' OR topics::text ILIKE '%vibe-coding%')
          AND commits_30d > 200
        ORDER BY commits_30d DESC
        LIMIT 15
    """)
    data["ai_assisted_builders"] = ai_assisted
    findings.append(f"{len(ai_assisted)} repos self-identify as AI-assisted with >200 commits/30d")

    # D) Top velocity repos from new accounts (the actual exemplars)
    exemplars = query("""
        SELECT ar.full_name, ar.stars, ar.commits_30d, ar.created_at::date as created,
               ar.forks, LEFT(ar.description, 100) as desc_preview,
               owner_repos.repo_count
        FROM ai_repos ar
        JOIN (SELECT github_owner, COUNT(*) as repo_count FROM ai_repos GROUP BY github_owner) owner_repos
          ON ar.github_owner = owner_repos.github_owner
        WHERE ar.commits_30d > 400
          AND owner_repos.repo_count <= 2
          AND ar.created_at >= '2025-06-01'
        ORDER BY ar.commits_30d DESC
        LIMIT 15
    """)
    data["exemplars"] = exemplars
    if exemplars:
        findings.append(f"Top exemplar: {exemplars[0]['full_name']} — {exemplars[0]['commits_30d']} commits/30d, {exemplars[0]['stars']} stars")

    return {
        "concept": "Domain Expert Direct-Build",
        "findings": findings,
        "data": data,
    }


# ─── Concept 2: Agent-Native Infrastructure ──────────────────────────


def validate_concept_2() -> dict:
    logger.info("=== Concept 2: Agent-Native Infrastructure ===")
    findings = []
    data = {}

    # A) Direct keyword search
    infra_repos = query("""
        SELECT full_name, stars, domain, subcategory, created_at::date as created,
               commits_30d, LEFT(description, 150) as desc_preview
        FROM ai_repos
        WHERE (description ILIKE '%agent%email%' OR description ILIKE '%agent%identity%'
               OR description ILIKE '%agent%credential%' OR description ILIKE '%agent native%'
               OR description ILIKE '%agent%phone%' OR description ILIKE '%agent%wallet%'
               OR description ILIKE '% for agents%' OR description ILIKE '%agent-native%'
               OR description ILIKE '%agent%inbox%')
          AND stars >= 5
        ORDER BY stars DESC
        LIMIT 30
    """)
    data["infra_repos"] = infra_repos
    findings.append(f"{len(infra_repos)} repos with agent-native infrastructure signals (stars >= 5)")

    # B) Subcategory scatter (pre-categorical = scattered across many subcategories)
    if infra_repos:
        subcats = {}
        for r in infra_repos:
            key = f"{r['domain']}:{r['subcategory']}"
            subcats[key] = subcats.get(key, 0) + 1
        data["subcategory_scatter"] = subcats
        findings.append(f"Scattered across {len(subcats)} subcategories — pre-categorical")

    # C) Creation timeline (clustering = emerging)
    creation_timeline = query("""
        SELECT DATE_TRUNC('month', created_at)::date as month, COUNT(*) as new_repos
        FROM ai_repos
        WHERE (description ILIKE '%agent%email%' OR description ILIKE '%agent%identity%'
               OR description ILIKE '%agent%credential%' OR description ILIKE '%agent native%'
               OR description ILIKE '% for agents%' OR description ILIKE '%agent-native%')
          AND stars >= 5 AND created_at >= '2025-01-01'
        GROUP BY 1 ORDER BY 1
    """)
    data["creation_timeline"] = creation_timeline

    # D) HN coverage
    hn = query("""
        SELECT title, points, num_comments, posted_at::date
        FROM hn_posts
        WHERE title ILIKE '%agent%native%' OR title ILIKE '%infrastructure%agent%'
           OR title ILIKE '%agent%identity%' OR title ILIKE '%agent%email%'
        ORDER BY posted_at DESC LIMIT 10
    """)
    data["hn_posts"] = hn
    findings.append(f"{len(hn)} HN posts about agent-native infrastructure")

    # E) Newsletter coverage
    newsletters = query("""
        SELECT COUNT(*) as mentions, COUNT(DISTINCT feed_slug) as feeds
        FROM newsletter_mentions
        WHERE ((title || ' ' || COALESCE(summary, '')) ILIKE '%agent%native%'
            OR (title || ' ' || COALESCE(summary, '')) ILIKE '%agent%identity%'
            OR (title || ' ' || COALESCE(summary, '')) ILIKE '%agent%infrastructure%')
          AND published_at >= NOW() - INTERVAL '90 days'
    """)
    if newsletters:
        findings.append(f"Newsletter coverage (90d): {newsletters[0]['mentions']} mentions across {newsletters[0]['feeds']} feeds")
    data["newsletter_coverage"] = newsletters

    return {
        "concept": "Agent-Native Infrastructure",
        "findings": findings,
        "data": data,
    }


# ─── Concept 3: Harness vs Fine-Tuning Shift ────────────────────────


def validate_concept_3() -> dict:
    logger.info("=== Concept 3: Harness vs Fine-Tuning Shift ===")
    findings = []
    data = {}

    # A) Fine-tuning creation velocity
    ft_velocity = query("""
        SELECT DATE_TRUNC('month', created_at)::date as month, COUNT(*) as new_repos
        FROM ai_repos
        WHERE subcategory IN ('llm-fine-tuning', 'lora-qlora-fine-tuning',
              'gpt2-pretraining-fine-tuning', 'llm-fine-tuning-frameworks',
              'model-fine-tuning-methods', 'gpt-model-fine-tuning', 'chatglm-fine-tuning')
          AND created_at >= '2025-01-01'
        GROUP BY 1 ORDER BY 1
    """)
    data["fine_tuning_velocity"] = ft_velocity

    # Harness/optimization creation velocity
    harness_velocity = query("""
        SELECT DATE_TRUNC('month', created_at)::date as month, COUNT(*) as new_repos
        FROM ai_repos
        WHERE subcategory IN ('prompt-optimization-systems', 'evolutionary-prompt-optimization',
              'reasoning-chain-frameworks', 'structured-reasoning-frameworks',
              'llm-reasoning-research', 'logic-reasoning-systems')
          AND created_at >= '2025-01-01'
        GROUP BY 1 ORDER BY 1
    """)
    data["harness_velocity"] = harness_velocity

    ft_total = sum(r["new_repos"] for r in ft_velocity)
    h_total = sum(r["new_repos"] for r in harness_velocity)
    findings.append(f"Fine-tuning repos since Jan 2025: {ft_total}")
    findings.append(f"Harness/reasoning repos since Jan 2025: {h_total}")

    # B) Check for Poetic
    poetic = query("""
        SELECT full_name, stars, commits_30d, created_at::date, downloads_monthly
        FROM ai_repos
        WHERE full_name ILIKE '%poetic%' OR full_name ILIKE '%poetiq%'
           OR description ILIKE '%recursive self-improvement%'
        ORDER BY stars DESC LIMIT 5
    """)
    data["poetic_search"] = poetic
    findings.append(f"Poetic/recursive self-improvement repos found: {len(poetic)}")

    # C) HN on fine-tuning frustration
    hn_ft = query("""
        SELECT title, points, num_comments, posted_at::date
        FROM hn_posts
        WHERE (title ILIKE '%fine-tun%' OR title ILIKE '%finetun%')
          AND posted_at >= NOW() - INTERVAL '180 days'
        ORDER BY points DESC LIMIT 10
    """)
    data["hn_fine_tuning"] = hn_ft
    findings.append(f"{len(hn_ft)} HN posts about fine-tuning in last 180 days")

    # D) Download comparison
    downloads = query("""
        SELECT
          SUM(downloads_monthly) FILTER (WHERE subcategory IN ('llm-fine-tuning', 'lora-qlora-fine-tuning')) as ft_downloads,
          SUM(downloads_monthly) FILTER (WHERE subcategory IN ('prompt-optimization-systems', 'evolutionary-prompt-optimization', 'reasoning-chain-frameworks')) as harness_downloads
        FROM ai_repos
    """)
    data["downloads"] = downloads
    if downloads:
        findings.append(f"Fine-tuning downloads/mo: {downloads[0]['ft_downloads'] or 0:,}")
        findings.append(f"Harness/optimization downloads/mo: {downloads[0]['harness_downloads'] or 0:,}")

    return {
        "concept": "Harness vs Fine-Tuning Shift",
        "findings": findings,
        "data": data,
    }


# ─── Concept 4: Frontier-First Product Design ───────────────────────


def validate_concept_4() -> dict:
    logger.info("=== Concept 4: Frontier-First Product Design ===")
    findings = []
    data = {}

    # A) Future-oriented README language
    future_lang = query("""
        SELECT full_name, stars, LEFT(ai_summary, 200) as summary_preview
        FROM ai_repos
        WHERE (ai_summary ILIKE '%future model%' OR ai_summary ILIKE '%model-agnostic%'
               OR ai_summary ILIKE '%forward-compatible%' OR ai_summary ILIKE '%any LLM%'
               OR ai_summary ILIKE '%swap%model%' OR ai_summary ILIKE '%multiple provider%'
               OR description ILIKE '%model-agnostic%' OR description ILIKE '%any llm provider%')
          AND stars >= 50
        ORDER BY stars DESC
        LIMIT 15
    """)
    data["future_language_repos"] = future_lang
    findings.append(f"{len(future_lang)} repos with model-agnostic/future-oriented language (stars >= 50)")

    # B) LiteLLM dependency growth
    litellm_deps = query("""
        SELECT COUNT(DISTINCT repo_id) as repos_using_litellm
        FROM package_deps
        WHERE dep_name = 'litellm'
    """)
    data["litellm_dependents"] = litellm_deps
    if litellm_deps:
        findings.append(f"{litellm_deps[0]['repos_using_litellm']} repos depend on LiteLLM")

    # Also check other model-routing deps
    routing_deps = query("""
        SELECT dep_name, COUNT(DISTINCT repo_id) as dependents
        FROM package_deps
        WHERE dep_name IN ('litellm', 'openrouter', 'langfuse', 'portkey-ai')
        GROUP BY dep_name
        ORDER BY dependents DESC
    """)
    data["routing_deps"] = routing_deps

    # C) Multi-provider repos
    multi_provider = query("""
        SELECT COUNT(*) as multi_provider_repos
        FROM ai_repos
        WHERE (description ILIKE '%openai%' AND description ILIKE '%anthropic%' AND description ILIKE '%gemini%')
          OR (description ILIKE '%multiple%provider%' OR description ILIKE '%multi%provider%')
          AND stars >= 20
    """)
    data["multi_provider"] = multi_provider
    if multi_provider:
        findings.append(f"{multi_provider[0]['multi_provider_repos']} repos support multiple LLM providers")

    return {
        "concept": "Frontier-First Product Design",
        "findings": findings,
        "data": data,
    }


# ─── Concept 5: Agent-Native Documentation ──────────────────────────


def validate_concept_5() -> dict:
    logger.info("=== Concept 5: Agent-Native Documentation ===")
    findings = []
    data = {}

    # A) llms.txt adoption timeline
    llms_txt = query("""
        SELECT DATE_TRUNC('month', created_at)::date as month, COUNT(*) as repos
        FROM ai_repos
        WHERE (description ILIKE '%llms.txt%' OR topics::text ILIKE '%llms.txt%'
               OR description ILIKE '%llms-txt%')
          AND created_at >= '2025-01-01'
        GROUP BY 1 ORDER BY 1
    """)
    data["llms_txt_timeline"] = llms_txt
    total_llms = sum(r["repos"] for r in llms_txt)
    findings.append(f"{total_llms} repos mentioning llms.txt since Jan 2025")

    # B) Doc platform repos with agent features
    doc_platforms = query("""
        SELECT full_name, stars, LEFT(description, 150) as desc_preview, created_at::date
        FROM ai_repos
        WHERE (full_name ILIKE '%mintlify%' OR full_name ILIKE '%readme%' OR full_name ILIKE '%gitbook%'
               OR description ILIKE '%documentation%agent%' OR description ILIKE '%docs%llm%'
               OR description ILIKE '%documentation%ai%pars%')
          AND stars >= 20
        ORDER BY stars DESC
        LIMIT 15
    """)
    data["doc_platform_repos"] = doc_platforms
    findings.append(f"{len(doc_platforms)} repos related to doc platforms + AI/agent features")

    # C) MCP quality vs description structure
    # Test: do higher-quality MCP servers have longer/more structured descriptions?
    mcp_doc_quality = query("""
        SELECT
          CASE WHEN LENGTH(COALESCE(ai_summary, '')) > 200 THEN 'detailed_summary'
               WHEN LENGTH(COALESCE(ai_summary, '')) > 50 THEN 'brief_summary'
               ELSE 'no_summary' END as summary_quality,
          COUNT(*) as repos,
          ROUND(AVG(stars)) as avg_stars,
          ROUND(AVG(downloads_monthly)) as avg_downloads,
          ROUND(AVG(forks)) as avg_forks
        FROM ai_repos
        WHERE domain = 'mcp' AND stars >= 5
        GROUP BY 1 ORDER BY avg_stars DESC
    """)
    data["mcp_doc_quality"] = mcp_doc_quality
    findings.append("MCP quality correlation: repos with detailed summaries vs brief vs none")

    # D) "X for agents" documentation tools
    doc_for_agents = query("""
        SELECT full_name, stars, LEFT(description, 150) as desc_preview
        FROM ai_repos
        WHERE (description ILIKE '%document%for%agent%' OR description ILIKE '%docs%for%agent%'
               OR description ILIKE '%agent%readable%' OR description ILIKE '%llm%readable%'
               OR description ILIKE '%machine%readable%doc%')
          AND stars >= 5
        ORDER BY stars DESC
        LIMIT 10
    """)
    data["doc_for_agents"] = doc_for_agents
    findings.append(f"{len(doc_for_agents)} repos building agent-readable documentation tools")

    return {
        "concept": "Agent-Native Documentation",
        "findings": findings,
        "data": data,
    }


# ─── Report generation ───────────────────────────────────────────────


def generate_report(results: list[dict], output_path: str) -> None:
    lines = [
        "# Concept Validation Report",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "Testing 5 pre-narrative concepts from YC Lightcone transcripts against PT-Edge data.",
        "",
        "---",
        "",
    ]

    for r in results:
        lines.extend([
            f"## {r['concept']}",
            "",
            "### Key Findings",
            "",
        ])
        for f in r["findings"]:
            lines.append(f"- {f}")
        lines.append("")

        # Render data tables
        for key, val in r["data"].items():
            if isinstance(val, list) and val and isinstance(val[0], dict):
                lines.append(f"### {key.replace('_', ' ').title()}")
                lines.append("")
                cols = list(val[0].keys())
                lines.append("| " + " | ".join(cols) + " |")
                lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
                for row in val[:15]:
                    cells = [str(row.get(c, ""))[:60] for c in cols]
                    lines.append("| " + " | ".join(cells) + " |")
                lines.append("")

        lines.extend(["---", ""])

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines))
    logger.info(f"Report written to {output_path}")


# ─── Main ────────────────────────────────────────────────────────────


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    results = [
        validate_concept_1(),
        validate_concept_2(),
        validate_concept_3(),
        validate_concept_4(),
        validate_concept_5(),
    ]

    output_path = "scratch/concept_validation_report.md"
    generate_report(results, output_path)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in results:
        print(f"\n{r['concept']}:")
        for f in r["findings"][:3]:
            print(f"  • {f}")


if __name__ == "__main__":
    main()
