from app.queue.handlers.fetch_readme import handle_fetch_readme
from app.queue.handlers.enrich_summary import handle_enrich_summary
from app.queue.handlers.enrich_comparison import handle_enrich_comparison
from app.queue.handlers.enrich_repo_brief import handle_enrich_repo_brief
from app.queue.handlers.enrich_project_brief import handle_enrich_project_brief
from app.queue.handlers.enrich_domain_brief import handle_enrich_domain_brief
from app.queue.handlers.enrich_landscape_brief import handle_enrich_landscape_brief
from app.queue.handlers.backfill_created_at import handle_backfill_created_at
from app.queue.handlers.fetch_github import handle_fetch_github
from app.queue.handlers.fetch_releases import handle_fetch_releases
from app.queue.handlers.compute_mv_refresh import handle_compute_mv_refresh
from app.queue.handlers.compute_content_budget import handle_compute_content_budget
from app.queue.handlers.compute_embeddings import handle_compute_embeddings
from app.queue.handlers.export_static_site import handle_export_static_site
from app.queue.handlers.enrich_subcategory import handle_enrich_subcategory
from app.queue.handlers.enrich_stack_layer import handle_enrich_stack_layer
from app.queue.handlers.enrich_hn_match import handle_enrich_hn_match
from app.queue.handlers.enrich_package_detect import handle_enrich_package_detect
from app.queue.handlers.fetch_data import (
    handle_fetch_downloads, handle_fetch_dockerhub, handle_fetch_vscode,
    handle_fetch_huggingface, handle_fetch_hn, handle_fetch_v2ex,
    handle_fetch_trending, handle_fetch_candidates, handle_fetch_candidate_watchlist,
    handle_fetch_hf_datasets, handle_fetch_hf_models, handle_fetch_public_apis,
    handle_fetch_api_specs, handle_fetch_package_deps, handle_compute_dep_velocity,
    handle_fetch_builder_tools, handle_fetch_npm_mcp, handle_fetch_ai_repo_downloads,
    handle_fetch_ai_repo_commits, handle_fetch_newsletters, handle_fetch_models,
)
from app.queue.handlers.compute_post_process import (
    handle_import_gsc, handle_import_umami, handle_compute_coview,
    handle_compute_hn_backfill, handle_compute_hn_lab_backfill,
    handle_compute_v2ex_lab_backfill, handle_compute_domain_reassign,
    handle_compute_project_linking, handle_compute_briefing_refresh,
    handle_export_dataset, handle_discover_ai_repos, handle_compute_structural,
)
from app.queue.handlers.compute_demand_radar import (
    handle_snapshot_bot_activity,
    handle_detect_bot_sessions,
)

TASK_HANDLERS: dict = {
    "fetch_readme": handle_fetch_readme,
    "enrich_summary": handle_enrich_summary,
    "enrich_comparison": handle_enrich_comparison,
    "enrich_repo_brief": handle_enrich_repo_brief,
    "enrich_project_brief": handle_enrich_project_brief,
    "enrich_domain_brief": handle_enrich_domain_brief,
    "enrich_landscape_brief": handle_enrich_landscape_brief,
    "backfill_created_at": handle_backfill_created_at,
    "fetch_github": handle_fetch_github,
    "fetch_releases": handle_fetch_releases,
    "compute_mv_refresh": handle_compute_mv_refresh,
    "compute_content_budget": handle_compute_content_budget,
    "compute_embeddings": handle_compute_embeddings,
    "export_static_site": handle_export_static_site,
    "enrich_subcategory": handle_enrich_subcategory,
    "enrich_stack_layer": handle_enrich_stack_layer,
    "enrich_hn_match": handle_enrich_hn_match,
    "enrich_package_detect": handle_enrich_package_detect,
    # Wave 7: Data ingestion
    "fetch_downloads": handle_fetch_downloads,
    "fetch_dockerhub": handle_fetch_dockerhub,
    "fetch_vscode": handle_fetch_vscode,
    "fetch_huggingface": handle_fetch_huggingface,
    "fetch_hn": handle_fetch_hn,
    "fetch_v2ex": handle_fetch_v2ex,
    "fetch_trending": handle_fetch_trending,
    "fetch_candidates": handle_fetch_candidates,
    "fetch_candidate_watchlist": handle_fetch_candidate_watchlist,
    "fetch_hf_datasets": handle_fetch_hf_datasets,
    "fetch_hf_models": handle_fetch_hf_models,
    "fetch_public_apis": handle_fetch_public_apis,
    "fetch_api_specs": handle_fetch_api_specs,
    "fetch_package_deps": handle_fetch_package_deps,
    "compute_dep_velocity": handle_compute_dep_velocity,
    "fetch_builder_tools": handle_fetch_builder_tools,
    "fetch_npm_mcp": handle_fetch_npm_mcp,
    "fetch_ai_repo_downloads": handle_fetch_ai_repo_downloads,
    "fetch_ai_repo_commits": handle_fetch_ai_repo_commits,
    "fetch_newsletters": handle_fetch_newsletters,
    "fetch_models": handle_fetch_models,
    # Wave 7: Analytics + post-processing
    "import_gsc": handle_import_gsc,
    "import_umami": handle_import_umami,
    "compute_coview": handle_compute_coview,
    "compute_hn_backfill": handle_compute_hn_backfill,
    "compute_hn_lab_backfill": handle_compute_hn_lab_backfill,
    "compute_v2ex_lab_backfill": handle_compute_v2ex_lab_backfill,
    "compute_domain_reassign": handle_compute_domain_reassign,
    "compute_project_linking": handle_compute_project_linking,
    "compute_briefing_refresh": handle_compute_briefing_refresh,
    "export_dataset": handle_export_dataset,
    "discover_ai_repos": handle_discover_ai_repos,
    "compute_structural": handle_compute_structural,
    # Demand Radar
    "snapshot_bot_activity": handle_snapshot_bot_activity,
    "detect_bot_sessions": handle_detect_bot_sessions,
}
