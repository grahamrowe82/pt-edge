from app.queue.handlers.fetch_readme import handle_fetch_readme
from app.queue.handlers.enrich_summary import handle_enrich_summary
from app.queue.handlers.enrich_project_brief import handle_enrich_project_brief
from app.queue.handlers.enrich_domain_brief import handle_enrich_domain_brief
from app.queue.handlers.enrich_landscape_brief import handle_enrich_landscape_brief

TASK_HANDLERS: dict = {
    "fetch_readme": handle_fetch_readme,
    "enrich_summary": handle_enrich_summary,
    "enrich_project_brief": handle_enrich_project_brief,
    "enrich_domain_brief": handle_enrich_domain_brief,
    "enrich_landscape_brief": handle_enrich_landscape_brief,
}
