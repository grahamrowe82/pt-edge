"""Insert or update a deep dive from a JSON manifest + HTML template file.

Usage:
    python scripts/insert_deep_dive.py data/deep_dives/evolutionary-ai.json

The JSON manifest should contain:
{
    "slug": "evolutionary-ai",
    "title": "...",
    "subtitle": "...",
    "author": "Graham Rowe",
    "primary_domain": "agents",
    "domains": ["agents", "ml-frameworks", "prompt-engineering"],
    "meta_description": "...",
    "template_file": "evolutionary-ai.html",
    "featured_repos": ["trevorstephens/gplearn", ...],
    "featured_categories": ["ml-frameworks:evolutionary-algorithm-frameworks", ...],
    "status": "published"
}

The template_file path is relative to the manifest's directory.
"""

import json
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db import engine


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/insert_deep_dive.py <manifest.json>")
        sys.exit(1)

    manifest_path = sys.argv[1]
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Read template body from file
    template_file = os.path.join(manifest_dir, manifest["template_file"])
    with open(template_file) as f:
        template_body = f.read()

    slug = manifest["slug"]

    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO deep_dives
                (slug, title, subtitle, author, primary_domain, domains,
                 meta_description, template_body, featured_repos,
                 featured_categories, status, published_at, updated_at)
            VALUES
                (:slug, :title, :subtitle, :author, :primary_domain, :domains,
                 :meta_description, :template_body, :featured_repos,
                 :featured_categories, :status,
                 CASE WHEN :status = 'published' THEN NOW() ELSE NULL END,
                 NOW())
            ON CONFLICT (slug) DO UPDATE SET
                title = EXCLUDED.title,
                subtitle = EXCLUDED.subtitle,
                author = EXCLUDED.author,
                primary_domain = EXCLUDED.primary_domain,
                domains = EXCLUDED.domains,
                meta_description = EXCLUDED.meta_description,
                template_body = EXCLUDED.template_body,
                featured_repos = EXCLUDED.featured_repos,
                featured_categories = EXCLUDED.featured_categories,
                status = EXCLUDED.status,
                published_at = CASE
                    WHEN EXCLUDED.status = 'published' AND deep_dives.published_at IS NULL
                    THEN NOW()
                    ELSE deep_dives.published_at
                END,
                updated_at = NOW()
        """), {
            "slug": slug,
            "title": manifest["title"],
            "subtitle": manifest.get("subtitle"),
            "author": manifest.get("author", "Graham Rowe"),
            "primary_domain": manifest["primary_domain"],
            "domains": manifest.get("domains", []),
            "meta_description": manifest.get("meta_description"),
            "template_body": template_body,
            "featured_repos": manifest.get("featured_repos", []),
            "featured_categories": manifest.get("featured_categories", []),
            "status": manifest.get("status", "draft"),
        })
        conn.commit()

    print(f"Upserted deep dive: {slug} ({manifest.get('status', 'draft')})")


if __name__ == "__main__":
    main()
