"""Seed labs and projects from JSON files."""
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import SessionLocal
from app.models import Lab, Project


def seed():
    session = SessionLocal()

    # Load labs
    labs_path = Path(__file__).parent.parent / "seeds" / "labs.json"
    with open(labs_path) as f:
        labs_data = json.load(f)

    lab_map = {}  # slug -> Lab object
    for data in labs_data:
        existing = session.query(Lab).filter(Lab.slug == data["slug"]).first()
        if existing:
            lab_map[data["slug"]] = existing
            print(f"  Lab already exists: {data['name']}")
            continue
        lab = Lab(
            name=data["name"],
            slug=data["slug"],
            url=data.get("url"),
            blog_url=data.get("blog_url"),
            github_org=data.get("github_org"),
        )
        session.add(lab)
        session.flush()  # get the ID
        lab_map[data["slug"]] = lab
        print(f"  Added lab: {data['name']}")

    session.commit()
    print(f"Labs: {len(lab_map)} total")

    # Load projects
    projects_path = Path(__file__).parent.parent / "seeds" / "projects.json"
    with open(projects_path) as f:
        projects_data = json.load(f)

    added = 0
    skipped = 0
    for data in projects_data:
        existing = session.query(Project).filter(Project.slug == data["slug"]).first()
        if existing:
            skipped += 1
            continue
        lab = lab_map.get(data.get("lab_slug")) if data.get("lab_slug") else None
        project = Project(
            name=data["name"],
            slug=data["slug"],
            category=data["category"],
            lab_id=lab.id if lab else None,
            github_owner=data.get("github_owner"),
            github_repo=data.get("github_repo"),
            pypi_package=data.get("pypi_package"),
            npm_package=data.get("npm_package"),
            description=data.get("description"),
            url=data.get("url"),
        )
        session.add(project)
        added += 1

    session.commit()
    session.close()
    print(f"Projects: {added} added, {skipped} skipped")


if __name__ == "__main__":
    seed()
