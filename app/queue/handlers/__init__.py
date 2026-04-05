from app.queue.handlers.fetch_readme import handle_fetch_readme
from app.queue.handlers.enrich_summary import handle_enrich_summary

TASK_HANDLERS: dict = {
    "fetch_readme": handle_fetch_readme,
    "enrich_summary": handle_enrich_summary,
}
