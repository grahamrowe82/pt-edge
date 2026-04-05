from app.queue.handlers.fetch_readme import handle_fetch_readme
from app.queue.handlers.enrich_summary import handle_enrich_summary
from app.queue.handlers.enrich_comparison import handle_enrich_comparison
from app.queue.handlers.enrich_repo_brief import handle_enrich_repo_brief

TASK_HANDLERS: dict = {
    "fetch_readme": handle_fetch_readme,
    "enrich_summary": handle_enrich_summary,
    "enrich_comparison": handle_enrich_comparison,
    "enrich_repo_brief": handle_enrich_repo_brief,
}
