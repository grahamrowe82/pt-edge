import asyncio
import logging
import os

from sqlalchemy.exc import OperationalError

from app.ingest.candidates import ingest_candidate_velocity, refresh_candidate_watchlist
from app.ingest.dockerhub import ingest_dockerhub
from app.ingest.vscode_marketplace import ingest_vscode
from app.ingest.downloads import ingest_downloads
from app.ingest.github import ingest_github
from app.ingest.hn import ingest_hn, backfill_hn_links, backfill_hn_lab_links
from app.ingest.newsletters import ingest_newsletters
from app.ingest.v2ex import ingest_v2ex, backfill_v2ex_lab_links
from app.ingest.models import ingest_models
from app.ingest.huggingface import ingest_huggingface
from app.ingest.releases import ingest_releases
from app.ingest.trending import ingest_trending
from app.ingest.ai_repos import ingest_ai_repos
from app.ingest.ai_repo_commits import ingest_ai_repo_commits
from app.ingest.ai_repo_created_at import ingest_ai_repo_created_at
from app.ingest.ai_repo_downloads import ingest_ai_repo_downloads
from app.ingest.semantic_scholar import ingest_semantic_scholar
from app.ingest.public_apis import ingest_public_apis
from app.ingest.api_specs import ingest_api_specs
from app.ingest.package_deps import ingest_package_deps
from app.ingest.dep_velocity import snapshot_dep_counts
from app.ingest.hf_datasets import ingest_hf_datasets
from app.ingest.hf_models import ingest_hf_models
from app.ingest.npm_mcp import ingest_npm_mcp
from app.ingest.builder_tools import ingest_builder_tools
from app.ingest.ai_repo_package_detect import detect_packages_llm
from app.ingest.ai_repo_subcategory import ingest_subcategories, classify_subcategory_llm
from app.ingest.stack_layer import classify_stack_layers
from app.ingest.hn_llm_match import match_hn_posts_llm
from app.ingest.ai_repo_summaries import generate_ai_summaries
from app.ingest.domain_reassign import reassign_domains
from app.ingest.comparison_sentences import generate_comparison_sentences
from app.backfill_embeddings import backfill_projects, backfill_methodology, backfill_ai_repos, backfill_public_apis, backfill_hf_datasets, backfill_hf_models
from app.briefing_refresh import refresh_briefing_evidence
from app.embeddings import is_enabled
from app.views.refresh import refresh_all_views

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [10, 30, 60]  # seconds — exponential-ish backoff


def _reset_pool():
    """Dispose all SQLAlchemy connection pools to force fresh connections."""
    from app.db import engine, readonly_engine
    engine.dispose()
    readonly_engine.dispose()
    logger.info("DB connection pools disposed — next query will reconnect")


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

    for name, fn in [
        # Phase 1: Fast daily-critical — no LLM calls (< 5 min each)
        ("github", ingest_github),
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
        ("semantic_scholar", ingest_semantic_scholar),
        # ai_repos removed — runs on its own weekly cron (Saturday 12:00 UTC)
        # Phase 3: LLM-dependent (rate-limited, at end so they don't block)
        ("ai_repo_package_detect", detect_packages_llm),
        ("releases", ingest_releases),
        ("newsletters", ingest_newsletters),
    ]:
        try:
            results[name] = await _run_with_retry(name, fn)
            logger.info(f"{name}: {results[name]}")
        except Exception as e:
            logger.exception(f"{name} failed: {e}")
            results[name] = {"error": str(e)}

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

    # LLM-assisted HN matching (residual NULLs after regex backfill)
    try:
        results["hn_llm_match"] = await _run_with_retry("hn_llm_match", match_hn_posts_llm)
        logger.info(f"hn_llm_match: {results['hn_llm_match']}")
    except Exception as e:
        logger.exception(f"hn_llm_match failed: {e}")
        results["hn_llm_match"] = {"error": str(e)}

    # Match unlinked V2EX posts to labs
    try:
        v2ex_lab_linked = await _run_with_retry("v2ex_lab_backfill", backfill_v2ex_lab_links)
        results["v2ex_lab_backfill"] = {"linked": v2ex_lab_linked}
        logger.info(f"v2ex_lab_backfill: {results['v2ex_lab_backfill']}")
    except Exception as e:
        logger.exception(f"v2ex_lab_backfill failed: {e}")
        results["v2ex_lab_backfill"] = {"error": str(e)}

    # Classify MCP repos by subcategory (regex first, then LLM fallback)
    try:
        results["subcategory"] = await _run_with_retry("subcategory", ingest_subcategories)
        logger.info(f"subcategory: {results['subcategory']}")
    except Exception as e:
        logger.exception(f"subcategory failed: {e}")
        results["subcategory"] = {"error": str(e)}

    try:
        results["subcategory_llm"] = await _run_with_retry("subcategory_llm", classify_subcategory_llm)
        logger.info(f"subcategory_llm: {results['subcategory_llm']}")
    except Exception as e:
        logger.exception(f"subcategory_llm failed: {e}")
        results["subcategory_llm"] = {"error": str(e)}

    # Classify projects by AI stack layer
    try:
        results["stack_layer"] = await _run_with_retry("stack_layer", classify_stack_layers)
        logger.info(f"stack_layer: {results['stack_layer']}")
    except Exception as e:
        logger.exception(f"stack_layer failed: {e}")
        results["stack_layer"] = {"error": str(e)}

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

    # Backfill embeddings for new projects/methodology (before view refresh)
    if is_enabled():
        try:
            proj_count = await _run_with_retry("embed_projects", backfill_projects)
            meth_count = await _run_with_retry("embed_methodology", backfill_methodology)
            ai_repo_count = await _run_with_retry("embed_ai_repos", backfill_ai_repos)
            api_count = await _run_with_retry("embed_public_apis", backfill_public_apis)
            hf_ds_count = await _run_with_retry("embed_hf_datasets", backfill_hf_datasets)
            hf_model_count = await _run_with_retry("embed_hf_models", backfill_hf_models)
            results["embeddings"] = {
                "projects": proj_count, "methodology": meth_count,
                "ai_repos": ai_repo_count, "public_apis": api_count,
                "hf_datasets": hf_ds_count, "hf_models": hf_model_count,
            }
            logger.info(f"embeddings: {results['embeddings']}")
        except Exception as e:
            logger.exception(f"embeddings failed: {e}")
            results["embeddings"] = {"error": str(e)}
    else:
        results["embeddings"] = "skipped (no OPENAI_API_KEY)"

    # Refresh materialized views after all ingest jobs complete
    try:
        results["views"] = refresh_all_views()
        logger.info(f"views: {results['views']}")
    except Exception as e:
        logger.exception(f"views failed: {e}")
        results["views"] = {"error": str(e)}

    # Compute content budget from allocation scores (must run after MV refresh)
    try:
        from app.allocation.budget import compute_and_write_budget
        from app.settings import settings as _settings
        results["content_budget"] = compute_and_write_budget(_settings.LLM_BUDGET_MULTIPLIER)
        logger.info(f"content_budget: {results['content_budget']}")
    except Exception as e:
        logger.exception(f"content_budget failed: {e}")
        results["content_budget"] = {"error": str(e)}

    # Content pipelines (allocation-driven — consume content_budget table)
    try:
        results["ai_summaries"] = await _run_with_retry("ai_summaries", generate_ai_summaries)
        logger.info(f"ai_summaries: {results['ai_summaries']}")
    except Exception as e:
        logger.exception(f"ai_summaries failed: {e}")
        results["ai_summaries"] = {"error": str(e)}

    try:
        results["comparison_sentences"] = await _run_with_retry("comparison_sentences", generate_comparison_sentences)
        logger.info(f"comparison_sentences: {results['comparison_sentences']}")
    except Exception as e:
        logger.exception(f"comparison_sentences failed: {e}")
        results["comparison_sentences"] = {"error": str(e)}

    try:
        from app.ingest.project_briefs import generate_repo_briefs
        results["repo_briefs"] = await _run_with_retry("repo_briefs", generate_repo_briefs)
        logger.info(f"repo_briefs: {results['repo_briefs']}")
    except Exception as e:
        logger.exception(f"repo_briefs failed: {e}")
        results["repo_briefs"] = {"error": str(e)}

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

    # Generate LLM project briefs (needs fresh MV data)
    try:
        from app.ingest.project_briefs import generate_project_briefs, generate_domain_briefs
        results["project_briefs"] = await _run_with_retry("project_briefs", generate_project_briefs)
        logger.info(f"project_briefs: {results['project_briefs']}")
    except Exception as e:
        logger.exception(f"project_briefs failed: {e}")
        results["project_briefs"] = {"error": str(e)}

    # Domain + landscape briefs weekly (Sunday)
    from datetime import datetime as _dt, timezone as _tz
    if _dt.now(_tz.utc).weekday() == 6:
        try:
            from app.ingest.project_briefs import generate_domain_briefs
            results["domain_briefs"] = await _run_with_retry("domain_briefs", generate_domain_briefs)
            logger.info(f"domain_briefs: {results['domain_briefs']}")
        except Exception as e:
            logger.exception(f"domain_briefs failed: {e}")
            results["domain_briefs"] = {"error": str(e)}

        try:
            from app.ingest.landscape_briefs import generate_landscape_briefs
            results["landscape_briefs"] = await _run_with_retry("landscape_briefs", generate_landscape_briefs)
            logger.info(f"landscape_briefs: {results['landscape_briefs']}")
        except Exception as e:
            logger.exception(f"landscape_briefs failed: {e}")
            results["landscape_briefs"] = {"error": str(e)}

    # Refresh briefing evidence values against current data
    try:
        results["briefing_refresh"] = await _run_with_retry(
            "briefing_refresh", refresh_briefing_evidence
        )
        logger.info(f"briefing_refresh: {results['briefing_refresh']}")
    except Exception as e:
        logger.exception(f"briefing_refresh failed: {e}")
        results["briefing_refresh"] = {"error": str(e)}

    # Trigger static directory site rebuild
    try:
        import httpx
        deploy_hook = os.environ.get("RENDER_DEPLOY_HOOK_URL")
        if deploy_hook:
            resp = httpx.post(deploy_hook, timeout=30)
            results["static_site"] = {"status": "deploy_triggered", "code": resp.status_code}
            logger.info(f"static_site: deploy triggered ({resp.status_code})")
        else:
            results["static_site"] = "skipped (no RENDER_DEPLOY_HOOK_URL)"
    except Exception as e:
        logger.warning(f"static_site deploy trigger failed: {e}")
        results["static_site"] = {"error": str(e)}

    # Backfill created_at — runs last, uses remaining time in the day.
    # Self-draining: becomes a no-op once all repos have created_at.
    try:
        results["ai_repo_created_at"] = await _run_with_retry(
            "ai_repo_created_at", ingest_ai_repo_created_at
        )
        logger.info(f"ai_repo_created_at: {results['ai_repo_created_at']}")
    except Exception as e:
        logger.exception(f"ai_repo_created_at failed: {e}")
        results["ai_repo_created_at"] = {"error": str(e)}

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
