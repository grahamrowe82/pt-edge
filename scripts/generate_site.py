"""Generate static AI directory site.

Usage:
    python scripts/generate_site.py [--domain mcp] [--output-dir ./site] [--base-url https://mcp.phasetransitions.ai]

Queries the domain's quality materialized view and renders Jinja2 templates
to static HTML files. Supports: mcp, agents, rag, ai-coding.
"""

import argparse
import math
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import numpy as np
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import text

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db import readonly_engine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_QUALITY_SCORE = 10
PER_PAGE = 100

DOMAIN_CONFIG = {
    "mcp": {
        "view": "mv_mcp_quality",
        "snapshot_table": "mcp_quality_snapshots",
        "snapshot_domain_filter": None,
        "label": "MCP Server",
        "label_plural": "MCP Servers",
        "noun": "server",
        "noun_plural": "servers",
        "description": "Quality-scored directory of MCP servers, updated daily.",
        "explainer": "The Model Context Protocol (MCP) lets AI assistants connect to external tools and services. This directory tracks every MCP server on GitHub, scored daily.",
    },
    "agents": {
        "view": "mv_agents_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "agents",
        "label": "AI Agent",
        "label_plural": "AI Agents",
        "noun": "agent",
        "noun_plural": "agents",
        "description": "Quality-scored directory of AI agent frameworks and tools, updated daily.",
        "explainer": "AI agents are autonomous systems that plan, reason, and execute multi-step tasks using LLMs. This directory tracks agent frameworks, SDKs, and tools.",
    },
    "rag": {
        "view": "mv_rag_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "rag",
        "label": "RAG",
        "label_plural": "RAG Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of retrieval-augmented generation tools, updated daily.",
        "explainer": "Retrieval-augmented generation (RAG) combines LLMs with external knowledge sources for more accurate, grounded responses.",
    },
    "ai-coding": {
        "view": "mv_ai_coding_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "ai-coding",
        "label": "AI Coding",
        "label_plural": "AI Coding Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of AI-powered coding tools, updated daily.",
        "explainer": "AI coding tools assist with code generation, review, completion, and codebase navigation using large language models.",
    },
    "voice-ai": {
        "view": "mv_voice_ai_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "voice-ai",
        "label": "Voice AI",
        "label_plural": "Voice AI Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of voice AI tools — TTS, STT, voice agents, and audio processing.",
        "explainer": "Voice AI covers text-to-speech synthesis, speech recognition, voice cloning, voice agents, and audio processing.",
    },
    "diffusion": {
        "view": "mv_diffusion_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "diffusion",
        "label": "Diffusion",
        "label_plural": "Diffusion Models",
        "noun": "model",
        "noun_plural": "models",
        "description": "Quality-scored directory of diffusion models and image generation tools.",
        "explainer": "Diffusion models generate images, video, and 3D content from text prompts. Includes Stable Diffusion, ComfyUI workflows, and fine-tuning tools.",
    },
    "vector-db": {
        "view": "mv_vector_db_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "vector-db",
        "label": "Vector Database",
        "label_plural": "Vector Databases",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of vector databases and similarity search tools.",
        "explainer": "Vector databases store and query high-dimensional embeddings for semantic search, RAG pipelines, and recommendation systems.",
    },
    "embeddings": {
        "view": "mv_embeddings_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "embeddings",
        "label": "Embeddings",
        "label_plural": "Embedding Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of embedding models, servers, and utilities.",
        "explainer": "Embedding models convert text, images, and code into dense vector representations for search, clustering, and similarity.",
    },
    "prompt-engineering": {
        "view": "mv_prompt_eng_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "prompt-engineering",
        "label": "Prompt Engineering",
        "label_plural": "Prompt Engineering Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of prompt engineering tools, frameworks, and libraries.",
        "explainer": "Prompt engineering tools help design, optimise, and manage prompts for large language models — including frameworks, guardrails, and output parsers.",
    },
    "ml-frameworks": {
        "view": "mv_ml_frameworks_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "ml-frameworks",
        "label": "ML Framework",
        "label_plural": "ML Frameworks",
        "noun": "framework",
        "noun_plural": "frameworks",
        "description": "Quality-scored directory of machine learning frameworks, training libraries, and ML infrastructure.",
        "explainer": "ML frameworks provide the foundational libraries for training, evaluating, and deploying machine learning models.",
    },
    "llm-tools": {
        "view": "mv_llm_tools_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "llm-tools",
        "label": "LLM Tool",
        "label_plural": "LLM Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of large language model tools, wrappers, and utilities.",
        "explainer": "LLM tools include API wrappers, fine-tuning utilities, inference servers, and evaluation frameworks for large language models.",
    },
    "nlp": {
        "view": "mv_nlp_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "nlp",
        "label": "NLP",
        "label_plural": "NLP Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of natural language processing tools and libraries.",
        "explainer": "NLP tools process and analyse human language — text classification, named entity recognition, translation, summarisation, and more.",
    },
    "transformers": {
        "view": "mv_transformers_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "transformers",
        "label": "Transformer",
        "label_plural": "Transformer Models",
        "noun": "model",
        "noun_plural": "models",
        "description": "Quality-scored directory of transformer models, fine-tuning tools, and inference engines.",
        "explainer": "Transformer models and tools for fine-tuning, quantisation, inference optimisation, and deployment of attention-based architectures.",
    },
    "generative-ai": {
        "view": "mv_generative_ai_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "generative-ai",
        "label": "Generative AI",
        "label_plural": "Generative AI Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of generative AI tools, chatbots, and content generation.",
        "explainer": "Generative AI tools create text, images, audio, and other content using foundation models — chatbots, content generators, and creative tools.",
    },
    "computer-vision": {
        "view": "mv_computer_vision_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "computer-vision",
        "label": "Computer Vision",
        "label_plural": "Computer Vision Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of computer vision tools, models, and libraries.",
        "explainer": "Computer vision tools for image classification, object detection, segmentation, OCR, and visual understanding.",
    },
    "data-engineering": {
        "view": "mv_data_engineering_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "data-engineering",
        "label": "Data Engineering",
        "label_plural": "Data Engineering Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of data engineering tools, pipelines, and ETL frameworks.",
        "explainer": "Data engineering tools for building data pipelines, ETL workflows, data quality, and data infrastructure.",
    },
    "mlops": {
        "view": "mv_mlops_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "mlops",
        "label": "MLOps",
        "label_plural": "MLOps Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of MLOps tools for model deployment, monitoring, and lifecycle management.",
        "explainer": "MLOps tools for model deployment, monitoring, experiment tracking, and ML lifecycle management.",
    },
}

TIER_CLASSES = {
    "verified":     "bg-green-100 text-green-800",
    "established":  "bg-blue-100 text-blue-800",
    "emerging":     "bg-yellow-100 text-yellow-800",
    "experimental": "bg-gray-100 text-gray-600",
}

TIER_BAR_COLORS = {
    "verified":     "bg-green-500",
    "established":  "bg-blue-500",
    "emerging":     "bg-yellow-500",
    "experimental": "bg-gray-400",
}

TIER_RANGES = {
    "verified":     "70\u2013100",
    "established":  "50\u201369",
    "emerging":     "30\u201349",
    "experimental": "10\u201329",
}

DIRECTORIES = [
    {"path": "/", "label": "MCP", "domain": "mcp"},
    {"path": "/agents/", "label": "Agents", "domain": "agents"},
    {"path": "/rag/", "label": "RAG", "domain": "rag"},
    {"path": "/ai-coding/", "label": "AI Coding", "domain": "ai-coding"},
    {"path": "/voice-ai/", "label": "Voice AI", "domain": "voice-ai"},
    {"path": "/diffusion/", "label": "Diffusion", "domain": "diffusion"},
    {"path": "/vector-db/", "label": "Vector DB", "domain": "vector-db"},
    {"path": "/embeddings/", "label": "Embeddings", "domain": "embeddings"},
    {"path": "/prompt-engineering/", "label": "Prompts", "domain": "prompt-engineering"},
    {"path": "/ml-frameworks/", "label": "ML Frameworks", "domain": "ml-frameworks"},
    {"path": "/llm-tools/", "label": "LLM Tools", "domain": "llm-tools"},
    {"path": "/nlp/", "label": "NLP", "domain": "nlp"},
    {"path": "/transformers/", "label": "Transformers", "domain": "transformers"},
    {"path": "/generative-ai/", "label": "Gen AI", "domain": "generative-ai"},
    {"path": "/computer-vision/", "label": "CV", "domain": "computer-vision"},
    {"path": "/data-engineering/", "label": "Data Eng", "domain": "data-engineering"},
    {"path": "/mlops/", "label": "MLOps", "domain": "mlops"},
]

# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

def tier_classes(tier):
    return TIER_CLASSES.get(tier, TIER_CLASSES["experimental"])

def tier_bar_color(tier):
    return TIER_BAR_COLORS.get(tier, TIER_BAR_COLORS["experimental"])

def score_bar_color(score, max_score):
    pct = (score or 0) / max_score if max_score else 0
    if pct >= 0.75:
        return "bg-green-500"
    if pct >= 0.5:
        return "bg-blue-500"
    if pct >= 0.25:
        return "bg-yellow-500"
    return "bg-gray-400"

def metrics_paragraph(server):
    """Build a dynamic metrics context paragraph from live data."""
    parts = []
    stars = server.get("stars") or 0
    downloads = server.get("downloads_monthly") or 0
    if stars >= 100 or downloads >= 1000:
        bits = []
        if stars:
            bits.append(f"{stars:,} stars")
        if downloads:
            bits.append(f"{downloads:,} monthly downloads")
        parts.append(" and ".join(bits))
    rev_deps = server.get("reverse_dep_count") or 0
    if rev_deps > 0:
        parts.append(f"Used by {rev_deps:,} other package{'s' if rev_deps != 1 else ''}")
    commits = server.get("commits_30d") or 0
    if commits > 0:
        parts.append(f"Actively maintained with {commits:,} commit{'s' if commits != 1 else ''} in the last 30 days")
    elif server.get("risk_flags") and "stale_6m" in server["risk_flags"]:
        parts.append("No commits in the last 6 months")
    pkgs = []
    if server.get("pypi_package"):
        pkgs.append("PyPI")
    if server.get("npm_package"):
        pkgs.append("npm")
    if pkgs:
        parts.append(f"Available on {' and '.join(pkgs)}")
    if not parts:
        return ""
    return ". ".join(parts) + "."

def decision_paragraph(category_label, servers, noun_plural):
    """Build a decision paragraph for a category page from live data."""
    count = len(servers)
    if count == 0:
        return ""
    verified = [s for s in servers if s.get("quality_tier") == "verified"]
    established = [s for s in servers if s.get("quality_tier") == "established"]
    top = servers[0]
    # Avoid "MongoDB MCP Servers servers" — don't append noun if already in label
    if noun_plural in category_label.lower():
        parts = [f"There are {count} {category_label.lower()} tracked."]
    else:
        parts = [f"There are {count} {category_label.lower()} {noun_plural} tracked."]
    if verified:
        parts.append(f"{len(verified)} score above 70 (verified tier).")
    elif established:
        parts.append(f"{len(established)} score above 50 (established tier).")
    parts.append(
        f"The highest-rated is {top['full_name']} at {int(top['quality_score'])}/100"
        f" with {top['stars'] or 0:,} stars"
        + (f" and {top['downloads_monthly'] or 0:,} monthly downloads" if top.get('downloads_monthly') else "")
        + "."
    )
    active = [s for s in servers[:10] if (s.get("commits_30d") or 0) > 0]
    if active:
        parts.append(f"{len(active)} of the top 10 are actively maintained.")
    return " ".join(parts)

# ---------------------------------------------------------------------------
# Data queries
# ---------------------------------------------------------------------------

def fetch_category_meta(domain):
    """Load display labels and scope definitions from category_centroids."""
    try:
        with readonly_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT label, display_label, description FROM category_centroids
                WHERE domain = :domain
            """), {"domain": domain}).fetchall()
        return {
            r._mapping["label"]: {
                "display_label": r._mapping["display_label"] or r._mapping["label"].replace("-", " ").title(),
                "desc": r._mapping["description"] or "",
            }
            for r in rows
        }
    except Exception:
        return {}

def fetch_global_total():
    """Total ai_repos count across all domains."""
    try:
        with readonly_engine.connect() as conn:
            return conn.execute(text("SELECT COUNT(*) FROM ai_repos")).scalar()
    except Exception:
        return 220000

def fetch_servers(view_name):
    """All qualifying repos from the given quality view."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT full_name, name, description, ai_summary, stars, forks,
                   language, license, archived, category, subcategory,
                   last_pushed_at, pypi_package, npm_package,
                   downloads_monthly, dependency_count, commits_30d,
                   reverse_dep_count,
                   maintenance_score, adoption_score, maturity_score, community_score,
                   quality_score, quality_tier, risk_flags
            FROM {view_name}
            WHERE quality_score >= :min_score
              AND description IS NOT NULL
              AND description != ''
            ORDER BY quality_score DESC NULLS LAST
        """), {"min_score": MIN_QUALITY_SCORE}).fetchall()
    results = []
    for r in rows:
        d = dict(r._mapping)
        if d.get("license") in ("NOASSERTION", ""):
            d["license"] = None
        results.append(d)
    return results


def fetch_trending(view_name, snapshot_table, domain_filter=None):
    """Repos with biggest score improvement since earliest available snapshot."""
    domain_clause = "AND s.domain = :domain_filter" if domain_filter else ""
    params = {"min_score": MIN_QUALITY_SCORE}
    if domain_filter:
        params["domain_filter"] = domain_filter

    with readonly_engine.connect() as conn:
        # Find earliest snapshot date
        date_sql = f"SELECT MIN(snapshot_date) FROM {snapshot_table}"
        if domain_filter:
            date_sql += " WHERE domain = :domain_filter"
        earliest = conn.execute(text(date_sql), params).scalar()
        if not earliest or earliest >= date.today():
            return [], 0

        rows = conn.execute(text(f"""
            SELECT m.full_name, m.name, m.description, m.quality_score,
                   m.quality_score - s.quality_score AS score_delta,
                   m.stars, m.subcategory, m.quality_tier
            FROM {view_name} m
            JOIN ai_repos ar ON ar.full_name = m.full_name
            JOIN {snapshot_table} s ON s.repo_id = ar.id
              AND s.snapshot_date = :earliest_date
              {domain_clause}
            WHERE m.quality_score >= :min_score
              AND m.description IS NOT NULL
              AND m.description != ''
              AND m.quality_score - s.quality_score > 0
            ORDER BY m.quality_score - s.quality_score DESC
            LIMIT 100
        """), {**params, "earliest_date": earliest}).fetchall()

        trending_days = (date.today() - earliest).days
    return [dict(r._mapping) for r in rows], trending_days


# ---------------------------------------------------------------------------
# Site generation
# ---------------------------------------------------------------------------

def build_category_data(servers, category_meta=None):
    """Group servers by subcategory and compute aggregates."""
    meta = category_meta or {}
    by_cat = {}
    for s in servers:
        cat = s.get("subcategory") or "uncategorized"
        by_cat.setdefault(cat, []).append(s)

    categories = []
    for key, group in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        cm = meta.get(key, {})
        categories.append({
            "subcategory": key,
            "label": cm.get("display_label", key.replace("-", " ").title()),
            "desc": cm.get("desc", ""),
            "count": len(group),
            "servers": group,
        })
    return categories


def build_related_lookup(categories):
    lookup = {}
    for cat in categories:
        top = cat["servers"][:6]
        lookup[cat["subcategory"]] = top
    return lookup


def dynamic_threshold(score_a, score_b):
    """Higher-scored repos get a wider comparison window."""
    ms = max(score_a, score_b)
    if ms >= 70: return 0.65
    elif ms >= 50: return 0.72
    elif ms >= 30: return 0.78
    else: return 0.85


def fetch_embeddings_for_repos(full_names):
    """Fetch 1536d embeddings for a list of repos. Small per-category query."""
    if not full_names:
        return {}
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT full_name, embedding_1536::text as emb
            FROM ai_repos
            WHERE full_name = ANY(:names) AND embedding_1536 IS NOT NULL
        """), {"names": list(full_names)}).fetchall()
    result = {}
    for r in rows:
        m = r._mapping
        vec = np.fromstring(m["emb"].strip("[]"), sep=",", dtype=np.float32)
        norm = np.linalg.norm(vec)
        result[m["full_name"]] = vec / norm if norm > 0 else vec
    return result


def build_comparison_pairs(categories, domain):
    """Find comparison-worthy pairs via embedding similarity within each category."""
    all_pairs = []
    for cat in categories:
        servers = cat["servers"]
        if len(servers) < 2:
            continue
        # Limit to top 20 per category to keep queries small
        top = servers[:20]
        names = [s["full_name"] for s in top]
        emb_map = fetch_embeddings_for_repos(names)
        if len(emb_map) < 2:
            continue

        # Build vectors in order
        indexed = [(s, emb_map[s["full_name"]]) for s in top if s["full_name"] in emb_map]
        for i, (a, va) in enumerate(indexed):
            for j, (b, vb) in enumerate(indexed):
                if j <= i:
                    continue
                sim = float(va @ vb)
                thresh = dynamic_threshold(a["quality_score"], b["quality_score"])
                if sim >= thresh:
                    # Ensure A has higher score (or alphabetical if equal)
                    if a["quality_score"] < b["quality_score"]:
                        a, b = b, a
                    slug = f"{a['full_name'].replace('/', '-')}-vs-{b['full_name'].replace('/', '-')}"
                    all_pairs.append({
                        "repo_a": a, "repo_b": b,
                        "similarity": sim,
                        "category": cat["subcategory"],
                        "category_label": cat["label"],
                        "slug": slug,
                    })
    return all_pairs


def fetch_comparison_sentences():
    """Load pre-computed decision sentences."""
    try:
        with readonly_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT a.full_name as a_name, b.full_name as b_name, cs.sentence
                FROM comparison_sentences cs
                JOIN ai_repos a ON a.id = cs.repo_a_id
                JOIN ai_repos b ON b.id = cs.repo_b_id
                WHERE cs.sentence IS NOT NULL
            """)).fetchall()
        result = {}
        for r in rows:
            m = r._mapping
            result[(m["a_name"], m["b_name"])] = m["sentence"]
            result[(m["b_name"], m["a_name"])] = m["sentence"]
        return result
    except Exception:
        return {}


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Path(path).write_text(content)


def generate_sitemap(base_url, base_path, servers, categories, out_dir, comparisons=None):
    prefix = f"{base_url}{base_path}"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f'  <url><loc>{prefix}</loc><changefreq>daily</changefreq><priority>1.0</priority></url>',
        f'  <url><loc>{prefix}servers/</loc><changefreq>daily</changefreq><priority>0.9</priority></url>',
        f'  <url><loc>{prefix}categories/</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>',
        f'  <url><loc>{prefix}trending/</loc><changefreq>daily</changefreq><priority>0.7</priority></url>',
    ]

    for cat in categories:
        lines.append(
            f'  <url><loc>{prefix}categories/{xml_escape(cat["subcategory"])}/</loc>'
            f'<changefreq>weekly</changefreq><priority>0.8</priority></url>'
        )

    for s in servers:
        lastmod = ""
        if s.get("last_pushed_at"):
            if isinstance(s["last_pushed_at"], datetime):
                lastmod = f"<lastmod>{s['last_pushed_at'].strftime('%Y-%m-%d')}</lastmod>"
            elif isinstance(s["last_pushed_at"], date):
                lastmod = f"<lastmod>{s['last_pushed_at'].isoformat()}</lastmod>"
        lines.append(
            f'  <url><loc>{prefix}servers/{xml_escape(s["full_name"])}/</loc>'
            f'{lastmod}<changefreq>weekly</changefreq><priority>0.6</priority></url>'
        )

    for pair in (comparisons or []):
        lines.append(
            f'  <url><loc>{prefix}compare/{xml_escape(pair["slug"])}/</loc>'
            f'<changefreq>weekly</changefreq><priority>0.7</priority></url>'
        )

    lines.append('</urlset>')
    write_file(os.path.join(out_dir, "sitemap.xml"), "\n".join(lines))


def generate_robots(base_url, base_path, out_dir):
    content = f"User-agent: *\nAllow: /\n\nSitemap: {base_url}{base_path}sitemap.xml\n"
    write_file(os.path.join(out_dir, "robots.txt"), content)


def main():
    parser = argparse.ArgumentParser(description="Generate static AI directory site")
    parser.add_argument("--domain", default="mcp", choices=list(DOMAIN_CONFIG.keys()),
                        help="Domain to generate (default: mcp)")
    parser.add_argument("--output-dir", default="./site", help="Output directory")
    parser.add_argument("--base-url", default="https://mcp.phasetransitions.ai",
                        help="Base URL for canonical links")
    args = parser.parse_args()

    domain = args.domain
    cfg = DOMAIN_CONFIG[domain]
    out_dir = args.output_dir
    base_url = args.base_url.rstrip("/")
    # MCP is at root, others get a path prefix
    base_path = "/" if domain == "mcp" else f"/{domain}/"
    t0 = time.time()

    print(f"Generating {cfg['label']} directory (domain={domain})...")

    # Set up Jinja2
    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    env.globals["tier_classes"] = tier_classes
    env.globals["tier_bar_color"] = tier_bar_color
    env.globals["score_bar_color"] = score_bar_color
    env.globals["metrics_paragraph"] = metrics_paragraph
    env.globals["decision_paragraph"] = decision_paragraph
    env.globals["base_url"] = base_url
    env.globals["base_path"] = base_path.rstrip("/")
    env.globals["directories"] = DIRECTORIES

    # Global total for footer context
    global_total = fetch_global_total()

    # Domain-specific context passed to all templates
    domain_ctx = {
        "domain": domain,
        "domain_label": cfg["label"],
        "domain_label_plural": cfg["label_plural"],
        "noun": cfg["noun"],
        "noun_plural": cfg["noun_plural"],
        "domain_description": cfg["description"],
        "domain_explainer": cfg.get("explainer", ""),
        "global_total": f"{global_total:,}",
    }

    # Phase 1: Query data
    print(f"  Fetching {cfg['noun_plural']}...")
    servers = fetch_servers(cfg["view"])
    total_count = len(servers)
    print(f"  {total_count} qualifying {cfg['noun_plural']}")

    print("  Fetching trending...")
    trending_days = 0
    try:
        trending, trending_days = fetch_trending(
            cfg["view"], cfg["snapshot_table"], cfg["snapshot_domain_filter"]
        )
    except Exception as e:
        print(f"  Trending query failed: {e}")
        trending = []
    print(f"  {len(trending)} trending {cfg['noun_plural']} ({trending_days}d window)")

    # Build derived data
    category_meta = fetch_category_meta(domain)
    categories = build_category_data(servers, category_meta)
    related_lookup = build_related_lookup(categories)

    tier_counts = {}
    for s in servers:
        t = s["quality_tier"]
        tier_counts[t] = tier_counts.get(t, 0) + 1

    tiers = {}
    for t_name in ["verified", "established", "emerging", "experimental"]:
        tiers[t_name] = {
            "count": tier_counts.get(t_name, 0),
            "classes": TIER_CLASSES[t_name],
            "range": TIER_RANGES[t_name],
        }

    ctx = {"total_count": total_count, **domain_ctx}

    # Phase 2: Render pages
    print("  Generating homepage...")
    write_file(
        os.path.join(out_dir, "index.html"),
        env.get_template("index.html").render(
            top_servers=servers[:20],
            tiers=tiers,
            categories=[{"subcategory": c["subcategory"], "label": c["label"], "count": c["count"]} for c in categories],
            **ctx,
        ),
    )

    print("  Generating index pages...")
    total_pages = math.ceil(total_count / PER_PAGE)
    index_tpl = env.get_template("servers_index.html")
    for page in range(1, total_pages + 1):
        offset = (page - 1) * PER_PAGE
        page_servers = servers[offset:offset + PER_PAGE]
        path = os.path.join(out_dir, "servers", "index.html") if page == 1 else \
               os.path.join(out_dir, "servers", "page", str(page), "index.html")
        write_file(path, index_tpl.render(
            servers=page_servers, page=page, total_pages=total_pages,
            offset=offset, per_page=PER_PAGE, **ctx,
        ))
    print(f"  {total_pages} index pages")

    print(f"  Generating {cfg['noun']} detail pages...")
    detail_tpl = env.get_template("server_detail.html")
    last_owner = None
    for i, s in enumerate(servers):
        parts = s["full_name"].split("/", 1)
        if len(parts) != 2:
            continue
        owner, repo = parts
        cat_key = s.get("subcategory") or "uncategorized"
        related = [r for r in related_lookup.get(cat_key, [])
                   if r["full_name"] != s["full_name"]][:5]

        path = os.path.join(out_dir, "servers", owner, repo, "index.html")
        if owner != last_owner:
            os.makedirs(os.path.join(out_dir, "servers", owner), exist_ok=True)
            last_owner = owner
        write_file(path, detail_tpl.render(server=s, related_servers=related, **ctx))

        if (i + 1) % 5000 == 0:
            print(f"  {i + 1}/{total_count} detail pages...")
    print(f"  {total_count} detail pages")

    print("  Generating category pages...")
    cat_tpl = env.get_template("category.html")
    write_file(
        os.path.join(out_dir, "categories", "index.html"),
        env.get_template("categories_index.html").render(
            categories=[{"subcategory": c["subcategory"], "label": c["label"], "desc": c["desc"], "count": c["count"]} for c in categories],
            **ctx,
        ),
    )
    for cat in categories:
        write_file(
            os.path.join(out_dir, "categories", cat["subcategory"], "index.html"),
            cat_tpl.render(subcategory=cat["subcategory"], category_label=cat["label"],
                           category_desc=cat["desc"], servers=cat["servers"], **ctx),
        )
    print(f"  {len(categories)} category pages")

    print("  Generating trending page...")
    write_file(
        os.path.join(out_dir, "trending", "index.html"),
        env.get_template("trending.html").render(trending=trending, trending_days=trending_days, **ctx),
    )

    print("  Generating about + methodology pages...")
    write_file(
        os.path.join(out_dir, "about", "index.html"),
        env.get_template("about.html").render(**ctx),
    )
    write_file(
        os.path.join(out_dir, "methodology", "index.html"),
        env.get_template("methodology.html").render(**ctx),
    )

    # Comparison pages
    print("  Building comparison pairs...")
    comparison_pairs = build_comparison_pairs(categories, domain)
    print(f"  {len(comparison_pairs)} comparison pairs found")

    if comparison_pairs:
        # Write placeholder rows for backfill (no LLM, just repo_a_id + repo_b_id)
        print("  Writing comparison placeholders for backfill...")
        try:
            names = set()
            for p in comparison_pairs:
                names.add(p["repo_a"]["full_name"])
                names.add(p["repo_b"]["full_name"])
            with readonly_engine.connect() as conn:
                rows = conn.execute(text("SELECT id, full_name FROM ai_repos WHERE full_name = ANY(:names)"),
                                    {"names": list(names)}).fetchall()
            id_map = {r._mapping["full_name"]: r._mapping["id"] for r in rows}

            with engine.connect() as conn:
                for p in comparison_pairs:
                    a_id = id_map.get(p["repo_a"]["full_name"])
                    b_id = id_map.get(p["repo_b"]["full_name"])
                    if a_id and b_id:
                        conn.execute(text("""
                            INSERT INTO comparison_sentences (repo_a_id, repo_b_id, domain, subcategory)
                            VALUES (:a, :b, :domain, :cat)
                            ON CONFLICT (repo_a_id, repo_b_id) DO NOTHING
                        """), {"a": a_id, "b": b_id, "domain": domain, "cat": p["category"]})
                conn.commit()
            print(f"  {len(comparison_pairs)} placeholders written")
        except Exception as e:
            print(f"  Placeholder write failed (non-fatal): {e}")

        print("  Fetching decision sentences...")
        sentences = fetch_comparison_sentences()
        print(f"  {len(sentences)} pre-computed sentences available")

        print("  Generating comparison pages...")
        comp_tpl = env.get_template("comparison.html")
        for i, pair in enumerate(comparison_pairs):
            sentence = sentences.get((pair["repo_a"]["full_name"], pair["repo_b"]["full_name"]), "")
            write_file(
                os.path.join(out_dir, "compare", pair["slug"], "index.html"),
                comp_tpl.render(
                    repo_a=pair["repo_a"], repo_b=pair["repo_b"],
                    slug=pair["slug"], sentence=sentence,
                    comparison_category=pair["category"],
                    category_label=pair["category_label"],
                    **ctx,
                ),
            )
            if (i + 1) % 1000 == 0:
                print(f"  {i + 1}/{len(comparison_pairs)} comparison pages...")
        print(f"  {len(comparison_pairs)} comparison pages")

    # Phase 3: SEO assets
    print("  Generating sitemap.xml + robots.txt...")
    generate_sitemap(base_url, base_path, servers, categories, out_dir, comparison_pairs)
    generate_robots(base_url, base_path, out_dir)

    elapsed = time.time() - t0
    total_files = total_count + total_pages + len(categories) + len(comparison_pairs) + 5
    print(f"\nDone! {cfg['label']}: {total_files} files in {elapsed:.1f}s → {out_dir}/")


if __name__ == "__main__":
    main()
