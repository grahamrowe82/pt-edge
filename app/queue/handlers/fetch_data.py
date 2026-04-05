"""Fetch handlers for all data ingestion sources.

Coarse-grained — each handler delegates to the existing ingest function.
These are fast bulk jobs that complete in minutes.
"""
import logging

logger = logging.getLogger(__name__)


async def handle_fetch_downloads(task: dict) -> dict:
    from app.ingest.downloads import ingest_downloads
    return await ingest_downloads()


async def handle_fetch_dockerhub(task: dict) -> dict:
    from app.ingest.dockerhub import ingest_dockerhub
    return await ingest_dockerhub()


async def handle_fetch_vscode(task: dict) -> dict:
    from app.ingest.vscode_marketplace import ingest_vscode
    return await ingest_vscode()


async def handle_fetch_huggingface(task: dict) -> dict:
    from app.ingest.huggingface import ingest_huggingface
    return await ingest_huggingface()


async def handle_fetch_hn(task: dict) -> dict:
    from app.ingest.hn import ingest_hn
    return await ingest_hn()


async def handle_fetch_v2ex(task: dict) -> dict:
    from app.ingest.v2ex import ingest_v2ex
    return await ingest_v2ex()


async def handle_fetch_trending(task: dict) -> dict:
    from app.ingest.trending import ingest_trending
    return await ingest_trending()


async def handle_fetch_candidates(task: dict) -> dict:
    from app.ingest.candidates import ingest_candidate_velocity
    return await ingest_candidate_velocity()


async def handle_fetch_candidate_watchlist(task: dict) -> dict:
    from app.ingest.candidates import refresh_candidate_watchlist
    return await refresh_candidate_watchlist()


async def handle_fetch_hf_datasets(task: dict) -> dict:
    from app.ingest.hf_datasets import ingest_hf_datasets
    return await ingest_hf_datasets()


async def handle_fetch_hf_models(task: dict) -> dict:
    from app.ingest.hf_models import ingest_hf_models
    return await ingest_hf_models()


async def handle_fetch_public_apis(task: dict) -> dict:
    from app.ingest.public_apis import ingest_public_apis
    return await ingest_public_apis()


async def handle_fetch_api_specs(task: dict) -> dict:
    from app.ingest.api_specs import ingest_api_specs
    return await ingest_api_specs()


async def handle_fetch_package_deps(task: dict) -> dict:
    from app.ingest.package_deps import ingest_package_deps
    return await ingest_package_deps()


async def handle_compute_dep_velocity(task: dict) -> dict:
    from app.ingest.dep_velocity import snapshot_dep_counts
    return await snapshot_dep_counts()


async def handle_fetch_builder_tools(task: dict) -> dict:
    from app.ingest.builder_tools import ingest_builder_tools
    return await ingest_builder_tools()


async def handle_fetch_npm_mcp(task: dict) -> dict:
    from app.ingest.npm_mcp import ingest_npm_mcp
    return await ingest_npm_mcp()


async def handle_fetch_ai_repo_downloads(task: dict) -> dict:
    from app.ingest.ai_repo_downloads import ingest_ai_repo_downloads
    return await ingest_ai_repo_downloads()


async def handle_fetch_ai_repo_commits(task: dict) -> dict:
    from app.ingest.ai_repo_commits import ingest_ai_repo_commits
    return await ingest_ai_repo_commits()


async def handle_fetch_newsletters(task: dict) -> dict:
    from app.ingest.newsletters import ingest_newsletters
    return await ingest_newsletters()


async def handle_fetch_models(task: dict) -> dict:
    from app.ingest.models import ingest_models
    return await ingest_models()
