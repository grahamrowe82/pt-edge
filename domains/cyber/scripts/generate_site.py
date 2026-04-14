"""Static site generator for CyberEdge.

Generates static HTML pages from pre-computed materialized views.
All expensive computation happens in the worker (view refresh, scoring,
embeddings, categorization). This script only queries views and renders
Jinja2 templates.

Chunked generation (same pattern as OS AI):
    start.sh calls this script ~18 times, once per chunk. Each invocation
    loads only its subset of data, generates, and exits. Memory freed between
    invocations. No single step exceeds ~40K pages.

Usage:
    python generate_site.py --chunk cve:2024 --output-dir site
    python generate_site.py --chunk products --output-dir site
    python generate_site.py --chunk homepage --output-dir site
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
MIN_SCORE = 55  # Only generate detail pages for CVEs scoring >= this

# Products/vendors/weaknesses use combo threshold: score >= 10 OR cve_count >= 20
# This captures both dangerous small products AND notable well-known products
PRODUCT_MIN_SCORE = 10
PRODUCT_MIN_CVES = 20

# Tier guidance for product pages (deterministic templates — Gemini-generated
# category-specific guidance is a follow-up PR)
TIER_GUIDANCE = {
    "critical-risk": {
        "headline": "Immediate action recommended",
        "summary": "{name} has critical exploitation rates across its known vulnerabilities.",
        "actions": [
            "Check for patches and apply immediately",
            "Review whether this software can be replaced with a safer alternative",
            "Consult your IT provider about mitigation options",
        ],
    },
    "high-risk": {
        "headline": "Take action — actively targeted",
        "summary": "{name} is actively targeted by attackers. A significant proportion of its known vulnerabilities are being exploited.",
        "actions": [
            "Apply all available updates immediately",
            "Review your exposure — is this internet-facing?",
            "Monitor vendor advisories for this product",
        ],
    },
    "moderate-risk": {
        "headline": "Review your setup",
        "summary": "{name} has some exploitation signals but is generally manageable with regular updates.",
        "actions": [
            "Keep this software updated",
            "Review your configuration for unnecessary exposure",
            "Check for known-vulnerable components or plugins",
        ],
    },
    "low-risk": {
        "headline": "Standard maintenance is sufficient",
        "summary": "{name} has low exploitation rates. Attackers rarely target this software's known vulnerabilities.",
        "actions": [
            "Keep automatic updates enabled",
            "No urgent action needed",
            "Review periodically as part of normal maintenance",
        ],
    },
}

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
        "summary_key": "cves",
        "max_score": 34,
        "description": "Common Vulnerabilities and Exposures scored on severity, exploitability, and exposure.",
        "dimensions": [
            ("severity", "Severity"),
            ("exploitability", "Exploitability"),
            ("exposure", "Exposure"),
        ],
    },
    "product": {
        "view": "mv_product_scores",
        "id_column": "id",
        "name_column": "display_name",
        "url_prefix": "/product",
        "slug_field": "id",
        "template": "product_detail.html",
        "label": "Product",
        "label_plural": "Products",
        "summary_key": "products",
        "max_score": 50,
        "combo_threshold": {"min_score": PRODUCT_MIN_SCORE, "min_cves": PRODUCT_MIN_CVES},
        "description": "Software products scored by proportion of dangerous CVEs — active threat signals and exploitation evidence.",
        "dimensions": [
            ("active_threat", "Active Threat"),
            ("exploit_availability", "Exploit Availability"),
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
        "summary_key": "vendors",
        "max_score": 50,
        "no_min_score": True,
        "description": "Vendors scored by proportion of dangerous CVEs across their product portfolio.",
        "dimensions": [
            ("active_threat", "Active Threat"),
            ("exploit_availability", "Exploit Availability"),
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
        "summary_key": "weaknesses",
        "max_score": 50,
        "no_min_score": True,
        "description": "CWE weakness types scored by proportion of linked CVEs with active exploitation.",
        "dimensions": [
            ("active_threat", "Active Threat"),
            ("exploit_availability", "Exploit Availability"),
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
        "summary_key": "techniques",
        "max_score": 50,
        "description": "MITRE ATT&CK techniques scored by proportion of reachable CVEs with active exploitation.",
        "dimensions": [
            ("active_threat", "Active Threat"),
            ("exploit_availability", "Exploit Availability"),
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
        "summary_key": "attack_patterns",
        "max_score": 50,
        "description": "CAPEC attack patterns scored by proportion of reachable CVEs with active exploitation.",
        "dimensions": [
            ("active_threat", "Active Threat"),
            ("exploit_availability", "Exploit Availability"),
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
    ("/product/", "Products"),
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

def fetch_entities(config: dict, year_filter: int | None = None) -> list[dict]:
    """Fetch scored entities from materialized view. MVs include all display fields.

    Products use combo threshold (score >= 10 OR cve_count >= 20).
    CVEs can be filtered by published year for chunked generation.
    """
    view = config["view"]
    combo = config.get("combo_threshold")

    if year_filter is not None:
        # CVE year chunk — no MIN_SCORE, filter by year
        with engine.connect() as conn:
            if year_filter == 0:
                # pre-2018 bucket
                rows = conn.execute(text(f"""
                    SELECT * FROM {view}
                    WHERE EXTRACT(YEAR FROM published_date) < 2018
                    ORDER BY composite_score DESC
                """)).mappings().fetchall()
            else:
                rows = conn.execute(text(f"""
                    SELECT * FROM {view}
                    WHERE EXTRACT(YEAR FROM published_date) = :year
                    ORDER BY composite_score DESC
                """), {"year": year_filter}).mappings().fetchall()
    elif combo:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT * FROM {view}
                WHERE composite_score >= :min_score OR cve_count >= :min_cves
                ORDER BY composite_score DESC
            """), {"min_score": combo["min_score"], "min_cves": combo["min_cves"]}).mappings().fetchall()
    elif config.get("no_min_score"):
        # Generate all (vendors, weaknesses, etc.)
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT * FROM {view}
                ORDER BY composite_score DESC
            """)).mappings().fetchall()
    else:
        min_score = config.get("min_score", MIN_SCORE)
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT * FROM {view}
                WHERE composite_score >= :min_score
                ORDER BY composite_score DESC
            """), {"min_score": min_score}).mappings().fetchall()
    return [dict(r) for r in rows]


def fetch_cve_metadata() -> dict:
    """Load Gemini-generated plain-English CVE summaries."""
    result = {}
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT cve_id, what_is_this, am_i_affected, what_to_do
                FROM cve_metadata
                WHERE what_is_this IS NOT NULL
            """)).mappings().fetchall()
            for r in rows:
                result[r["cve_id"]] = dict(r)
        print(f"  CVE metadata: {len(result):,} Gemini summaries loaded")
    except Exception:
        print("  CVE metadata: table not yet populated")
    return result


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


def fetch_homepage_data() -> dict:
    """Fetch data for homepage 'What's Happening Now' sections."""
    data = {}
    with engine.connect() as conn:
        # Highest exploit probability CVEs
        rows = conn.execute(text("""
            SELECT cve_id, cvss_base_score, epss_score, is_kev
            FROM cves
            WHERE epss_score > 0.1
            ORDER BY epss_score DESC
            LIMIT 10
        """)).mappings().fetchall()
        data["highest_epss"] = [dict(r) for r in rows]
        print(f"  Homepage: {len(data['highest_epss'])} highest EPSS CVEs")

        # Recent KEV additions
        rows = conn.execute(text("""
            SELECT cve_id, cvss_base_score, epss_score
            FROM cves
            WHERE is_kev = true AND cvss_base_score IS NOT NULL
            ORDER BY published_date DESC
            LIMIT 10
        """)).mappings().fetchall()
        data["kev_recent"] = [dict(r) for r in rows]
        print(f"  Homepage: {len(data['kev_recent'])} recent KEV CVEs")

    return data


def fetch_cve_enrichment(cve_ids: set[int]) -> dict:
    """Fetch CVE enrichment for rendered CVEs only. Filters by cve_ids to avoid
    loading millions of rows for CVEs that won't get detail pages."""
    if not cve_ids:
        return {}
    result = {}
    with engine.connect() as conn:
        # Software links (only for rendered CVEs)
        rows = conn.execute(text("""
            SELECT cs.cve_id, s.name, s.cpe_id,
                   split_part(s.cpe_id, ':', 4) AS vendor_key,
                   split_part(s.cpe_id, ':', 5) AS product_key
            FROM cve_software cs
            JOIN software s ON s.id = cs.software_id
            WHERE cs.cve_id IN (SELECT id FROM mv_cve_scores WHERE composite_score >= :min)
        """), {"min": MIN_SCORE}).mappings().fetchall()
        for r in rows:
            result.setdefault(r["cve_id"], {}).setdefault("software", []).append(
                {"name": r["name"], "cpe_id": r["cpe_id"],
                 "vendor_key": r["vendor_key"], "product_key": r["product_key"]})
        print(f"  CVE enrichment: {len(rows):,} software links")

        # Vendor links
        rows = conn.execute(text("""
            SELECT cv.cve_id, v.name, v.slug
            FROM cve_vendors cv
            JOIN vendors v ON v.id = cv.vendor_id
            WHERE cv.cve_id IN (SELECT id FROM mv_cve_scores WHERE composite_score >= :min)
        """), {"min": MIN_SCORE}).mappings().fetchall()
        for r in rows:
            result.setdefault(r["cve_id"], {}).setdefault("vendors", []).append(
                {"name": r["name"], "slug": r["slug"]})
        print(f"  CVE enrichment: {len(rows):,} vendor links")

        # Weakness links
        rows = conn.execute(text("""
            SELECT cw.cve_id, w.cwe_id, w.name
            FROM cve_weaknesses cw
            JOIN weaknesses w ON w.id = cw.weakness_id
            WHERE cw.cve_id IN (SELECT id FROM mv_cve_scores WHERE composite_score >= :min)
        """), {"min": MIN_SCORE}).mappings().fetchall()
        for r in rows:
            result.setdefault(r["cve_id"], {}).setdefault("weaknesses", []).append(
                {"cwe_id": r["cwe_id"], "name": r["name"]})
        print(f"  CVE enrichment: {len(rows):,} weakness links")

        # Kill chain: CWE → CAPEC → ATT&CK
        rows = conn.execute(text("""
            SELECT DISTINCT cw.cve_id, w.cwe_id, ap.capec_id,
                   t.technique_id, t.name AS technique_name
            FROM cve_weaknesses cw
            JOIN weaknesses w ON w.id = cw.weakness_id
            JOIN weakness_patterns wp ON wp.weakness_id = w.id
            JOIN attack_patterns ap ON ap.id = wp.pattern_id
            JOIN pattern_techniques pt ON pt.pattern_id = ap.id
            JOIN techniques t ON t.id = pt.technique_id
            WHERE cw.cve_id IN (SELECT id FROM mv_cve_scores WHERE composite_score >= :min)
        """), {"min": MIN_SCORE}).mappings().fetchall()
        for r in rows:
            result.setdefault(r["cve_id"], {}).setdefault("kill_chain", []).append(
                {"cwe_id": r["cwe_id"], "capec_id": r["capec_id"],
                 "technique_id": r["technique_id"], "technique_name": r["technique_name"]})
        print(f"  CVE enrichment: {len(rows):,} kill chain paths")

        # Exploits for rendered CVEs
        rows = conn.execute(text("""
            SELECT ce.cve_id, ce.exploit_db_id, ce.exploit_type, ce.verified, ce.source_url
            FROM cve_exploits ce
            WHERE ce.cve_id IN (SELECT id FROM mv_cve_scores WHERE composite_score >= :min)
        """), {"min": MIN_SCORE}).mappings().fetchall()
        for r in rows:
            result.setdefault(r["cve_id"], {}).setdefault("exploits", []).append(dict(r))
        print(f"  CVE enrichment: {len(rows):,} exploit links")

        # Extra CVE fields not in MV (has_fix, fix_versions, references, attack_complexity)
        rows = conn.execute(text("""
            SELECT c.id, c.has_fix, c.fix_versions, c."references", c.attack_complexity
            FROM cves c
            WHERE c.id IN (SELECT id FROM mv_cve_scores WHERE composite_score >= :min)
        """), {"min": MIN_SCORE}).mappings().fetchall()
        for r in rows:
            refs = r["references"]
            if isinstance(refs, str):
                import json
                try:
                    refs = json.loads(refs)
                except Exception:
                    refs = []
            fix_vers = r["fix_versions"]
            if isinstance(fix_vers, str):
                import json
                try:
                    fix_vers = json.loads(fix_vers)
                except Exception:
                    fix_vers = []
            result.setdefault(r["id"], {})["extra"] = {
                "has_fix": r["has_fix"],
                "fix_versions": fix_vers or [],
                "references": refs or [],
                "attack_complexity": r["attack_complexity"],
            }
        print(f"  CVE enrichment: {len(rows):,} extra field lookups")

    return result


def fetch_product_enrichment() -> dict:
    """Fetch top CVEs per product for rendered product pages."""
    result = {}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            WITH ranked AS (
                SELECT
                    split_part(s.cpe_id, ':', 4) || '/' || split_part(s.cpe_id, ':', 5) AS product_id,
                    c.cve_id, c.cvss_base_score, c.epss_score, c.is_kev, c.published_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY split_part(s.cpe_id, ':', 4), split_part(s.cpe_id, ':', 5)
                        ORDER BY COALESCE(c.epss_score, 0) DESC
                    ) AS rn
                FROM software s
                JOIN cve_software cs ON cs.software_id = s.id
                JOIN cves c ON c.id = cs.cve_id
                JOIN mv_product_scores p
                    ON p.vendor_key = split_part(s.cpe_id, ':', 4)
                    AND p.product_key = split_part(s.cpe_id, ':', 5)
                WHERE c.cvss_base_score IS NOT NULL
                  AND (p.composite_score >= :min_score OR p.cve_count >= :min_cves)
            )
            SELECT * FROM ranked WHERE rn <= 20
        """), {"min_score": PRODUCT_MIN_SCORE, "min_cves": PRODUCT_MIN_CVES}).mappings().fetchall()
        for r in rows:
            result.setdefault(r["product_id"], []).append(dict(r))
    print(f"  Product enrichment: {len(rows):,} top CVE links across {len(result):,} products")
    return result


def fetch_product_metadata() -> dict:
    """Load precomputed product metadata (categories, guidance, peers)."""
    result = {}
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT vendor_key || '/' || product_key AS id,
                       category, category_label, risk_summary,
                       recommended_actions, peer_products
                FROM product_metadata
            """)).mappings().fetchall()
            for r in rows:
                result[r["id"]] = dict(r)
        print(f"  Product metadata: {len(result):,} products with enrichment")
    except Exception:
        print("  Product metadata: table not yet populated")
    return result


def fetch_weakness_enrichment() -> dict:
    """Fetch JSONB data + top CVEs for rendered weakness pages."""
    result = {}
    with engine.connect() as conn:
        # JSONB extra fields (common_consequences, detection_methods)
        rows = conn.execute(text("""
            SELECT w.id, w.common_consequences, w.detection_methods
            FROM weaknesses w
            JOIN mv_weakness_scores ws ON ws.id = w.id
            WHERE ws.composite_score >= :min_score
        """), {"min_score": MIN_SCORE}).mappings().fetchall()
        for r in rows:
            cons = r["common_consequences"] or []
            det = r["detection_methods"] or []
            result[r["id"]] = {
                "consequences": cons if isinstance(cons, list) else [],
                "detection_methods": det if isinstance(det, list) else [],
            }
        print(f"  Weakness enrichment: {len(rows):,} JSONB lookups")

        # Top CVEs per weakness
        rows = conn.execute(text("""
            WITH ranked AS (
                SELECT cw.weakness_id, c.cve_id, c.cvss_base_score, c.epss_score, c.is_kev,
                    ROW_NUMBER() OVER (
                        PARTITION BY cw.weakness_id
                        ORDER BY COALESCE(c.epss_score, 0) DESC
                    ) AS rn
                FROM cve_weaknesses cw
                JOIN cves c ON c.id = cw.cve_id
                WHERE c.cvss_base_score IS NOT NULL
                  AND cw.weakness_id IN (
                    SELECT id FROM mv_weakness_scores WHERE composite_score >= :min_score
                  )
            )
            SELECT * FROM ranked WHERE rn <= 10
        """), {"min_score": MIN_SCORE}).mappings().fetchall()
        for r in rows:
            result.setdefault(r["weakness_id"], {}).setdefault("top_cves", []).append(dict(r))
        print(f"  Weakness enrichment: {len(rows):,} top CVE links")

    return result


def fetch_technique_enrichment() -> dict:
    """Fetch extra fields + top CVEs for rendered technique pages."""
    result = {}
    with engine.connect() as conn:
        # Data sources (ARRAY field not in MV)
        rows = conn.execute(text("""
            SELECT t.id, t.data_sources
            FROM techniques t
            JOIN mv_technique_scores ts ON ts.id = t.id
            WHERE ts.composite_score >= :min_score
        """), {"min_score": MIN_SCORE}).mappings().fetchall()
        for r in rows:
            result[r["id"]] = {
                "data_sources": r["data_sources"] or [],
            }
        print(f"  Technique enrichment: {len(rows):,} data source lookups")

        # Top CVEs per technique (through kill chain)
        rows = conn.execute(text("""
            WITH ranked AS (
                SELECT pt.technique_id AS tech_id, c.cve_id, c.cvss_base_score, c.epss_score, c.is_kev,
                    ROW_NUMBER() OVER (
                        PARTITION BY pt.technique_id
                        ORDER BY COALESCE(c.epss_score, 0) DESC
                    ) AS rn
                FROM pattern_techniques pt
                JOIN weakness_patterns wp ON wp.pattern_id = pt.pattern_id
                JOIN cve_weaknesses cw ON cw.weakness_id = wp.weakness_id
                JOIN cves c ON c.id = cw.cve_id
                WHERE c.cvss_base_score IS NOT NULL
                  AND pt.technique_id IN (
                    SELECT id FROM mv_technique_scores WHERE composite_score >= :min_score
                  )
            )
            SELECT * FROM ranked WHERE rn <= 10
        """), {"min_score": MIN_SCORE}).mappings().fetchall()
        for r in rows:
            result.setdefault(r["tech_id"], {}).setdefault("top_cves", []).append(dict(r))
        print(f"  Technique enrichment: {len(rows):,} top CVE links")

    return result


def fetch_vendor_enrichment() -> dict:
    """Fetch product stats + top products for rendered vendor pages."""
    result = {}
    with engine.connect() as conn:
        # Aggregate stats per vendor from mv_product_scores
        rows = conn.execute(text("""
            SELECT p.vendor_id,
                COUNT(*) AS product_count,
                SUM(p.cve_count) AS total_cves,
                SUM(p.high_epss_count) AS high_epss_cves,
                SUM(p.kev_count) AS kev_cves,
                SUM(p.exploit_count) AS exploit_cves,
                ROUND(AVG(p.composite_score)::numeric, 1) AS avg_product_score
            FROM mv_product_scores p
            WHERE p.vendor_id IN (
                SELECT id FROM mv_vendor_scores WHERE composite_score >= :min_score
            )
            GROUP BY p.vendor_id
        """), {"min_score": MIN_SCORE}).mappings().fetchall()
        for r in rows:
            result[r["vendor_id"]] = {"stats": dict(r)}
        print(f"  Vendor enrichment: {len(rows):,} vendor stats")

        # Top products per vendor by composite score
        rows = conn.execute(text("""
            WITH ranked AS (
                SELECT p.vendor_id, p.id, p.display_name, p.composite_score,
                    p.quality_tier, p.cve_count, p.kev_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY p.vendor_id
                        ORDER BY p.composite_score DESC
                    ) AS rn
                FROM mv_product_scores p
                WHERE p.vendor_id IN (
                    SELECT id FROM mv_vendor_scores WHERE composite_score >= :min_score
                )
            )
            SELECT * FROM ranked WHERE rn <= 10
        """), {"min_score": MIN_SCORE}).mappings().fetchall()
        for r in rows:
            result.setdefault(r["vendor_id"], {}).setdefault("top_products", []).append(dict(r))
        print(f"  Vendor enrichment: {len(rows):,} top product links")

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

def _setup_jinja(base_url: str) -> Environment:
    """Create Jinja2 environment with all globals."""
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
    return env


def _render_detail_pages(env, out_dir, entity_type, config, entities, enrichments):
    """Render detail pages for a single entity type. Returns file count."""
    tpl_detail = env.get_template(config["template"])
    slug_field = config["slug_field"]
    lookups = enrichments.get("lookups", {})
    count = 0

    for entity in entities:
        slug = entity.get(slug_field, "")
        if not slug:
            continue

        prefix = config["url_prefix"]
        page_path = f"{prefix}/{slug}/"

        ctx = {
            "entity": entity,
            "config": config,
            "dimensions": [
                {
                    "key": dim_key,
                    "label": dim_label,
                    "value": entity.get(dim_key, 0),
                    "max_score": config.get("max_score", 25),
                    "context": score_context(entity.get(dim_key, 0), config.get("max_score", 25)),
                }
                for dim_key, dim_label in config["dimensions"]
            ],
            "lookups": lookups,
            "slugify": slugify,
        }

        # Entity-specific enrichment
        if entity_type == "cve":
            enr = enrichments.get("cve_enrichment", {}).get(entity["id"], {})
            ctx["software"] = enr.get("software", [])[:20]
            ctx["vendors"] = enr.get("vendors", [])
            ctx["weaknesses"] = enr.get("weaknesses", [])
            ctx["kill_chain"] = enr.get("kill_chain", [])
            ctx["exploits"] = enr.get("exploits", [])
            ctx["cve_extra"] = enr.get("extra", {})
            ctx["cve_summary"] = enrichments.get("cve_metadata", {}).get(entity["id"])

        elif entity_type == "product":
            ctx["top_cves"] = enrichments.get("product_enrichment", {}).get(entity["id"], [])
            tier = entity.get("quality_tier", "low-risk")
            guidance = TIER_GUIDANCE.get(tier, TIER_GUIDANCE["low-risk"])
            ctx["guidance"] = {
                "headline": guidance["headline"],
                "summary": guidance["summary"].format(name=entity.get("display_name", "")),
                "actions": guidance["actions"],
            }
            meta = enrichments.get("product_metadata", {}).get(entity["id"], {})
            if meta.get("risk_summary"):
                ctx["guidance"]["summary"] = meta["risk_summary"]
            if meta.get("recommended_actions"):
                actions = meta["recommended_actions"]
                if isinstance(actions, str):
                    import json
                    try:
                        actions = json.loads(actions)
                    except Exception:
                        actions = []
                if actions:
                    ctx["guidance"]["actions"] = actions
            ctx["category_label"] = meta.get("category_label", "")
            peers = meta.get("peer_products", [])
            if isinstance(peers, str):
                import json
                try:
                    peers = json.loads(peers)
                except Exception:
                    peers = []
            ctx["peer_products"] = peers

        elif entity_type == "weakness":
            wenr = enrichments.get("weakness_enrichment", {}).get(entity["id"], {})
            ctx["weakness_extra"] = wenr
            ctx["top_cves"] = wenr.get("top_cves", [])

        elif entity_type == "technique":
            tenr = enrichments.get("technique_enrichment", {}).get(entity["id"], {})
            ctx["technique_extra"] = tenr
            ctx["top_cves"] = tenr.get("top_cves", [])

        elif entity_type == "vendor":
            venr = enrichments.get("vendor_enrichment", {}).get(entity["id"], {})
            ctx["vendor_stats"] = venr.get("stats", {})
            ctx["top_products"] = venr.get("top_products", [])

        html = tpl_detail.render(**ctx)
        write_page(out_dir, page_path, html)
        count += 1

        if count % 10000 == 0:
            print(f"    {config['label_plural']}: {count:,} detail pages...")

    print(f"  {config['label_plural']}: {count:,} detail pages")
    return count


def _render_index_pages(env, out_dir, config, entities):
    """Render paginated index pages for an entity type. Returns file count."""
    tpl_index = env.get_template("entity_index.html")
    slug_field = config["slug_field"]
    prefix = config["url_prefix"]
    entity_summary = fetch_entity_summary()
    tiers = entity_summary.get(config.get("summary_key", ""), {})

    total_pages = max(1, math.ceil(len(entities) / PER_PAGE))
    count = 0
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
        count += 1

    print(f"  {config['label_plural']}: {total_pages} index pages")
    return count


def main():
    parser = argparse.ArgumentParser(description="Generate CyberEdge static site")
    parser.add_argument("--output-dir", default="./site")
    parser.add_argument("--base-url", default="https://cyber.phasetransitions.ai")
    parser.add_argument("--chunk", help="Chunk to generate: cve:YEAR, products, vendors, weaknesses, patterns, techniques, relationships, insights, homepage")
    args = parser.parse_args()

    out_dir = args.output_dir
    base_url = args.base_url.rstrip("/")
    os.makedirs(out_dir, exist_ok=True)
    env = _setup_jinja(base_url)

    t0 = time.time()
    total_files = 0
    chunk = args.chunk

    if not chunk:
        print("ERROR: --chunk is required. Use start.sh for full generation.")
        sys.exit(1)

    # -------------------------------------------------------------------
    # CVE year chunk: cve:2024, cve:2025, cve:pre2018, etc.
    # -------------------------------------------------------------------
    if chunk.startswith("cve:"):
        year_str = chunk.split(":")[1]
        year = 0 if year_str == "pre2018" else int(year_str)
        label = f"CVEs {year_str}"
        print(f"Chunk: {label}")

        config = ENTITY_CONFIG["cve"]
        entities = fetch_entities(config, year_filter=year)
        print(f"  Fetched {len(entities):,} CVEs for {year_str}")

        # Build lookup sets (lightweight — just slug sets from all MVs)
        lookups = {}
        for et, cfg in ENTITY_CONFIG.items():
            with engine.connect() as conn:
                rows = conn.execute(text(f"SELECT {cfg['slug_field']} FROM {cfg['view']}")).fetchall()
                lookups[et] = {r[0] for r in rows}

        # CVE enrichment for this chunk only
        cve_ids = {e["id"] for e in entities}
        cve_enrichment = fetch_cve_enrichment(cve_ids)
        cve_metadata = fetch_cve_metadata()

        enrichments = {"cve_enrichment": cve_enrichment, "cve_metadata": cve_metadata, "lookups": lookups}
        total_files += _render_detail_pages(env, out_dir, "cve", config, entities, enrichments)

    # -------------------------------------------------------------------
    # Single entity type chunks: products, vendors, weaknesses, etc.
    # -------------------------------------------------------------------
    elif chunk in ENTITY_CONFIG and chunk != "cve":
        entity_type = chunk
        config = ENTITY_CONFIG[entity_type]
        print(f"Chunk: {config['label_plural']}")

        entities = fetch_entities(config)
        print(f"  Fetched {len(entities):,} {config['label_plural']}")

        # Build lookup sets
        lookups = {}
        for et, cfg in ENTITY_CONFIG.items():
            with engine.connect() as conn:
                rows = conn.execute(text(f"SELECT {cfg['slug_field']} FROM {cfg['view']}")).fetchall()
                lookups[et] = {r[0] for r in rows}

        enrichments = {"lookups": lookups}

        # Load entity-specific enrichment
        if entity_type == "product":
            enrichments["product_enrichment"] = fetch_product_enrichment()
            enrichments["product_metadata"] = fetch_product_metadata()
        elif entity_type == "weakness":
            enrichments["weakness_enrichment"] = fetch_weakness_enrichment()
        elif entity_type == "technique":
            enrichments["technique_enrichment"] = fetch_technique_enrichment()
        elif entity_type == "vendor":
            enrichments["vendor_enrichment"] = fetch_vendor_enrichment()

        total_files += _render_detail_pages(env, out_dir, entity_type, config, entities, enrichments)
        total_files += _render_index_pages(env, out_dir, config, entities)

    # -------------------------------------------------------------------
    # Relationship pages (from structural_cache)
    # -------------------------------------------------------------------
    elif chunk == "relationships":
        print("Chunk: Relationship pages")

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
                total_files += 1
                pair_count += 1
                if pair_count % 10000 == 0:
                    print(f"    CVE-Software pairs: {pair_count:,}...")
            print(f"  CVE-Software pairs: {pair_count:,}")

        vendor_weak_data = load_cached("vendor_weakness_pairs")
        if vendor_weak_data:
            vw_tpl = env.get_template("vendor_weaknesses.html")
            vendor_groups = {}
            for row in vendor_weak_data:
                vs = row.get("vendor_slug", "")
                if vs not in vendor_groups:
                    vendor_groups[vs] = {"vendor_slug": vs, "vendor_name": row.get("vendor_name"), "weaknesses": []}
                vendor_groups[vs]["weaknesses"].append(row)
            vw_count = 0
            for vs, group in vendor_groups.items():
                page_path = f"/vendor/{vs}/weaknesses/"
                html = vw_tpl.render(vendor_slug=group["vendor_slug"], vendor_name=group["vendor_name"], weaknesses=group["weaknesses"])
                write_page(out_dir, page_path, html)
                total_files += 1
                vw_count += 1
            print(f"  Vendor weakness portfolios: {vw_count:,}")

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
                total_files += 1
                chain_count += 1
            print(f"  Kill chain pages: {chain_count:,}")

    # -------------------------------------------------------------------
    # Insight pages (hypothesis engine)
    # -------------------------------------------------------------------
    elif chunk == "insights":
        print("Chunk: Insight pages")

        HYPOTHESIS_CONFIG = {
            "unpatched_exposure": {"cache_key": "hypothesis_unpatched_exposure", "template": "insight_unpatched.html", "url_fn": lambda h: f"/insights/unpatched/{h.get('cve_id', '')}/", "label_fn": lambda h: h.get("cve_id", ""), "score_fn": lambda h: h.get("composite_score", 0), "title": "Unpatched Exposure Gaps", "description": "High-severity CVEs with wide deployment and no available fix.", "entity_label": "CVE"},
            "chain_gaps": {"cache_key": "hypothesis_chain_gaps", "template": "insight_chain_gap.html", "url_fn": lambda h: f"/insights/chain-gap/{h.get('technique_id', '')}/{slugify(h.get('software_name', ''))}/", "label_fn": lambda h: f"{h.get('technique_id', '')} × {h.get('software_name', '')}", "score_fn": lambda h: h.get("weakness_cve_count", 0), "title": "Attack Chain Gaps", "description": "Software with weakness exposure to a technique but no verified exploit.", "entity_label": "Gap"},
            "vendor_anomalies": {"cache_key": "hypothesis_vendor_anomalies", "template": "insight_vendor_risk.html", "url_fn": lambda h: f"/insights/vendor-risk/{h.get('vendor_slug', '')}/", "label_fn": lambda h: h.get("vendor_name", ""), "score_fn": lambda h: h.get("vendor_score", 0), "title": "Vendor Risk Anomalies", "description": "Vendors with anomalous risk profiles.", "entity_label": "Vendor"},
            "momentum_divergences": {"cache_key": "hypothesis_momentum_divergences", "template": "insight_momentum.html", "url_fn": lambda h: f"/insights/momentum/{h.get('cve_id', '')}/", "label_fn": lambda h: h.get("cve_id", ""), "score_fn": lambda h: h.get("composite_score", 0), "title": "Exploit Momentum Signals", "description": "CVEs with high EPSS probability but no public exploit yet.", "entity_label": "CVE"},
        }

        MIN_HYPOTHESIS_SCORE = 40
        insight_sections = []
        for h_type, h_config in HYPOTHESIS_CONFIG.items():
            data = load_cached(h_config["cache_key"])
            filtered = [h for h in data if h.get("hypothesis_score", 0) >= MIN_HYPOTHESIS_SCORE]
            section_items = []
            if filtered:
                tpl = env.get_template(h_config["template"])
                for item in filtered:
                    page_path = h_config["url_fn"](item)
                    if not page_path or page_path.endswith("//"):
                        continue
                    html = tpl.render(item=item, slugify=slugify)
                    write_page(out_dir, page_path, html)
                    total_files += 1
                    section_items.append({"url": page_path, "label": h_config["label_fn"](item), "entity_score": h_config["score_fn"](item), "hypothesis_score": item.get("hypothesis_score", 0)})
                print(f"  {h_config['title']}: {len(section_items):,} pages")
            insight_sections.append({"title": h_config["title"], "description": h_config["description"], "entity_label": h_config["entity_label"], "items": section_items})

        insights_tpl = env.get_template("insights_index.html")
        html = insights_tpl.render(sections=insight_sections, any_data=any(s["items"] for s in insight_sections))
        write_page(out_dir, "/insights/", html)
        total_files += 1

    # -------------------------------------------------------------------
    # Homepage chunk: homepage, trending, about, ALL index pages, SEO
    # -------------------------------------------------------------------
    elif chunk == "homepage":
        print("Chunk: Homepage + index pages + SEO")

        entity_summary = fetch_entity_summary()
        trending = fetch_trending()
        homepage_data = fetch_homepage_data()

        # Fetch top 10 per entity type for homepage (lightweight)
        top_entities = {}
        for et, config in ENTITY_CONFIG.items():
            with engine.connect() as conn:
                rows = conn.execute(text(f"SELECT * FROM {config['view']} ORDER BY composite_score DESC LIMIT 10")).mappings().fetchall()
                top_entities[et] = [dict(r) for r in rows]

        # Homepage
        homepage_tpl = env.get_template("homepage.html")
        html = homepage_tpl.render(
            top_entities=top_entities, entity_summary=entity_summary,
            entity_config=ENTITY_CONFIG, homepage_data=homepage_data,
            total_entities=sum(s.get("total", 0) for s in entity_summary.values()),
            slugify=slugify,
        )
        write_page(out_dir, "/", html)
        total_files += 1

        # ALL entity index pages (paginated) — loads lightweight rows
        for et, config in ENTITY_CONFIG.items():
            entities = fetch_entities(config) if et != "cve" else []
            # For CVEs: load ALL CVEs (lightweight — just scoring fields)
            if et == "cve":
                with engine.connect() as conn:
                    rows = conn.execute(text("SELECT * FROM mv_cve_scores ORDER BY composite_score DESC")).mappings().fetchall()
                    entities = [dict(r) for r in rows]
            total_files += _render_index_pages(env, out_dir, config, entities)
            del entities  # Free memory before next entity type

        # Trending
        trending_tpl = env.get_template("trending.html")
        html = trending_tpl.render(trending=trending, entity_config=ENTITY_CONFIG)
        write_page(out_dir, "/trending/", html)
        total_files += 1

        # About
        about_tpl = env.get_template("about.html")
        html = about_tpl.render(entity_config=ENTITY_CONFIG)
        write_page(out_dir, "/about/", html)
        total_files += 1

        # SEO
        # Sitemap generation is deferred — each chunk would need to contribute URLs.
        # For now, generate a basic sitemap from the MVs.
        generate_robots(base_url, out_dir)
        print("  robots.txt generated")

    else:
        print(f"ERROR: Unknown chunk '{chunk}'")
        sys.exit(1)

    elapsed = time.time() - t0
    print(f"\nDone! {chunk}: {total_files:,} files in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
