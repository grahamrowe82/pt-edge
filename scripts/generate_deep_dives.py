"""Generate deep dive insight pages with live metrics.

Usage:
    python scripts/generate_deep_dives.py [--output-dir ./site]

Reads curated deep dives from the deep_dives table, fetches live metrics
for featured repos and categories, then renders Jinja2 template bodies
into static HTML pages under /insights/.
"""

import argparse
import math
import os
import sys
from datetime import date, datetime, timezone
from xml.sax.saxutils import escape as xml_escape

from jinja2 import BaseLoader, Environment, FileSystemLoader
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db import readonly_engine


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

def intcomma(value):
    """Format integer with commas: 6388 → '6,388'."""
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return str(value) if value is not None else "0"


def timeago(dt):
    """Relative time: datetime → '7 months ago'."""
    if dt is None:
        return "unknown"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    days = delta.days
    if days < 1:
        return "today"
    if days < 2:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    remaining_months = (days - years * 365) // 30
    if remaining_months > 0:
        return f"{years}y {remaining_months}m ago"
    return f"{years} year{'s' if years != 1 else ''} ago"


def dateformat(dt, fmt="%B %d, %Y"):
    """Format date: datetime → 'March 30, 2026'."""
    if dt is None:
        return ""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt
    return dt.strftime(fmt)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

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
    {"path": "/ml-frameworks/", "label": "ML", "domain": "ml-frameworks"},
    {"path": "/llm-tools/", "label": "LLM Tools", "domain": "llm-tools"},
    {"path": "/nlp/", "label": "NLP", "domain": "nlp"},
    {"path": "/transformers/", "label": "Transformers", "domain": "transformers"},
    {"path": "/generative-ai/", "label": "Gen AI", "domain": "generative-ai"},
    {"path": "/computer-vision/", "label": "CV", "domain": "computer-vision"},
    {"path": "/data-engineering/", "label": "Data Eng", "domain": "data-engineering"},
    {"path": "/mlops/", "label": "MLOps", "domain": "mlops"},
]

DOMAIN_PATHS = {d["domain"]: d["path"].rstrip("/") for d in DIRECTORIES}


def fetch_deep_dives():
    """All published deep dives."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT slug, title, subtitle, author, primary_domain, domains,
                   meta_description, template_body, featured_repos,
                   featured_categories, published_at
            FROM deep_dives
            WHERE status = 'published'
            ORDER BY published_at DESC NULLS LAST
        """)).fetchall()
    return [dict(r._mapping) for r in rows]


def fetch_repo_metrics(full_names):
    """Live metrics for featured repos from ai_repos + quality scores."""
    if not full_names:
        return {}
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT full_name, name, stars, forks, downloads_monthly,
                   commits_30d, last_pushed_at, language, license,
                   domain, subcategory, description, ai_summary
            FROM ai_repos
            WHERE full_name = ANY(:names)
        """), {"names": list(full_names)}).fetchall()
    repos = {r._mapping["full_name"]: dict(r._mapping) for r in rows}

    # Fetch quality scores from domain-specific views via UNION ALL
    quality_views = [
        "mv_mcp_quality", "mv_agents_quality", "mv_rag_quality",
        "mv_ai_coding_quality", "mv_voice_ai_quality", "mv_diffusion_quality",
        "mv_vector_db_quality", "mv_embeddings_quality", "mv_prompt_eng_quality",
        "mv_ml_frameworks_quality", "mv_llm_tools_quality", "mv_nlp_quality",
        "mv_transformers_quality", "mv_generative_ai_quality",
        "mv_computer_vision_quality", "mv_data_engineering_quality",
        "mv_mlops_quality",
    ]
    union_sql = " UNION ALL ".join(
        f"SELECT full_name, quality_score, quality_tier FROM {v}"
        for v in quality_views
    )
    try:
        with readonly_engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT full_name, quality_score, quality_tier
                FROM ({union_sql}) all_quality
                WHERE full_name = ANY(:names)
            """), {"names": list(full_names)}).fetchall()
        for r in rows:
            fn = r._mapping["full_name"]
            if fn in repos:
                repos[fn]["quality_score"] = r._mapping["quality_score"]
                repos[fn]["quality_tier"] = r._mapping["quality_tier"]
    except Exception as e:
        print(f"    Warning: could not fetch quality scores: {e}")

    return repos


def fetch_category_opportunities(category_keys):
    """Allocation scores for 'domain:subcategory' pairs.

    Returns dict keyed by 'domain:subcategory' with backward-compatible
    fields (opportunity_score, opportunity_tier) plus new EHS/ES scores.
    """
    if not category_keys:
        return {}
    results = {}
    with readonly_engine.connect() as conn:
        for key in category_keys:
            parts = key.split(":", 1)
            if len(parts) != 2:
                continue
            domain, sub = parts
            row = conn.execute(text("""
                SELECT domain, subcategory, ehs, es,
                       opportunity_score, opportunity_tier,
                       repo_count, total_stars, confidence_level,
                       gsc_impressions_7d, gsc_clicks_7d,
                       github_star_velocity_7d, github_new_repos_7d,
                       umami_pageviews_7d,
                       0 AS demand_score, 0 AS quality_gap_score,
                       0 AS concentration_score, 0 AS graveyard_score,
                       0 AS momentum_score, 0 AS stadium_score,
                       0 AS avg_quality_score
                FROM mv_allocation_scores
                WHERE domain = :domain AND subcategory = :sub
            """), {"domain": domain, "sub": sub}).fetchone()
            if row:
                results[key] = dict(row._mapping)
    return results


def fetch_global_total():
    try:
        with readonly_engine.connect() as conn:
            return conn.execute(text("SELECT COUNT(*) FROM ai_repos")).scalar()
    except Exception:
        return 220000


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def domain_path(domain):
    """Get the URL path prefix for a domain."""
    return DOMAIN_PATHS.get(domain, "")


def render_deep_dive(dd, env, out_dir, global_total):
    """Render a single deep dive to static HTML."""
    slug = dd["slug"]
    print(f"  Rendering {slug}...")

    # Fetch live data
    repos = fetch_repo_metrics(dd["featured_repos"] or [])
    cats = fetch_category_opportunities(dd["featured_categories"] or [])

    print(f"    {len(repos)} repos, {len(cats)} categories with live data")

    # Render the template_body (Jinja2 string) with live data context
    body_env = Environment(loader=BaseLoader(), autoescape=False)
    body_env.filters["intcomma"] = intcomma
    body_env.filters["timeago"] = timeago
    body_env.filters["dateformat"] = dateformat
    body_env.globals["domain_path"] = domain_path

    try:
        body_tpl = body_env.from_string(dd["template_body"])
        rendered_body = body_tpl.render(repos=repos, cats=cats)
    except Exception as e:
        print(f"    ERROR rendering body: {e}")
        return None

    # Render the page shell
    shell = env.get_template("deep_dive.html")
    html = shell.render(
        deep_dive=dd,
        rendered_body=rendered_body,
        global_total=f"{global_total:,}",
        directories=DIRECTORIES,
    )

    path = os.path.join(out_dir, "insights", slug, "index.html")
    write_file(path, html)
    return slug


def render_index(deep_dives, env, out_dir, global_total):
    """Render the insights listing page."""
    html = env.get_template("insights_index.html").render(
        deep_dives=deep_dives,
        global_total=f"{global_total:,}",
        directories=DIRECTORIES,
    )
    write_file(os.path.join(out_dir, "insights", "index.html"), html)


def generate_sitemap(deep_dives, out_dir):
    """Generate sitemap for insights pages."""
    base_url = "https://mcp.phasetransitions.ai"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f'  <url><loc>{base_url}/insights/</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>',
    ]
    for dd in deep_dives:
        lines.append(
            f'  <url><loc>{base_url}/insights/{xml_escape(dd["slug"])}/</loc>'
            f'<changefreq>daily</changefreq><priority>0.9</priority></url>'
        )
    lines.append('</urlset>')
    write_file(os.path.join(out_dir, "insights", "sitemap.xml"), "\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate deep dive insight pages")
    parser.add_argument("--output-dir", default="./site", help="Output directory")
    args = parser.parse_args()
    out_dir = args.output_dir

    # Set up Jinja2 for page shells
    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    env.filters["intcomma"] = intcomma
    env.filters["timeago"] = timeago
    env.filters["dateformat"] = dateformat
    env.globals["domain_path"] = domain_path

    print("Generating deep dive pages...")
    deep_dives = fetch_deep_dives()

    if not deep_dives:
        print("  No published deep dives found.")
        return

    global_total = fetch_global_total()
    rendered = []

    for dd in deep_dives:
        slug = render_deep_dive(dd, env, out_dir, global_total)
        if slug:
            rendered.append(dd)

    if rendered:
        render_index(rendered, env, out_dir, global_total)
        generate_sitemap(rendered, out_dir)

    print(f"\nDone! {len(rendered)} deep dive(s) → {out_dir}/insights/")


if __name__ == "__main__":
    main()
