import asyncio
import logging

from app.ingest.candidates import ingest_candidate_velocity
from app.ingest.dockerhub import ingest_dockerhub
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
from app.ingest.ai_repo_downloads import ingest_ai_repo_downloads
from app.ingest.public_apis import ingest_public_apis
from app.ingest.api_specs import ingest_api_specs
from app.ingest.package_deps import ingest_package_deps
from app.ingest.hf_datasets import ingest_hf_datasets
from app.ingest.hf_models import ingest_hf_models
from app.ingest.npm_mcp import ingest_npm_mcp
from app.backfill_embeddings import backfill_projects, backfill_methodology, backfill_ai_repos, backfill_public_apis, backfill_hf_datasets, backfill_hf_models
from app.embeddings import is_enabled
from app.views.refresh import refresh_all_views

logger = logging.getLogger(__name__)


async def run_all() -> dict:
    """Run all ingest jobs sequentially, then refresh materialized views."""
    results = {}

    logger.info("Starting full ingest cycle")

    for name, coro in [
        # Phase 1: Fast daily-critical (< 5 min each)
        ("github", ingest_github()),
        ("downloads", ingest_downloads()),
        ("dockerhub", ingest_dockerhub()),
        ("huggingface", ingest_huggingface()),
        ("releases", ingest_releases()),
        ("hn", ingest_hn()),
        ("v2ex", ingest_v2ex()),
        ("trending", ingest_trending()),
        ("newsletters", ingest_newsletters()),
        ("candidate_velocity", ingest_candidate_velocity()),
        # Phase 2: Slow discovery indexes (minutes to hours)
        ("hf_datasets", ingest_hf_datasets()),
        ("hf_models", ingest_hf_models()),
        ("public_apis", ingest_public_apis()),
        ("api_specs", ingest_api_specs()),
        ("package_deps", ingest_package_deps()),
        ("npm_mcp", ingest_npm_mcp()),
        ("ai_repo_downloads", ingest_ai_repo_downloads()),
        ("ai_repos", ingest_ai_repos()),  # Slowest — last
    ]:
        try:
            results[name] = await coro
            logger.info(f"{name}: {results[name]}")
        except Exception as e:
            logger.exception(f"{name} failed: {e}")
            results[name] = {"error": str(e)}

    # Re-match unlinked HN posts against current project list
    try:
        hn_linked = await backfill_hn_links()
        results["hn_backfill"] = {"linked": hn_linked}
        logger.info(f"hn_backfill: {results['hn_backfill']}")
    except Exception as e:
        logger.exception(f"hn_backfill failed: {e}")
        results["hn_backfill"] = {"error": str(e)}

    # Match unlinked HN posts to labs by title
    try:
        hn_lab_linked = await backfill_hn_lab_links()
        results["hn_lab_backfill"] = {"linked": hn_lab_linked}
        logger.info(f"hn_lab_backfill: {results['hn_lab_backfill']}")
    except Exception as e:
        logger.exception(f"hn_lab_backfill failed: {e}")
        results["hn_lab_backfill"] = {"error": str(e)}

    # Match unlinked V2EX posts to labs
    try:
        v2ex_lab_linked = await backfill_v2ex_lab_links()
        results["v2ex_lab_backfill"] = {"linked": v2ex_lab_linked}
        logger.info(f"v2ex_lab_backfill: {results['v2ex_lab_backfill']}")
    except Exception as e:
        logger.exception(f"v2ex_lab_backfill failed: {e}")
        results["v2ex_lab_backfill"] = {"error": str(e)}

    # Sync frontier models from OpenRouter
    try:
        results["models"] = await ingest_models()
        logger.info(f"models: {results['models']}")
    except Exception as e:
        logger.exception(f"models ingest failed: {e}")
        results["models"] = {"error": str(e)}

    # Backfill embeddings for new projects/methodology (before view refresh)
    if is_enabled():
        try:
            proj_count = await backfill_projects()
            meth_count = await backfill_methodology()
            ai_repo_count = await backfill_ai_repos()
            api_count = await backfill_public_apis()
            hf_ds_count = await backfill_hf_datasets()
            hf_model_count = await backfill_hf_models()
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

    logger.info(f"Full ingest complete: {results}")
    return results
