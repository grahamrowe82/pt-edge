"""Static site generator for CyberEdge.

Generates ~300K+ static HTML pages from pre-computed materialized views.
All expensive computation happens in the worker (view refresh, scoring,
embeddings, categorization). This script only queries views and renders
Jinja2 templates. Must complete in <5 minutes on Render.

Usage:
    python scripts/generate_site.py --output-dir site --base-url https://cyber.phasetransitions.ai
"""

import argparse
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import text

from domains.cyber.app.db import engine

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PER_PAGE = 100
BATCH_SIZE = 5000

ENTITY_CONFIG = {
    "cve": {
        "view": "mv_cve_scores",
        "id_column": "cve_id",
        "name_column": "cve_id",
        "url_prefix": "/cve",
        "slug_field": "cve_id",
        "template": "cve_detail.html",
        "label": "CVE",
        "label_plural": "CVEs",
        "description": "Common Vulnerabilities and Exposures scored on severity, exploitability, exposure, and patch availability.",
        "dimensions": [
            ("severity", "Severity"),
            ("exploitability", "Exploitability"),
            ("exposure", "Exposure"),
            ("patch_availability", "Patch Availability"),
        ],
    },
    "software": {
        "view": "mv_software_scores",
        "id_column": "cpe_id",
        "name_column": "name",
        "url_prefix": "/software",
        "slug_field": "name",
        "template": "software_detail.html",
        "label": "Software",
        "label_plural": "Software Products",
        "description": "Software products scored by aggregate vulnerability risk across their CVE portfolio.",
        "dimensions": [
            ("severity", "Severity"),
            ("exploitability", "Exploitability"),
            ("exposure", "Exposure"),
            ("patch_availability", "Patch Availability"),
        ],
    },
    "vendor": {
        "view": "mv_vendor_scores",
        "id_column": "slug",
        "name_column": "name",
        "url_prefix": "/vendor",
        "slug_field": "slug",
        "template": "vendor_detail.html",
        "label": "Vendor",
        "label_plural": "Vendors",
        "description": "Vendors scored by aggregate vulnerability risk across their product portfolio.",
        "dimensions": [
            ("severity", "Severity"),
            ("exploitability", "Exploitability"),
            ("exposure", "Exposure"),
            ("patch_availability", "Patch Availability"),
        ],
    },
    "weakness": {
        "view": "mv_weakness_scores",
        "id_column": "cwe_id",
        "name_column": "name",
        "url_prefix": "/weakness",
        "slug_field": "cwe_id",
        "template": "weakness_detail.html",
        "label": "Weakness",
        "label_plural": "Weaknesses",
        "description": "CWE weakness types scored by the severity and exploitability of associated CVEs.",
        "dimensions": [
            ("severity", "Severity"),
            ("exploitability", "Exploitability"),
            ("exposure", "Exposure"),
            ("patch_availability", "Patch Availability"),
        ],
    },
    "technique": {
        "view": "mv_technique_scores",
        "id_column": "technique_id",
        "name_column": "name",
        "url_prefix": "/technique",
        "slug_field": "technique_id",
        "template": "technique_detail.html",
        "label": "Technique",
        "label_plural": "ATT&CK Techniques",
        "description": "MITRE ATT&CK techniques scored by the CVEs reachable through the kill chain.",
        "dimensions": [
            ("severity", "Severity"),
            ("exploitability", "Exploitability"),
            ("exposure", "Exposure"),
            ("patch_availability", "Patch Availability"),
        ],
    },
    "pattern": {
        "view": "mv_pattern_scores",
        "id_column": "capec_id",
        "name_column": "name",
        "url_prefix": "/attack-pattern",
        "slug_field": "capec_id",
        "template": "pattern_detail.html",
        "label": "Attack Pattern",
        "label_plural": "CAPEC Attack Patterns",
        "description": "CAPEC attack patterns scored by the CVEs reachable through linked weaknesses.",
        "dimensions": [
            ("severity", "Severity"),
            ("exploitability", "Exploitability"),
            ("exposure", "Exposure"),
            ("patch_availability", "Patch Availability"),
        ],
    },
}

TIER_RANGES = {
    "critical-risk": (70, 100),
    "high-risk": (50, 69),
    "moderate-risk": (30, 49),
    "low-risk": (0, 29),
}

TIER_ORDER = ["critical-risk", "high-risk", "moderate-risk", "low-risk"]

NAV_LINKS = [
    ("/cve/", "CVEs"),
    ("/software/", "Software"),
    ("/vendor/", "Vendors"),
    ("/weakness/", "Weaknesses"),
    ("/technique/", "Techniques"),
    ("/attack-pattern/", "Patterns"),
    ("/trending/", "Trending"),
    ("/about/", "About"),
]


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

def human_number(n):
    """Format number for display: 1200 → '1.2K', 1500000 → '1.5M'."""
    if n is None:
        return "0"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def tier_classes(tier):
    """CSS classes for tier badges."""
    return {
        "critical-risk": "bg-red-100 text-red-800 border-red-200",
        "high-risk": "bg-orange-100 text-orange-800 border-orange-200",
        "moderate-risk": "bg-yellow-100 text-yellow-800 border-yellow-200",
        "low-risk": "bg-green-100 text-green-800 border-green-200",
    }.get(tier, "bg-gray-100 text-gray-800 border-gray-200")


def tier_bar_color(tier):
    """Bar color for tier visualization."""
    return {
        "critical-risk": "bg-red-500",
        "high-risk": "bg-orange-500",
        "moderate-risk": "bg-yellow-500",
        "low-risk": "bg-green-500",
    }.get(tier, "bg-gray-400")


def score_bar_color(score, max_score=25):
    """Color for individual dimension score bars."""
    pct = (score or 0) / max_score * 100
    if pct >= 80:
        return "bg-red-500"
    if pct >= 60:
        return "bg-orange-500"
    if pct >= 40:
        return "bg-yellow-500"
    if pct >= 20:
        return "bg-blue-500"
    return "bg-gray-400"


def score_context(score, max_score=25):
    """Contextual label for a dimension score."""
    pct = (score or 0) / max_score * 100
    if pct >= 80:
        return "Critical"
    if pct >= 60:
        return "High"
    if pct >= 40:
        return "Moderate"
    if pct >= 20:
        return "Low"
    return "Minimal"


def slugify(name):
    """Create URL-safe slug from a name."""
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9-]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


# ---------------------------------------------------------------------------
# Data fetching (from materialized views — fast reads)
# ---------------------------------------------------------------------------

def fetch_entities(config: dict) -> list[dict]:
    """Fetch scored entities from a materialized view."""
    view = config["view"]
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT * FROM {view}
            ORDER BY composite_score DESC
        """)).mappings().fetchall()
    return [dict(r) for r in rows]


def fetch_entity_summary() -> dict:
    """Fetch tier distributions from mv_entity_summary."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT * FROM mv_entity_summary"
            )).mappings().fetchall()
        return {r["entity_type"]: dict(r) for r in rows}
    except Exception:
        return {}


def fetch_trending() -> dict:
    """Fetch score movers from snapshot tables for all entity types."""
    trending = {}
    snapshot_tables = {
        "cve": ("cve_score_snapshots", "cve_id", "cves", "cve_id"),
        "software": ("software_score_snapshots", "software_id", "software", "name"),
        "vendor": ("vendor_score_snapshots", "vendor_id", "vendors", "name"),
        "weakness": ("weakness_score_snapshots", "weakness_id", "weaknesses", "cwe_id"),
        "technique": ("technique_score_snapshots", "technique_id", "techniques", "technique_id"),
        "pattern": ("pattern_score_snapshots", "pattern_id", "attack_patterns", "capec_id"),
    }
    for entity_type, (snap_table, fk_col, entity_table, name_col) in snapshot_tables.items():
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(f"""
                    WITH latest AS (
                        SELECT {fk_col}, composite_score, quality_tier,
                               ROW_NUMBER() OVER (PARTITION BY {fk_col} ORDER BY snapshot_date DESC) AS rn
                        FROM {snap_table}
                    ),
                    earliest AS (
                        SELECT {fk_col}, composite_score,
                               ROW_NUMBER() OVER (PARTITION BY {fk_col} ORDER BY snapshot_date ASC) AS rn
                        FROM {snap_table}
                    )
                    SELECT e.{name_col} AS name, l.composite_score AS current_score,
                           l.quality_tier, l.composite_score - ea.composite_score AS score_delta
                    FROM latest l
                    JOIN earliest ea ON ea.{fk_col} = l.{fk_col} AND ea.rn = 1
                    JOIN {entity_table} e ON e.id = l.{fk_col}
                    WHERE l.rn = 1
                      AND l.composite_score - ea.composite_score > 0
                    ORDER BY score_delta DESC
                    LIMIT 20
                """)).mappings().fetchall()
                trending[entity_type] = [dict(r) for r in rows]
        except Exception:
            trending[entity_type] = []
    return trending


def fetch_cve_enrichment(cve_ids: list[int]) -> dict:
    """Batch fetch CVE enrichment: software, vendors, weaknesses, kill chain."""
    if not cve_ids:
        return {}

    result = {}
    with engine.connect() as conn:
        # Software links
        for start in range(0, len(cve_ids), BATCH_SIZE):
            batch = cve_ids[start:start + BATCH_SIZE]
            rows = conn.execute(text("""
                SELECT cs.cve_id, s.name, s.cpe_id
                FROM cve_software cs
                JOIN software s ON s.id = cs.software_id
                WHERE cs.cve_id = ANY(:ids)
            """), {"ids": batch}).mappings().fetchall()
            for r in rows:
                result.setdefault(r["cve_id"], {}).setdefault("software", []).append(dict(r))

        # Vendor links
        for start in range(0, len(cve_ids), BATCH_SIZE):
            batch = cve_ids[start:start + BATCH_SIZE]
            rows = conn.execute(text("""
                SELECT cv.cve_id, v.name, v.slug
                FROM cve_vendors cv
                JOIN vendors v ON v.id = cv.vendor_id
                WHERE cv.cve_id = ANY(:ids)
            """), {"ids": batch}).mappings().fetchall()
            for r in rows:
                result.setdefault(r["cve_id"], {}).setdefault("vendors", []).append(dict(r))

        # Weakness links (kill chain step 1)
        for start in range(0, len(cve_ids), BATCH_SIZE):
            batch = cve_ids[start:start + BATCH_SIZE]
            rows = conn.execute(text("""
                SELECT cw.cve_id, w.cwe_id, w.name
                FROM cve_weaknesses cw
                JOIN weaknesses w ON w.id = cw.weakness_id
                WHERE cw.cve_id = ANY(:ids)
            """), {"ids": batch}).mappings().fetchall()
            for r in rows:
                result.setdefault(r["cve_id"], {}).setdefault("weaknesses", []).append(dict(r))

        # Kill chain: CWE → CAPEC → ATT&CK
        for start in range(0, len(cve_ids), BATCH_SIZE):
            batch = cve_ids[start:start + BATCH_SIZE]
            rows = conn.execute(text("""
                SELECT DISTINCT cw.cve_id, w.cwe_id, ap.capec_id, t.technique_id, t.name AS technique_name
                FROM cve_weaknesses cw
                JOIN weaknesses w ON w.id = cw.weakness_id
                JOIN weakness_patterns wp ON wp.weakness_id = w.id
                JOIN attack_patterns ap ON ap.id = wp.pattern_id
                JOIN pattern_techniques pt ON pt.pattern_id = ap.id
                JOIN techniques t ON t.id = pt.technique_id
                WHERE cw.cve_id = ANY(:ids)
            """), {"ids": batch}).mappings().fetchall()
            for r in rows:
                result.setdefault(r["cve_id"], {}).setdefault("kill_chain", []).append(dict(r))

    return result


# ---------------------------------------------------------------------------
# Page writing
# ---------------------------------------------------------------------------

def load_cached(key: str) -> list[dict]:
    """Load pre-computed data from structural_cache. Returns [] if empty."""
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT value FROM structural_cache WHERE key = :k"
            ), {"k": key}).fetchone()
        if row and row[0]:
            return row[0] if isinstance(row[0], list) else []
    except Exception:
        pass
    return []


def write_page(out_dir: str, path: str, html: str):
    """Write an HTML page to disk."""
    full_path = os.path.join(out_dir, path.strip("/"), "index.html")
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(html)


def generate_sitemap(base_url: str, urls: list[dict], out_dir: str):
    """Write sitemap.xml from generated URL list."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for u in urls:
        loc = xml_escape(f"{base_url}{u['path']}")
        lines.append(f"  <url><loc>{loc}</loc>")
        if u.get("lastmod"):
            lines.append(f"    <lastmod>{u['lastmod']}</lastmod>")
        if u.get("changefreq"):
            lines.append(f"    <changefreq>{u['changefreq']}</changefreq>")
        if u.get("priority"):
            lines.append(f"    <priority>{u['priority']}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")

    path = os.path.join(out_dir, "sitemap.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def generate_robots(base_url: str, out_dir: str):
    """Write robots.txt."""
    content = f"""User-agent: *
Allow: /

Sitemap: {base_url}/sitemap.xml

# CyberEdge — cybersecurity vulnerability intelligence
# API: {base_url}/api/v1/
# MCP: {base_url}/mcp
"""
    path = os.path.join(out_dir, "robots.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate CyberEdge static site")
    parser.add_argument("--output-dir", default="./site")
    parser.add_argument("--base-url", default="https://cyber.phasetransitions.ai")
    args = parser.parse_args()

    out_dir = args.output_dir
    base_url = args.base_url.rstrip("/")
    os.makedirs(out_dir, exist_ok=True)

    t0 = time.time()
    generated_urls = []
    total_files = 0

    # Set up Jinja2
    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
    env.globals.update({
        "human_number": human_number,
        "tier_classes": tier_classes,
        "tier_bar_color": tier_bar_color,
        "score_bar_color": score_bar_color,
        "score_context": score_context,
        "nav_links": NAV_LINKS,
        "base_url": base_url,
        "now": datetime.now(timezone.utc),
        "tier_order": TIER_ORDER,
    })

    # -----------------------------------------------------------------------
    # Phase 1: Fetch data from materialized views
    # -----------------------------------------------------------------------
    print("Phase 1: Fetching data from materialized views...")

    all_entities = {}
    for entity_type, config in ENTITY_CONFIG.items():
        try:
            entities = fetch_entities(config)
            all_entities[entity_type] = entities
            print(f"  {config['label_plural']}: {len(entities):,}")
        except Exception as e:
            print(f"  {config['label_plural']}: FAILED ({e})")
            all_entities[entity_type] = []

    entity_summary = fetch_entity_summary()
    trending = fetch_trending()

    # Build lookup sets for dead-link prevention
    lookups = {}
    for entity_type, config in ENTITY_CONFIG.items():
        slug_field = config["slug_field"]
        if entity_type == "software":
            lookups[entity_type] = {slugify(e.get("name", "")) for e in all_entities[entity_type]}
        else:
            lookups[entity_type] = {e.get(slug_field) for e in all_entities[entity_type]}

    # Batch fetch CVE enrichment (software, vendors, weaknesses, kill chain)
    cve_ids = [e["id"] for e in all_entities.get("cve", [])]
    cve_enrichment = {}
    if cve_ids:
        print(f"  Fetching CVE enrichment for {len(cve_ids):,} CVEs...")
        cve_enrichment = fetch_cve_enrichment(cve_ids)

    # -----------------------------------------------------------------------
    # Phase 2: Render pages
    # -----------------------------------------------------------------------
    print("\nPhase 2: Rendering pages...")

    # Homepage
    homepage_tpl = env.get_template("homepage.html")
    top_entities = {
        et: entities[:10] for et, entities in all_entities.items()
    }
    html = homepage_tpl.render(
        top_entities=top_entities,
        entity_summary=entity_summary,
        entity_config=ENTITY_CONFIG,
        total_entities=sum(len(v) for v in all_entities.values()),
    )
    write_page(out_dir, "/", html)
    generated_urls.append({"path": "/", "changefreq": "daily", "priority": "1.0"})
    total_files += 1

    # Entity index + detail pages
    for entity_type, config in ENTITY_CONFIG.items():
        entities = all_entities[entity_type]
        if not entities:
            continue

        tpl_detail = env.get_template(config["template"])
        tpl_index = env.get_template("entity_index.html")
        prefix = config["url_prefix"]
        slug_field = config["slug_field"]

        # Tier distribution for this entity type
        tiers = entity_summary.get(entity_type + ("s" if entity_type != "software" else ""), {})

        # Index pages (paginated)
        total_pages = max(1, math.ceil(len(entities) / PER_PAGE))
        for page_num in range(1, total_pages + 1):
            offset = (page_num - 1) * PER_PAGE
            page_entities = entities[offset:offset + PER_PAGE]
            page_path = f"{prefix}/" if page_num == 1 else f"{prefix}/page/{page_num}/"

            html = tpl_index.render(
                config=config,
                entities=page_entities,
                tiers=tiers,
                slug_field=slug_field,
                slugify=slugify,
                current_page=page_num,
                total_pages=total_pages,
                total_count=len(entities),
                page_base_url=f"{prefix}/page",
                first_page_url=f"{prefix}/",
            )
            write_page(out_dir, page_path, html)
            generated_urls.append({"path": page_path, "changefreq": "daily", "priority": "0.9"})
            total_files += 1

        # Detail pages
        detail_count = 0
        for entity in entities:
            if entity_type == "software":
                slug = slugify(entity.get("name", ""))
            else:
                slug = entity.get(slug_field, "")
            if not slug:
                continue

            page_path = f"{prefix}/{slug}/"

            # Build context
            ctx = {
                "entity": entity,
                "config": config,
                "dimensions": [
                    {
                        "key": dim_key,
                        "label": dim_label,
                        "value": entity.get(dim_key, 0),
                        "context": score_context(entity.get(dim_key, 0)),
                    }
                    for dim_key, dim_label in config["dimensions"]
                ],
                "lookups": lookups,
                "slugify": slugify,
            }

            # CVE-specific enrichment
            if entity_type == "cve":
                enr = cve_enrichment.get(entity["id"], {})
                ctx["software"] = enr.get("software", [])[:20]
                ctx["vendors"] = enr.get("vendors", [])
                ctx["weaknesses"] = enr.get("weaknesses", [])
                ctx["kill_chain"] = enr.get("kill_chain", [])

            html = tpl_detail.render(**ctx)
            write_page(out_dir, page_path, html)
            generated_urls.append({"path": page_path, "changefreq": "weekly", "priority": "0.6"})
            total_files += 1
            detail_count += 1

            if detail_count % 10000 == 0:
                print(f"    {config['label_plural']}: {detail_count:,} detail pages...")

        print(f"  {config['label_plural']}: {detail_count:,} detail + {total_pages} index pages")

    # Trending page
    trending_tpl = env.get_template("trending.html")
    html = trending_tpl.render(trending=trending, entity_config=ENTITY_CONFIG)
    write_page(out_dir, "/trending/", html)
    generated_urls.append({"path": "/trending/", "changefreq": "daily", "priority": "0.7"})
    total_files += 1

    # About page
    about_tpl = env.get_template("about.html")
    html = about_tpl.render(entity_config=ENTITY_CONFIG)
    write_page(out_dir, "/about/", html)
    generated_urls.append({"path": "/about/", "changefreq": "monthly", "priority": "0.4"})
    total_files += 1

    # -----------------------------------------------------------------------
    # Phase 2b: Relationship pages (from structural_cache)
    # -----------------------------------------------------------------------
    print("\nPhase 2b: Relationship pages...")

    # CVE-Software pair pages
    cve_sw_pairs = load_cached("cve_software_pairs")
    if cve_sw_pairs:
        pair_tpl = env.get_template("cve_software_pair.html")
        pair_count = 0
        for pair in cve_sw_pairs:
            cve_id = pair.get("cve_id", "")
            sw_name = pair.get("software_name", "")
            if not cve_id or not sw_name:
                continue
            page_path = f"/cve/{cve_id}/software/{slugify(sw_name)}/"
            html = pair_tpl.render(pair=pair, slugify=slugify)
            write_page(out_dir, page_path, html)
            generated_urls.append({"path": page_path, "changefreq": "weekly", "priority": "0.4"})
            total_files += 1
            pair_count += 1
            if pair_count % 10000 == 0:
                print(f"    CVE-Software pairs: {pair_count:,}...")
        print(f"  CVE-Software pairs: {pair_count:,}")

    # Vendor weakness portfolio pages
    vendor_weak_data = load_cached("vendor_weakness_pairs")
    if vendor_weak_data:
        vw_tpl = env.get_template("vendor_weaknesses.html")
        # Group by vendor
        vendor_groups = {}
        for row in vendor_weak_data:
            vs = row.get("vendor_slug", "")
            if vs not in vendor_groups:
                vendor_groups[vs] = {"vendor_slug": vs, "vendor_name": row.get("vendor_name"), "weaknesses": []}
            vendor_groups[vs]["weaknesses"].append(row)
        vw_count = 0
        for vs, group in vendor_groups.items():
            page_path = f"/vendor/{vs}/weaknesses/"
            html = vw_tpl.render(
                vendor_slug=group["vendor_slug"],
                vendor_name=group["vendor_name"],
                weaknesses=group["weaknesses"],
            )
            write_page(out_dir, page_path, html)
            generated_urls.append({"path": page_path, "changefreq": "weekly", "priority": "0.5"})
            total_files += 1
            vw_count += 1
        print(f"  Vendor weakness portfolios: {vw_count:,}")

    # Kill chain pages
    chain_data = load_cached("kill_chain_pages")
    if chain_data:
        chain_tpl = env.get_template("chain_page.html")
        chain_count = 0
        for chain in chain_data:
            cwe = chain.get("cwe_id", "")
            capec = chain.get("capec_id", "")
            tech = chain.get("technique_id", "")
            if not cwe or not capec or not tech:
                continue
            page_path = f"/chain/{cwe}/{capec}/{tech}/"
            html = chain_tpl.render(chain=chain)
            write_page(out_dir, page_path, html)
            generated_urls.append({"path": page_path, "changefreq": "weekly", "priority": "0.5"})
            total_files += 1
            chain_count += 1
        print(f"  Kill chain pages: {chain_count:,}")

    # -----------------------------------------------------------------------
    # Phase 2c: Insight pages (hypothesis engine)
    # -----------------------------------------------------------------------
    print("\nPhase 2c: Insight pages...")

    HYPOTHESIS_CONFIG = {
        "unpatched_exposure": {
            "cache_key": "hypothesis_unpatched_exposure",
            "template": "insight_unpatched.html",
            "url_fn": lambda h: f"/insights/unpatched/{h.get('cve_id', '')}/",
            "label_fn": lambda h: h.get("cve_id", ""),
            "score_fn": lambda h: h.get("composite_score", 0),
            "title": "Unpatched Exposure Gaps",
            "description": "High-severity CVEs with wide deployment and no available fix.",
            "entity_label": "CVE",
        },
        "chain_gaps": {
            "cache_key": "hypothesis_chain_gaps",
            "template": "insight_chain_gap.html",
            "url_fn": lambda h: f"/insights/chain-gap/{h.get('technique_id', '')}/{slugify(h.get('software_name', ''))}/",
            "label_fn": lambda h: f"{h.get('technique_id', '')} × {h.get('software_name', '')}",
            "score_fn": lambda h: h.get("weakness_cve_count", 0),
            "title": "Attack Chain Gaps",
            "description": "Software with weakness exposure to a technique but no verified exploit proves the chain.",
            "entity_label": "Gap",
        },
        "vendor_anomalies": {
            "cache_key": "hypothesis_vendor_anomalies",
            "template": "insight_vendor_risk.html",
            "url_fn": lambda h: f"/insights/vendor-risk/{h.get('vendor_slug', '')}/",
            "label_fn": lambda h: h.get("vendor_name", ""),
            "score_fn": lambda h: h.get("vendor_score", 0),
            "title": "Vendor Risk Anomalies",
            "description": "Vendors with patch response rates anomalously below their peer bracket.",
            "entity_label": "Vendor",
        },
        "momentum_divergences": {
            "cache_key": "hypothesis_momentum_divergences",
            "template": "insight_momentum.html",
            "url_fn": lambda h: f"/insights/momentum/{h.get('cve_id', '')}/",
            "label_fn": lambda h: h.get("cve_id", ""),
            "score_fn": lambda h: h.get("composite_score", 0),
            "title": "Exploit Momentum Signals",
            "description": "CVEs with high EPSS probability but no public exploit yet.",
            "entity_label": "CVE",
        },
    }

    MIN_HYPOTHESIS_SCORE = 40
    insight_sections = []

    for h_type, h_config in HYPOTHESIS_CONFIG.items():
        data = load_cached(h_config["cache_key"])
        filtered = [h for h in data if h.get("hypothesis_score", 0) >= MIN_HYPOTHESIS_SCORE]
        if not filtered:
            insight_sections.append({"title": h_config["title"], "description": h_config["description"], "entity_label": h_config["entity_label"], "items": []})
            continue

        tpl = env.get_template(h_config["template"])
        rendered = 0
        section_items = []

        for item in filtered:
            page_path = h_config["url_fn"](item)
            if not page_path or page_path.endswith("//"):
                continue
            html = tpl.render(item=item, slugify=slugify)
            write_page(out_dir, page_path, html)
            generated_urls.append({"path": page_path, "changefreq": "weekly", "priority": "0.5"})
            total_files += 1
            rendered += 1
            section_items.append({
                "url": page_path,
                "label": h_config["label_fn"](item),
                "entity_score": h_config["score_fn"](item),
                "hypothesis_score": item.get("hypothesis_score", 0),
            })

        insight_sections.append({
            "title": h_config["title"],
            "description": h_config["description"],
            "entity_label": h_config["entity_label"],
            "items": section_items,
        })
        if rendered:
            print(f"  {h_config['title']}: {rendered:,} pages")

    # Insights index page
    any_data = any(s["items"] for s in insight_sections)
    insights_tpl = env.get_template("insights_index.html")
    html = insights_tpl.render(sections=insight_sections, any_data=any_data)
    write_page(out_dir, "/insights/", html)
    generated_urls.append({"path": "/insights/", "changefreq": "weekly", "priority": "0.8"})
    total_files += 1

    # -----------------------------------------------------------------------
    # Phase 3: SEO assets
    # -----------------------------------------------------------------------
    print("\nPhase 3: SEO assets...")
    generate_sitemap(base_url, generated_urls, out_dir)
    generate_robots(base_url, out_dir)
    print(f"  Sitemap: {len(generated_urls):,} URLs")

    elapsed = time.time() - t0
    print(f"\nDone! {total_files:,} files in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
