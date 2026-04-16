"""Task handler registry.

Lightweight handlers run in-process. Heavy handlers (numpy, UMAP, Gemini
backfills) are delegated to subprocesses so the worker never loads their
dependencies and all memory is reclaimed when the subprocess exits.
"""

from domains.cyber.app.queue.handlers.ingest_nvd import handle_ingest_nvd
from domains.cyber.app.queue.handlers.ingest_kev import handle_ingest_kev
from domains.cyber.app.queue.handlers.ingest_epss import handle_ingest_epss
from domains.cyber.app.queue.handlers.ingest_mitre import handle_ingest_mitre
from domains.cyber.app.queue.handlers.ingest_osv import handle_ingest_osv
from domains.cyber.app.queue.handlers.ingest_ghsa import handle_ingest_ghsa
from domains.cyber.app.queue.handlers.ingest_exploit_db import handle_ingest_exploit_db
from domains.cyber.app.queue.handlers.compute_pairs import handle_compute_pairs
from domains.cyber.app.queue.handlers.compute_hypotheses import handle_compute_hypotheses
from domains.cyber.app.queue.handlers.refresh_views import handle_refresh_views

from domains.cyber.app.queue.subprocess_wrapper import run_in_subprocess


# --- Heavy handlers: subprocess-isolated ---

async def handle_compute_embeddings(task: dict) -> dict:
    return await run_in_subprocess(
        "domains.cyber.app.queue.handlers.compute_embeddings",
        "handle_compute_embeddings", task,
    )


async def handle_embed_products(task: dict) -> dict:
    return await run_in_subprocess(
        "domains.cyber.app.queue.handlers.embed_products",
        "_embed_products", task,
    )


async def handle_product_guidance(task: dict) -> dict:
    return await run_in_subprocess(
        "domains.cyber.app.queue.handlers.product_guidance",
        "_run_guidance_pipeline", task,
    )


async def handle_enrich_cve_summaries(task: dict) -> dict:
    return await run_in_subprocess(
        "domains.cyber.app.queue.handlers.enrich_cve_summaries",
        "_enrich_cves", task,
    )


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
    "embed_products": handle_embed_products,
    "product_guidance": handle_product_guidance,
    "enrich_cve_summaries": handle_enrich_cve_summaries,
}
