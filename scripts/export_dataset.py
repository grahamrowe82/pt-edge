"""Export public datasets to JSON for the mcp-quality-index GitHub repo.

Usage:
    python scripts/export_dataset.py [--output-dir /path/to/mcp-quality-index/data]

Exports:
    - mcp-scores.json:  MCP quality scores (mv_mcp_quality)
    - mcp-repos.json:   All MCP-domain repos with metrics
    - projects.json:    Tracked project summaries (mv_project_summary)
    - metadata.json:    Export metadata (timestamp, counts, schema version)
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone, date

from sqlalchemy import text

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db import readonly_engine


def _json_serial(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "__float__"):
        return float(obj)
    return str(obj)


def _query(sql):
    with readonly_engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()
        return [dict(r._mapping) for r in rows]


def export_mcp_scores():
    return _query("""
        SELECT full_name, name, description, stars, forks,
               language, license, archived, subcategory,
               last_pushed_at, pypi_package, npm_package,
               downloads_monthly, dependency_count, commits_30d,
               reverse_dep_count,
               maintenance_score, adoption_score, maturity_score, community_score,
               quality_score, quality_tier, risk_flags
        FROM mv_mcp_quality
        ORDER BY quality_score DESC NULLS LAST
    """)


def export_mcp_repos():
    return _query("""
        SELECT full_name, name, description, stars, forks, language,
               topics, license, last_pushed_at, archived, subcategory,
               downloads_monthly, dependency_count,
               pypi_package, npm_package, commits_30d
        FROM ai_repos
        WHERE domain = 'mcp' AND archived = false
        ORDER BY stars DESC NULLS LAST
    """)


def export_projects():
    return _query("""
        SELECT name, slug, category, domain, stack_layer, lab_name,
               stars, forks, monthly_downloads, commits_30d,
               stars_7d_delta, stars_30d_delta, dl_30d_delta,
               commits_7d_delta, commits_30d_delta, contributors_30d_delta,
               hype_ratio, hype_bucket,
               velocity_band, commits_per_contributor, development_pace,
               fork_star_ratio, lifecycle_stage,
               tier, traction_score, traction_bucket,
               dl_trend, dl_weekly_velocity,
               last_commit_at, last_release_at, days_since_release
        FROM mv_project_summary
        ORDER BY traction_score DESC NULLS LAST
    """)


def main():
    parser = argparse.ArgumentParser(description="Export PT-Edge datasets to JSON")
    parser.add_argument("--output-dir", default="./data", help="Output directory")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    now = datetime.now(timezone.utc)

    exports = {
        "mcp-scores.json": ("MCP quality scores", export_mcp_scores),
        "mcp-repos.json": ("MCP repos", export_mcp_repos),
        "projects.json": ("Project summaries", export_projects),
    }

    counts = {}
    for filename, (label, fn) in exports.items():
        print(f"Exporting {label}...")
        data = fn()
        path = os.path.join(args.output_dir, filename)
        with open(path, "w") as f:
            json.dump(data, f, default=_json_serial, indent=2)
        counts[filename] = len(data)
        print(f"  {len(data)} records -> {path}")

    metadata = {
        "schema_version": 1,
        "exported_at": now.isoformat(),
        "source": "https://pt-edge.onrender.com",
        "license": "CC-BY-4.0",
        "datasets": {
            name: {"records": count, "description": exports[name][0]}
            for name, count in counts.items()
        },
    }
    meta_path = os.path.join(args.output_dir, "metadata.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata -> {meta_path}")
    print(f"Export complete: {sum(counts.values())} total records")


if __name__ == "__main__":
    main()
