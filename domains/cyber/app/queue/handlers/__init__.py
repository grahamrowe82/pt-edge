"""Task handler registry."""

from domains.cyber.app.queue.handlers.ingest_nvd import handle_ingest_nvd
from domains.cyber.app.queue.handlers.ingest_kev import handle_ingest_kev
from domains.cyber.app.queue.handlers.ingest_epss import handle_ingest_epss
from domains.cyber.app.queue.handlers.ingest_mitre import handle_ingest_mitre
from domains.cyber.app.queue.handlers.ingest_osv import handle_ingest_osv
from domains.cyber.app.queue.handlers.ingest_ghsa import handle_ingest_ghsa
from domains.cyber.app.queue.handlers.ingest_exploit_db import handle_ingest_exploit_db
from domains.cyber.app.queue.handlers.compute_pairs import handle_compute_pairs
from domains.cyber.app.queue.handlers.compute_hypotheses import handle_compute_hypotheses
from domains.cyber.app.queue.handlers.compute_embeddings import handle_compute_embeddings
from domains.cyber.app.queue.handlers.refresh_views import handle_refresh_views

TASK_HANDLERS: dict = {
    "ingest_nvd": handle_ingest_nvd,
    "ingest_kev": handle_ingest_kev,
    "ingest_epss": handle_ingest_epss,
    "ingest_mitre": handle_ingest_mitre,
    "ingest_osv": handle_ingest_osv,
    "ingest_ghsa": handle_ingest_ghsa,
    "ingest_exploit_db": handle_ingest_exploit_db,
    "compute_pairs": handle_compute_pairs,
    "compute_hypotheses": handle_compute_hypotheses,
    "compute_embeddings": handle_compute_embeddings,
    "refresh_views": handle_refresh_views,
}
