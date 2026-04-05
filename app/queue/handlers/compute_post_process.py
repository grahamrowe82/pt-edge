"""Compute/fetch handlers for post-processing and analytics tasks.

Coarse-grained — each handler delegates to the existing function.
"""
import logging

logger = logging.getLogger(__name__)


async def handle_import_gsc(task: dict) -> dict:
    from app.ingest.gsc import ingest_gsc
    return await ingest_gsc()


async def handle_import_umami(task: dict) -> dict:
    from app.ingest.umami import ingest_umami
    return await ingest_umami()


async def handle_compute_coview(task: dict) -> dict:
    from app.ingest.coview import ingest_coview
    return await ingest_coview()


async def handle_compute_hn_backfill(task: dict) -> dict:
    from app.ingest.hn import backfill_hn_links
    return await backfill_hn_links()


async def handle_compute_hn_lab_backfill(task: dict) -> dict:
    from app.ingest.hn import backfill_hn_lab_links
    return await backfill_hn_lab_links()


async def handle_compute_v2ex_lab_backfill(task: dict) -> dict:
    from app.ingest.v2ex import backfill_v2ex_lab_links
    return await backfill_v2ex_lab_links()


async def handle_compute_domain_reassign(task: dict) -> dict:
    from app.ingest.domain_reassign import reassign_domains
    return await reassign_domains()


async def handle_compute_project_linking(task: dict) -> dict:
    """Link projects to ai_repos by matching github_owner/github_repo."""
    from sqlalchemy import text
    from app.db import engine
    with engine.connect() as conn:
        result = conn.execute(text("""
            UPDATE projects p
            SET ai_repo_id = a.id
            FROM ai_repos a
            WHERE LOWER(p.github_owner) = LOWER(a.github_owner)
              AND LOWER(p.github_repo) = LOWER(a.github_repo)
              AND p.ai_repo_id IS NULL
              AND p.github_owner IS NOT NULL
        """))
        linked = result.rowcount
        conn.commit()
    return {"linked": linked}


async def handle_compute_briefing_refresh(task: dict) -> dict:
    from app.briefing_refresh import refresh_briefing_evidence
    return await refresh_briefing_evidence()


async def handle_export_dataset(task: dict) -> dict:
    """Push dataset export to GitHub + HuggingFace."""
    import subprocess
    result = subprocess.run(
        ["bash", "scripts/push_dataset.sh"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode == 0:
        return {"status": "pushed"}
    raise RuntimeError(f"Dataset export failed: {result.stderr[:200]}")


async def handle_discover_ai_repos(task: dict) -> dict:
    """Run the weekly AI repos GitHub Search discovery."""
    from app.ingest.ai_repos import ingest_ai_repos
    return await ingest_ai_repos()


async def handle_compute_structural(task: dict) -> dict:
    """Run weekly structural computation (comparison pairs, centroids, labels).

    Delegates to scripts/weekly_structural.py as a subprocess, same as
    the existing Sunday cron job.
    """
    import subprocess
    import sys
    from pathlib import Path
    script = str(Path(__file__).parent.parent.parent.parent / "scripts" / "weekly_structural.py")
    result = subprocess.run(
        [sys.executable, script],
        capture_output=True, text=True, timeout=3600,
    )
    if result.returncode == 0:
        return {"status": "success"}
    raise RuntimeError(f"weekly_structural failed: {result.stderr[:300]}")
