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
}
