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
        "categories": {
            "framework":     {"label": "Frameworks",      "desc": "MCP server frameworks and SDKs for building servers"},
            "gateway":       {"label": "Gateways",        "desc": "API gateways, proxies, hubs, and aggregators for MCP"},
            "transport":     {"label": "Transport",        "desc": "Transport layer implementations — stdio, SSE, WebSocket bridges"},
            "security":      {"label": "Security",         "desc": "Authentication, authorization, and security tools for MCP"},
            "ide":           {"label": "IDE Integration",  "desc": "Editor and IDE plugins for MCP — VS Code, Neovim, JetBrains, Cursor"},
            "observability": {"label": "Observability",    "desc": "Monitoring, debugging, tracing, and telemetry for MCP servers"},
            "testing":       {"label": "Testing",          "desc": "Test frameworks, mocking tools, and benchmarks for MCP"},
            "discovery":     {"label": "Discovery",        "desc": "Server registries, catalogs, and directory tools"},
            "billing":       {"label": "Billing",          "desc": "Payment, metering, and monetization for MCP servers"},
            "agent-memory":  {"label": "Agent Memory",     "desc": "Long-term memory and knowledge graph tools via MCP"},
        },
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
        "categories": {
            "browser-agent":   {"label": "Browser Agents",   "desc": "Web browsing and interaction agents"},
            "coding-agent":    {"label": "Coding Agents",    "desc": "Autonomous software engineering agents"},
            "research-agent":  {"label": "Research Agents",  "desc": "Deep research and web research agents"},
            "multi-agent":     {"label": "Multi-Agent",      "desc": "Multi-agent orchestration and swarm frameworks"},
            "agent-framework": {"label": "Agent Frameworks", "desc": "SDKs and platforms for building AI agents"},
        },
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
        "categories": {
            "chunking":   {"label": "Chunking",   "desc": "Text splitting, segmentation, and partitioning tools"},
            "retrieval":  {"label": "Retrieval",   "desc": "Search, reranking, and hybrid retrieval"},
            "ingestion":  {"label": "Ingestion",   "desc": "Document loaders, parsers, and extractors"},
            "evaluation": {"label": "Evaluation",  "desc": "RAG evaluation, benchmarking, and quality metrics"},
            "pipeline":   {"label": "Pipelines",   "desc": "End-to-end RAG pipeline frameworks"},
        },
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
        "categories": {
            "code-editor":     {"label": "Code Editors",     "desc": "IDE plugins and AI-powered editors"},
            "code-review":     {"label": "Code Review",      "desc": "Automated code review and static analysis"},
            "code-generation": {"label": "Code Generation",  "desc": "Code completion and generation tools"},
            "context-tools":   {"label": "Context Tools",    "desc": "Codebase indexing, search, and mapping"},
        },
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

# ---------------------------------------------------------------------------
# Data queries
# ---------------------------------------------------------------------------

def fetch_servers(view_name):
    """All qualifying repos from the given quality view."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT full_name, name, description, stars, forks,
                   language, license, archived, subcategory,
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
    return [dict(r._mapping) for r in rows]


def fetch_trending(view_name, snapshot_table, domain_filter=None, days=7):
    """Repos with biggest score improvement in last N days."""
    domain_clause = "AND s.domain = :domain_filter" if domain_filter else ""
    params = {"days": days, "min_score": MIN_QUALITY_SCORE}
    if domain_filter:
        params["domain_filter"] = domain_filter

    with readonly_engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT m.full_name, m.name, m.description, m.quality_score,
                   m.quality_score - s.quality_score AS score_delta,
                   m.stars, m.subcategory, m.quality_tier
            FROM {view_name} m
            JOIN {snapshot_table} s ON s.repo_id = (
                SELECT id FROM ai_repos WHERE full_name = m.full_name LIMIT 1
            )
            WHERE s.snapshot_date = CURRENT_DATE - :days
              AND m.quality_score >= :min_score
              AND m.description IS NOT NULL
              AND m.description != ''
              AND m.quality_score - s.quality_score > 0
              {domain_clause}
            ORDER BY m.quality_score - s.quality_score DESC
            LIMIT 100
        """), params).fetchall()
    return [dict(r._mapping) for r in rows]


# ---------------------------------------------------------------------------
# Site generation
# ---------------------------------------------------------------------------

def build_category_data(servers, category_meta):
    """Group servers by subcategory and compute aggregates."""
    by_cat = {}
    for s in servers:
        cat = s.get("subcategory") or "uncategorized"
        by_cat.setdefault(cat, []).append(s)

    categories = []
    for key, group in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        meta = category_meta.get(key, {"label": key.replace("-", " ").title(), "desc": f"{key} tools"})
        categories.append({
            "subcategory": key,
            "label": meta["label"],
            "desc": meta["desc"],
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


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Path(path).write_text(content)


def generate_sitemap(base_url, base_path, servers, categories, out_dir):
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
    env.globals["base_url"] = base_url
    env.globals["base_path"] = base_path.rstrip("/")
    env.globals["directories"] = DIRECTORIES

    # Domain-specific context passed to all templates
    domain_ctx = {
        "domain": domain,
        "domain_label": cfg["label"],
        "domain_label_plural": cfg["label_plural"],
        "noun": cfg["noun"],
        "noun_plural": cfg["noun_plural"],
        "domain_description": cfg["description"],
    }

    # Phase 1: Query data
    print(f"  Fetching {cfg['noun_plural']}...")
    servers = fetch_servers(cfg["view"])
    total_count = len(servers)
    print(f"  {total_count} qualifying {cfg['noun_plural']}")

    print("  Fetching trending...")
    try:
        trending = fetch_trending(
            cfg["view"], cfg["snapshot_table"], cfg["snapshot_domain_filter"]
        )
    except Exception as e:
        print(f"  Trending query failed (expected if < 7 days of snapshots): {e}")
        trending = []
    print(f"  {len(trending)} trending {cfg['noun_plural']}")

    # Build derived data
    categories = build_category_data(servers, cfg["categories"])
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
        env.get_template("trending.html").render(trending=trending, **ctx),
    )

    # Phase 3: SEO assets
    print("  Generating sitemap.xml + robots.txt...")
    generate_sitemap(base_url, base_path, servers, categories, out_dir)
    generate_robots(base_url, base_path, out_dir)

    elapsed = time.time() - t0
    total_files = total_count + total_pages + len(categories) + 5
    print(f"\nDone! {cfg['label']}: {total_files} files in {elapsed:.1f}s → {out_dir}/")


if __name__ == "__main__":
    main()
