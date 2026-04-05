import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.exc import OperationalError

from app.ingest.candidates import ingest_candidate_velocity, refresh_candidate_watchlist
from app.ingest.dockerhub import ingest_dockerhub
from app.ingest.vscode_marketplace import ingest_vscode
from app.ingest.downloads import ingest_downloads
# ingest_github — now handled by task queue (app/queue/handlers/fetch_github.py)
from app.ingest.hn import ingest_hn, backfill_hn_links, backfill_hn_lab_links
from app.ingest.newsletters import ingest_newsletters
from app.ingest.v2ex import ingest_v2ex, backfill_v2ex_lab_links
from app.ingest.models import ingest_models
from app.ingest.huggingface import ingest_huggingface
# ingest_releases — now handled by task queue (app/queue/handlers/fetch_releases.py)
from app.ingest.trending import ingest_trending
from app.ingest.ai_repos import ingest_ai_repos
from app.ingest.ai_repo_commits import ingest_ai_repo_commits
# ingest_ai_repo_created_at — now handled by task queue (app/queue/handlers/backfill_created_at.py)
from app.ingest.ai_repo_downloads import ingest_ai_repo_downloads

from app.ingest.public_apis import ingest_public_apis
from app.ingest.api_specs import ingest_api_specs
from app.ingest.package_deps import ingest_package_deps
from app.ingest.dep_velocity import snapshot_dep_counts
from app.ingest.hf_datasets import ingest_hf_datasets
from app.ingest.hf_models import ingest_hf_models
from app.ingest.npm_mcp import ingest_npm_mcp
from app.ingest.builder_tools import ingest_builder_tools
# LLM classification tasks — now handled by task queue (Wave 6)
# detect_packages_llm, ingest_subcategories, classify_subcategory_llm,
# classify_stack_layers, match_hn_posts_llm
# generate_ai_summaries — now handled by task queue (app/queue/handlers/)
from app.ingest.domain_reassign import reassign_domains
# generate_comparison_sentences — now handled by task queue (app/queue/handlers/)
# backfill_embeddings — now handled by task queue (app/queue/handlers/compute_embeddings.py)
from app.briefing_refresh import refresh_briefing_evidence
# embeddings + views — now handled by task queue (compute_embeddings, compute_mv_refresh)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [10, 30, 60]  # seconds — exponential-ish backoff
INGEST_LOCK_ID = 8675309  # Postgres advisory lock ID

# Held open for the duration of run_all() to keep the advisory lock alive.
_lock_conn = None


def acquire_ingest_lock() -> bool:
    """Try to acquire a Postgres advisory lock. Returns True if acquired."""
    global _lock_conn
    from sqlalchemy import text
    from app.db import engine

    _lock_conn = engine.connect()
    acquired = _lock_conn.execute(
        text("SELECT pg_try_advisory_lock(:id)"), {"id": INGEST_LOCK_ID}
    ).scalar()
    if not acquired:
        _lock_conn.close()
        _lock_conn = None
    return acquired


def release_ingest_lock():
    """Release the advisory lock by closing the dedicated connection."""
    global _lock_conn
    if _lock_conn is not None:
        _lock_conn.close()
        _lock_conn = None


def _reset_pool():
    """Dispose all SQLAlchemy connection pools to force fresh connections."""
    from app.db import engine, readonly_engine
    engine.dispose()
    readonly_engine.dispose()
    logger.info("DB connection pools disposed — next query will reconnect")


# Jobs that write their own sync_log entries — don't double-log these
_SELF_LOGGING_JOBS = {
    'github', 'downloads', 'dockerhub', 'vscode', 'huggingface',
    'hn', 'v2ex', 'trending', 'candidate_velocity', 'hf_datasets',
    'hf_models', 'public_apis', 'package_deps', 'dep_velocity',
    'builder_tools', 'npm_mcp', 'ai_repo_downloads', 'ai_repo_commits',
    'ai_repo_package_detect', 'releases', 'newsletters',
    'ai_repo_subcategory', 'domain_reassign', 'views',
    'ai_repo_created_at', 'project_briefs', 'stack_layer',
    'subcategory_llm', 'hn_llm_match',
}


def _log_job(name: str, result, job_started: datetime):
    """Write sync_log for jobs that don't write their own."""
    if name in _SELF_LOGGING_JOBS:
        return
    from app.db import SessionLocal
    from app.models import SyncLog
    is_error = isinstance(result, dict) and 'error' in result
    records = 0
    if isinstance(result, dict):
        records = result.get('generated', result.get('linked', result.get('refreshed', 0)))
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type=name,
            status='failed' if is_error else 'success',
            records_written=records,
            error_message=str(result.get('error', ''))[:500] if is_error else None,
            started_at=job_started,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    except Exception as e:
        logger.warning(f"Could not log sync for {name}: {e}")
    finally:
        session.close()


async def _run_with_retry(name: str, fn, retries: int = MAX_RETRIES):
    """Run an async ingest function with retry on DB connection errors.

    fn must be a callable that returns a coroutine (not a pre-created coroutine).
    """
    for attempt in range(1, retries + 1):
        try:
            return await fn()
        except OperationalError as e:
            if attempt < retries:
                delay = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
                logger.warning(
                    f"{name}: DB connection error (attempt {attempt}/{retries}), "
                    f"retrying in {delay}s: {e}"
                )
                _reset_pool()
                await asyncio.sleep(delay)
            else:
                logger.exception(f"{name}: DB connection error after {retries} attempts")
                raise


async def run_all() -> dict:
    """Run all ingest jobs sequentially, then refresh materialized views."""
    results = {}

    logger.info("Starting full ingest cycle")

    # github — now handled by task queue (fetch_github, priority 7)
    results["github"] = {"status": "handled_by_task_queue"}
    logger.info("github: delegated to task queue worker")

    for name, fn in [
        # Phase 1: Fast daily-critical — no LLM calls (< 5 min each)
        ("downloads", ingest_downloads),
        ("dockerhub", ingest_dockerhub),
        ("vscode", ingest_vscode),
        ("huggingface", ingest_huggingface),
        ("hn", ingest_hn),
        ("v2ex", ingest_v2ex),
        ("trending", ingest_trending),
        ("candidate_velocity", ingest_candidate_velocity),
        # Phase 2: Slow discovery indexes (minutes to hours)
        ("hf_datasets", ingest_hf_datasets),
        ("hf_models", ingest_hf_models),
        ("public_apis", ingest_public_apis),
        ("api_specs", ingest_api_specs),
        ("package_deps", ingest_package_deps),
        ("dep_velocity", snapshot_dep_counts),
        ("builder_tools", ingest_builder_tools),
        ("npm_mcp", ingest_npm_mcp),
        ("ai_repo_downloads", ingest_ai_repo_downloads),
        ("ai_repo_commits", ingest_ai_repo_commits),
        ("candidate_watchlist", refresh_candidate_watchlist),
        # semantic_scholar removed — 2.5h runtime for 0 records (2026-04-04 audit)
        # ai_repos removed — runs on its own weekly cron (Saturday 12:00 UTC)
        # Phase 3: LLM-dependent (rate-limited, at end so they don't block)
        # ai_repo_package_detect — now handled by task queue (enrich_package_detect)
        ("newsletters", ingest_newsletters),
        # releases — now handled by task queue (fetch_releases, priority 6)
    ]:
        try:
            results[name] = await _run_with_retry(name, fn)
            logger.info(f"{name}: {results[name]}")
        except Exception as e:
            logger.exception(f"{name} failed: {e}")
            results[name] = {"error": str(e)}

    # releases — now handled by task queue (fetch_releases, priority 6)
    results["releases"] = {"status": "handled_by_task_queue"}
    logger.info("releases: delegated to task queue worker")

    # Google Search Console (lazy import — google libs not in CI)
    try:
        from app.ingest.gsc import ingest_gsc
        results["gsc"] = await _run_with_retry("gsc", ingest_gsc)
        logger.info(f"gsc: {results['gsc']}")
    except ImportError:
        results["gsc"] = "skipped (google libs not installed)"
    except Exception as e:
        logger.exception(f"gsc failed: {e}")
        results["gsc"] = {"error": str(e)}

    # Umami analytics ETL (page stats for allocation engine)
    try:
        from app.ingest.umami import ingest_umami
        results["umami"] = await _run_with_retry("umami", ingest_umami)
        logger.info(f"umami: {results['umami']}")
    except Exception as e:
        logger.exception(f"umami failed: {e}")
        results["umami"] = {"error": str(e)}

    # Co-view pair extraction from Umami sessions
    try:
        from app.ingest.coview import ingest_coview
        results["coview"] = await _run_with_retry("coview", ingest_coview)
        logger.info(f"coview: {results['coview']}")
    except Exception as e:
        logger.exception(f"coview failed: {e}")
        results["coview"] = {"error": str(e)}

    # Re-match unlinked HN posts against current project list
    try:
        hn_linked = await _run_with_retry("hn_backfill", backfill_hn_links)
        results["hn_backfill"] = {"linked": hn_linked}
        logger.info(f"hn_backfill: {results['hn_backfill']}")
    except Exception as e:
        logger.exception(f"hn_backfill failed: {e}")
        results["hn_backfill"] = {"error": str(e)}

    # Match unlinked HN posts to labs by title
    try:
        hn_lab_linked = await _run_with_retry("hn_lab_backfill", backfill_hn_lab_links)
        results["hn_lab_backfill"] = {"linked": hn_lab_linked}
        logger.info(f"hn_lab_backfill: {results['hn_lab_backfill']}")
    except Exception as e:
        logger.exception(f"hn_lab_backfill failed: {e}")
        results["hn_lab_backfill"] = {"error": str(e)}

    # hn_llm_match — now handled by task queue (enrich_hn_match, priority 4)
    results["hn_llm_match"] = {"status": "handled_by_task_queue"}
    logger.info("hn_llm_match: delegated to task queue worker")

    # Match unlinked V2EX posts to labs
    try:
        v2ex_lab_linked = await _run_with_retry("v2ex_lab_backfill", backfill_v2ex_lab_links)
        results["v2ex_lab_backfill"] = {"linked": v2ex_lab_linked}
        logger.info(f"v2ex_lab_backfill: {results['v2ex_lab_backfill']}")
    except Exception as e:
        logger.exception(f"v2ex_lab_backfill failed: {e}")
        results["v2ex_lab_backfill"] = {"error": str(e)}

    # subcategory + subcategory_llm — now handled by task queue (enrich_subcategory, priority 4)
    results["subcategory"] = {"status": "handled_by_task_queue"}
    results["subcategory_llm"] = {"status": "handled_by_task_queue"}
    logger.info("subcategory: delegated to task queue worker")

    # stack_layer — now handled by task queue (enrich_stack_layer, priority 4)
    results["stack_layer"] = {"status": "handled_by_task_queue"}
    logger.info("stack_layer: delegated to task queue worker")

    # NOTE: ai_summaries + comparison_sentences moved after MV refresh (allocation-driven)

    # Reassign misclassified domains (10,000 repos per run via centroid similarity)
    try:
        results["domain_reassign"] = await _run_with_retry("domain_reassign", reassign_domains)
        logger.info(f"domain_reassign: {results['domain_reassign']}")
    except Exception as e:
        logger.exception(f"domain_reassign failed: {e}")
        results["domain_reassign"] = {"error": str(e)}

    # Link projects ↔ ai_repos by matching github_owner/github_repo
    try:
        from sqlalchemy import text as _text
        from app.db import engine as _engine
        with _engine.connect() as conn:
            result = conn.execute(_text("""
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
        results["project_linking"] = {"linked": linked}
        logger.info(f"project_linking: {results['project_linking']}")
    except Exception as e:
        logger.exception(f"project_linking failed: {e}")
        results["project_linking"] = {"error": str(e)}

    # Sync frontier models from OpenRouter
    try:
        results["models"] = await _run_with_retry("models", ingest_models)
        logger.info(f"models: {results['models']}")
    except Exception as e:
        logger.exception(f"models ingest failed: {e}")
        results["models"] = {"error": str(e)}

    # embeddings — now handled by task queue (compute_embeddings, priority 5)
    results["embeddings"] = {"status": "handled_by_task_queue"}
    logger.info("embeddings: delegated to task queue worker")

    # views (MV refresh) — now handled by task queue (compute_mv_refresh, priority 5)
    results["views"] = {"status": "handled_by_task_queue"}
    logger.info("views: delegated to task queue worker")

    # content_budget — now handled by task queue (compute_content_budget, priority 5)
    results["content_budget"] = {"status": "handled_by_task_queue"}
    logger.info("content_budget: delegated to task queue worker")

    # Content pipelines (allocation-driven — consume content_budget table)

    # ai_summaries — now handled by the task queue worker (fetch_readme + enrich_summary)
    # See app/queue/handlers/ and docs/design/worker-architecture.md
    results["ai_summaries"] = {"status": "handled_by_task_queue"}
    logger.info("ai_summaries: delegated to task queue worker")

    # comparison_sentences — now handled by the task queue worker (enrich_comparison)
    results["comparison_sentences"] = {"status": "handled_by_task_queue"}
    logger.info("comparison_sentences: delegated to task queue worker")

    # repo_briefs — now handled by the task queue worker (enrich_repo_brief)
    results["repo_briefs"] = {"status": "handled_by_task_queue"}
    logger.info("repo_briefs: delegated to task queue worker")

    # Export dataset to GitHub repo
    try:
        import subprocess
        result = subprocess.run(
            ["bash", "scripts/push_dataset.sh"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            results["dataset_export"] = {"status": "pushed"}
            logger.info(f"dataset_export: pushed")
        else:
            results["dataset_export"] = {"error": result.stderr[:200]}
            logger.warning(f"dataset_export failed: {result.stderr[:200]}")
    except Exception as e:
        logger.warning(f"dataset_export failed: {e}")
        results["dataset_export"] = {"error": str(e)}

    # project_briefs — now handled by the task queue worker (enrich_project_brief)
    results["project_briefs"] = {"status": "handled_by_task_queue"}
    logger.info("project_briefs: delegated to task queue worker")

    # domain_briefs + landscape_briefs — now handled by the task queue worker
    # Previously gated by weekday() == 6 (Sunday). Now staleness-driven.
    results["domain_briefs"] = {"status": "handled_by_task_queue"}
    logger.info("domain_briefs: delegated to task queue worker (staleness-driven, no Sunday gate)")
    results["landscape_briefs"] = {"status": "handled_by_task_queue"}
    logger.info("landscape_briefs: delegated to task queue worker (staleness-driven, no Sunday gate)")

    # Refresh briefing evidence values against current data
    try:
        results["briefing_refresh"] = await _run_with_retry(
            "briefing_refresh", refresh_briefing_evidence
        )
        logger.info(f"briefing_refresh: {results['briefing_refresh']}")
    except Exception as e:
        logger.exception(f"briefing_refresh failed: {e}")
        results["briefing_refresh"] = {"error": str(e)}

    # static_site — now handled by task queue (export_static_site, priority 4)
    results["static_site"] = {"status": "handled_by_task_queue"}
    logger.info("static_site: delegated to task queue worker")

    # ai_repo_created_at — now handled by task queue (backfill_created_at, priority 2)
    # Fine-grained: one task per repo, naturally yields to higher-priority work
    results["ai_repo_created_at"] = {"status": "handled_by_task_queue"}
    logger.info("ai_repo_created_at: delegated to task queue worker")

    # Log sync_log entries for jobs that don't write their own
    run_started = datetime.now(timezone.utc)  # approximate; individual times not tracked for post-loop jobs
    for name, result in results.items():
        _log_job(name, result, run_started)

    # Summary
    errors = [k for k, v in results.items() if isinstance(v, dict) and "error" in v]
    if errors:
        logger.warning(f"⚠ Ingest completed with errors in: {', '.join(errors)}")
        for name in errors:
            logger.warning(f"  {name}: {results[name]['error'][:200]}")
    else:
        logger.info("✓ Ingest completed successfully — all stages passed")

    logger.info(f"Full ingest complete: {results}")
    return results
