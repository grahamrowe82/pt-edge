"""Daily domain reassignment via embedding similarity.

Checks 10,000 repos per run (5 batches of 2,000) against domain
centroids. Repos closer to a different domain get reassigned.

Processes by stars DESC with an offset that advances daily.
Uses a sync_log entry to track progress across runs.
"""
import logging
import time

import numpy as np
from sqlalchemy import text

from app.db import engine, readonly_engine

logger = logging.getLogger(__name__)

BATCH_SIZE = 2000
BATCHES_PER_RUN = 25
MIN_IMPROVEMENT = 0.05


def _parse_pgvector(text_val):
    return np.fromstring(text_val.strip("[]"), sep=",", dtype=np.float32)


def _load_centroids():
    with readonly_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT label, centroid FROM category_centroids WHERE level = 'domain'"
        )).fetchall()
    return {r._mapping["label"]: _parse_pgvector(r._mapping["centroid"]) for r in rows}


def _get_offset():
    """Get current offset from sync_log, or 0 if never run."""
    with readonly_engine.connect() as conn:
        row = conn.execute(text(
            "SELECT records_written FROM sync_log WHERE sync_type = 'domain_reassign' ORDER BY finished_at DESC LIMIT 1"
        )).fetchone()
    return row._mapping["records_written"] if row else 0


def _save_offset(new_offset, reassigned):
    """Save progress so next run continues where we left off."""
    from datetime import datetime, timezone
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO sync_log (sync_type, status, records_written, started_at, finished_at)
            VALUES ('domain_reassign', 'success', :offset, :now, :now)
        """), {"offset": new_offset, "now": datetime.now(timezone.utc)})
        conn.commit()
    logger.info(f"domain_reassign: offset saved at {new_offset}, {reassigned} reassigned this run")


async def reassign_domains():
    """Check 10,000 repos for domain misassignment. Called from daily ingest."""
    centroids = _load_centroids()
    if not centroids:
        logger.warning("No domain centroids found. Run: python scripts/reassign_domains.py --compute-centroids")
        return {"checked": 0, "reassigned": 0, "skipped": "no centroids"}

    domain_labels = list(centroids.keys())
    centroid_matrix = np.array([centroids[d] for d in domain_labels])
    domain_index = {d: i for i, d in enumerate(domain_labels)}

    start_offset = _get_offset()
    total_checked = 0
    total_reassigned = 0

    for batch in range(BATCHES_PER_RUN):
        offset = start_offset + (batch * BATCH_SIZE)

        with readonly_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, full_name, domain, stars, embedding_1536::text as emb
                FROM ai_repos
                WHERE embedding_1536 IS NOT NULL
                ORDER BY stars DESC NULLS LAST
                LIMIT :limit OFFSET :offset
            """), {"limit": BATCH_SIZE, "offset": offset}).fetchall()

        if not rows:
            # We've reached the end of the table — reset offset to 0
            logger.info(f"domain_reassign: reached end of table at offset {offset}, resetting")
            _save_offset(0, total_reassigned)
            return {"checked": total_checked, "reassigned": total_reassigned, "status": "completed_full_pass"}

        reassign_ids = {}  # new_domain -> [repo_ids]

        for r in rows:
            m = r._mapping
            if m["domain"] not in domain_index:
                continue

            vec = _parse_pgvector(m["emb"])
            norm = np.linalg.norm(vec)
            if norm == 0:
                continue
            vec = vec / norm

            sims = centroid_matrix @ vec
            current_idx = domain_index[m["domain"]]
            current_sim = sims[current_idx]
            best_idx = np.argmax(sims)
            best_sim = sims[best_idx]

            if best_idx != current_idx and (best_sim - current_sim) >= MIN_IMPROVEMENT:
                new_domain = domain_labels[best_idx]
                reassign_ids.setdefault(new_domain, []).append(m["id"])

        # Apply this batch's reassignments
        if reassign_ids:
            with engine.connect() as conn:
                for new_domain, ids in reassign_ids.items():
                    conn.execute(text(
                        "UPDATE ai_repos SET domain = :domain WHERE id = ANY(:ids)"
                    ), {"domain": new_domain, "ids": ids})
                conn.commit()

        batch_reassigned = sum(len(ids) for ids in reassign_ids.values())
        total_checked += len(rows)
        total_reassigned += batch_reassigned
        logger.info(f"domain_reassign: batch {batch+1}/{BATCHES_PER_RUN} offset={offset} checked={len(rows)} reassigned={batch_reassigned}")

    new_offset = start_offset + (BATCHES_PER_RUN * BATCH_SIZE)
    _save_offset(new_offset, total_reassigned)

    return {"checked": total_checked, "reassigned": total_reassigned, "offset": new_offset}
