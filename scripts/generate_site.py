"""Generate static MCP directory site.

Usage:
    python scripts/generate_site.py [--output-dir ./site] [--base-url https://phasetransitions.ai]

Queries mv_mcp_quality and renders Jinja2 templates to static HTML files.
Designed to run in < 60 seconds for ~11,500 server pages.
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

CATEGORY_META = {
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
    "verified":     "70–100",
    "established":  "50–69",
    "emerging":     "30–49",
    "experimental": "10–29",
}

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

def fetch_servers():
    """All qualifying MCP servers, ordered by quality_score DESC."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT full_name, name, description, stars, forks,
                   language, license, archived, subcategory,
                   last_pushed_at, pypi_package, npm_package,
                   downloads_monthly, dependency_count, commits_30d,
                   reverse_dep_count,
                   maintenance_score, adoption_score, maturity_score, community_score,
                   quality_score, quality_tier, risk_flags
            FROM mv_mcp_quality
            WHERE quality_score >= :min_score
              AND description IS NOT NULL
              AND description != ''
            ORDER BY quality_score DESC NULLS LAST
        """), {"min_score": MIN_QUALITY_SCORE}).fetchall()
    return [dict(r._mapping) for r in rows]


def fetch_trending(days=7):
    """Servers with biggest score improvement in last N days."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT m.full_name, m.name, m.description, m.quality_score,
                   m.quality_score - s.quality_score AS score_delta,
                   m.stars, m.subcategory, m.quality_tier
            FROM mv_mcp_quality m
            JOIN mcp_quality_snapshots s ON s.repo_id = (
                SELECT id FROM ai_repos WHERE full_name = m.full_name LIMIT 1
            )
            WHERE s.snapshot_date = CURRENT_DATE - :days
              AND m.quality_score >= :min_score
              AND m.description IS NOT NULL
              AND m.description != ''
              AND m.quality_score - s.quality_score > 0
            ORDER BY m.quality_score - s.quality_score DESC
            LIMIT 100
        """), {"days": days, "min_score": MIN_QUALITY_SCORE}).fetchall()
    return [dict(r._mapping) for r in rows]


# ---------------------------------------------------------------------------
# Site generation
# ---------------------------------------------------------------------------

def build_category_data(servers):
    """Group servers by subcategory and compute aggregates."""
    by_cat = {}
    for s in servers:
        cat = s.get("subcategory") or "uncategorized"
        by_cat.setdefault(cat, []).append(s)

    categories = []
    for key, group in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        meta = CATEGORY_META.get(key, {"label": key.replace("-", " ").title(), "desc": f"{key} MCP servers"})
        categories.append({
            "subcategory": key,
            "label": meta["label"],
            "desc": meta["desc"],
            "count": len(group),
            "servers": group,
        })
    return categories


def build_related_lookup(categories):
    """Pre-compute top 5 related servers per category (excluding the server itself)."""
    lookup = {}
    for cat in categories:
        top = cat["servers"][:6]  # grab 6 so we can exclude self
        lookup[cat["subcategory"]] = top
    return lookup


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Path(path).write_text(content)


def generate_sitemap(base_url, servers, categories, out_dir):
    """Generate sitemap.xml."""
    today = date.today().isoformat()
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f'  <url><loc>{base_url}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>',
        f'  <url><loc>{base_url}/servers/</loc><changefreq>daily</changefreq><priority>0.9</priority></url>',
        f'  <url><loc>{base_url}/categories/</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>',
        f'  <url><loc>{base_url}/trending/</loc><changefreq>daily</changefreq><priority>0.7</priority></url>',
    ]

    for cat in categories:
        lines.append(
            f'  <url><loc>{base_url}/categories/{xml_escape(cat["subcategory"])}/</loc>'
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
            f'  <url><loc>{base_url}/servers/{xml_escape(s["full_name"])}/</loc>'
            f'{lastmod}<changefreq>weekly</changefreq><priority>0.6</priority></url>'
        )

    lines.append('</urlset>')

    write_file(os.path.join(out_dir, "sitemap.xml"), "\n".join(lines))


def generate_robots(base_url, out_dir):
    content = f"User-agent: *\nAllow: /\n\nSitemap: {base_url}/sitemap.xml\n"
    write_file(os.path.join(out_dir, "robots.txt"), content)


def main():
    parser = argparse.ArgumentParser(description="Generate static MCP directory site")
    parser.add_argument("--output-dir", default="./site", help="Output directory")
    parser.add_argument("--base-url", default="https://phasetransitions.ai", help="Base URL for canonical links")
    args = parser.parse_args()

    out_dir = args.output_dir
    base_url = args.base_url.rstrip("/")
    t0 = time.time()

    # Set up Jinja2
    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    env.globals["tier_classes"] = tier_classes
    env.globals["tier_bar_color"] = tier_bar_color
    env.globals["score_bar_color"] = score_bar_color
    env.globals["base_url"] = base_url

    # Phase 1: Query data
    print("Fetching servers...")
    servers = fetch_servers()
    total_count = len(servers)
    print(f"  {total_count} qualifying servers")

    print("Fetching trending...")
    try:
        trending = fetch_trending()
    except Exception as e:
        print(f"  Trending query failed (expected if < 7 days of snapshots): {e}")
        trending = []
    print(f"  {len(trending)} trending servers")

    # Build derived data
    categories = build_category_data(servers)
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

    # Shared template context
    ctx = {"total_count": total_count}

    # Phase 2: Render pages
    print("Generating homepage...")
    homepage = env.get_template("index.html")
    write_file(
        os.path.join(out_dir, "index.html"),
        homepage.render(
            top_servers=servers[:20],
            tiers=tiers,
            categories=[{
                "subcategory": c["subcategory"],
                "label": c["label"],
                "count": c["count"],
            } for c in categories],
            **ctx,
        ),
    )

    # Paginated server index
    print("Generating server index pages...")
    total_pages = math.ceil(total_count / PER_PAGE)
    index_tpl = env.get_template("servers_index.html")
    for page in range(1, total_pages + 1):
        offset = (page - 1) * PER_PAGE
        page_servers = servers[offset:offset + PER_PAGE]
        path = os.path.join(out_dir, "servers", "index.html") if page == 1 else \
               os.path.join(out_dir, "servers", "page", str(page), "index.html")
        write_file(path, index_tpl.render(
            servers=page_servers,
            page=page,
            total_pages=total_pages,
            offset=offset,
            per_page=PER_PAGE,
            **ctx,
        ))
    print(f"  {total_pages} index pages")

    # Individual server pages
    print("Generating server detail pages...")
    detail_tpl = env.get_template("server_detail.html")
    last_owner = None
    for i, s in enumerate(servers):
        parts = s["full_name"].split("/", 1)
        if len(parts) != 2:
            continue
        owner, repo = parts

        # Get related servers (same subcategory, excluding self)
        cat_key = s.get("subcategory") or "uncategorized"
        related = [r for r in related_lookup.get(cat_key, [])
                   if r["full_name"] != s["full_name"]][:5]

        path = os.path.join(out_dir, "servers", owner, repo, "index.html")
        if owner != last_owner:
            os.makedirs(os.path.join(out_dir, "servers", owner), exist_ok=True)
            last_owner = owner

        write_file(path, detail_tpl.render(
            server=s,
            related_servers=related,
            **ctx,
        ))

        if (i + 1) % 2000 == 0:
            print(f"  {i + 1}/{total_count} server pages...")
    print(f"  {total_count} server detail pages")

    # Category pages
    print("Generating category pages...")
    cat_tpl = env.get_template("category.html")
    cat_index_tpl = env.get_template("categories_index.html")

    write_file(
        os.path.join(out_dir, "categories", "index.html"),
        cat_index_tpl.render(
            categories=[{
                "subcategory": c["subcategory"],
                "label": c["label"],
                "desc": c["desc"],
                "count": c["count"],
            } for c in categories],
            **ctx,
        ),
    )

    for cat in categories:
        write_file(
            os.path.join(out_dir, "categories", cat["subcategory"], "index.html"),
            cat_tpl.render(
                subcategory=cat["subcategory"],
                category_label=cat["label"],
                category_desc=cat["desc"],
                servers=cat["servers"],
                **ctx,
            ),
        )
    print(f"  {len(categories)} category pages")

    # Trending page
    print("Generating trending page...")
    trending_tpl = env.get_template("trending.html")
    write_file(
        os.path.join(out_dir, "trending", "index.html"),
        trending_tpl.render(trending=trending, **ctx),
    )

    # Phase 3: SEO assets
    print("Generating sitemap.xml...")
    generate_sitemap(base_url, servers, categories, out_dir)

    print("Generating robots.txt...")
    generate_robots(base_url, out_dir)

    elapsed = time.time() - t0
    total_files = total_count + total_pages + len(categories) + 5  # detail + index + cat + home/cat-index/trending/sitemap/robots
    print(f"\nDone! {total_files} files generated in {elapsed:.1f}s → {out_dir}/")


if __name__ == "__main__":
    main()
