"""Seed labs and projects from JSON files. Batch insert to avoid round-trip latency."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db import engine


def seed():
    labs_path = Path(__file__).parent.parent / "seeds" / "labs.json"
    projects_path = Path(__file__).parent.parent / "seeds" / "projects.json"

    with open(labs_path) as f:
        labs_data = json.load(f)
    with open(projects_path) as f:
        projects_data = json.load(f)

    with engine.connect() as conn:
        # Batch upsert labs
        for lab in labs_data:
            conn.execute(
                text("""
                    INSERT INTO labs (name, slug, url, blog_url, github_org)
                    VALUES (:name, :slug, :url, :blog_url, :github_org)
                    ON CONFLICT (slug) DO NOTHING
                """),
                lab,
            )
        conn.commit()
        print(f"Labs: {len(labs_data)} processed")

        # Build slug -> id map in one query
        rows = conn.execute(text("SELECT id, slug FROM labs")).fetchall()
        lab_map = {r[1]: r[0] for r in rows}
        print(f"Lab map: {len(lab_map)} entries")

        # Batch upsert projects
        for p in projects_data:
            conn.execute(
                text("""
                    INSERT INTO projects (name, slug, category, lab_id, github_owner, github_repo,
                                         pypi_package, npm_package, description, url, distribution_type,
                                         hf_model_id, docker_image)
                    VALUES (:name, :slug, :category, :lab_id, :github_owner, :github_repo,
                            :pypi_package, :npm_package, :description, :url, :distribution_type,
                            :hf_model_id, :docker_image)
                    ON CONFLICT (slug) DO UPDATE SET
                        github_owner = EXCLUDED.github_owner,
                        github_repo = EXCLUDED.github_repo,
                        distribution_type = EXCLUDED.distribution_type,
                        hf_model_id = EXCLUDED.hf_model_id,
                        docker_image = EXCLUDED.docker_image
                """),
                {
                    "name": p["name"],
                    "slug": p["slug"],
                    "category": p["category"],
                    "lab_id": lab_map.get(p.get("lab_slug")),
                    "github_owner": p.get("github_owner"),
                    "github_repo": p.get("github_repo"),
                    "pypi_package": p.get("pypi_package"),
                    "npm_package": p.get("npm_package"),
                    "description": p.get("description"),
                    "url": p.get("url"),
                    "distribution_type": p.get("distribution_type", "package"),
                    "hf_model_id": p.get("hf_model_id"),
                    "docker_image": p.get("docker_image"),
                },
            )
        conn.commit()
        print(f"Projects: {len(projects_data)} processed")

        # Verify
        lab_count = conn.execute(text("SELECT count(*) FROM labs")).scalar()
        proj_count = conn.execute(text("SELECT count(*) FROM projects")).scalar()
        print(f"Total in DB: {lab_count} labs, {proj_count} projects")


if __name__ == "__main__":
    seed()
