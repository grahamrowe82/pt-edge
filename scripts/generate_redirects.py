"""Generate static HTML redirect pages for reclassified repos.

Reads domain_redirects table (append-only log of old domain assignments),
joins to ai_repos for current domain, and writes a tiny redirect HTML file
at each old path. Skips paths where a real page already exists.

Run AFTER generate_site.py so the "real page exists" check works.

Usage:
    python scripts/generate_redirects.py --output-dir site
"""
import argparse
import os
import time

from sqlalchemy import text

# Allow running standalone or as part of the app
try:
    from app.db import engine
except ImportError:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app.db import engine

BASE_URL = "https://mcp.phasetransitions.ai"

REDIRECT_TEMPLATE = """\
<!DOCTYPE html><html><head>
<meta charset="utf-8">
<link rel="canonical" href="{canonical_url}">
<meta http-equiv="refresh" content="0;url={relative_url}">
<title>Moved</title>
</head><body>
<p>Moved to <a href="{relative_url}">{relative_url}</a></p>
</body></html>
"""


def generate_redirects(output_dir: str) -> dict:
    t0 = time.time()

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT dr.full_name, dr.old_domain, ar.domain AS current_domain
            FROM domain_redirects dr
            JOIN ai_repos ar ON dr.full_name = ar.full_name
            WHERE dr.old_domain != ar.domain
        """)).fetchall()

    written = 0
    skipped = 0

    for r in rows:
        parts = r.full_name.split("/", 1)
        if len(parts) != 2:
            continue
        owner, repo = parts
        old_domain = r.old_domain
        current_domain = r.current_domain

        # MCP domain lives at root, others get a prefix
        if old_domain == "mcp":
            old_path = os.path.join(output_dir, "servers", owner, repo, "index.html")
        else:
            old_path = os.path.join(output_dir, old_domain, "servers", owner, repo, "index.html")

        # Skip if a real page already exists (another repo lives there,
        # or this repo moved back to its original domain)
        if os.path.exists(old_path):
            skipped += 1
            continue

        if current_domain == "mcp":
            relative_url = f"/servers/{owner}/{repo}/"
        else:
            relative_url = f"/{current_domain}/servers/{owner}/{repo}/"
        canonical_url = f"{BASE_URL}{relative_url}"

        os.makedirs(os.path.dirname(old_path), exist_ok=True)
        with open(old_path, "w") as f:
            f.write(REDIRECT_TEMPLATE.format(
                canonical_url=canonical_url,
                relative_url=relative_url,
            ))
        written += 1

    elapsed = time.time() - t0
    print(f"  {written} redirect pages written, {skipped} skipped ({elapsed:.1f}s)")
    return {"written": written, "skipped": skipped}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate static redirect pages")
    parser.add_argument("--output-dir", default="./site", help="Output directory")
    args = parser.parse_args()

    print("Generating redirect pages...")
    generate_redirects(args.output_dir)
