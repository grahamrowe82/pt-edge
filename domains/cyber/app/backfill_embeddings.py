"""Backfill embeddings for all entity types.

Queries entities with NULL embeddings, builds text, embeds in batches,
and updates the embedding column. Designed to be called by the
compute_embeddings task handler.
"""

import logging
from datetime import datetime, timezone

from psycopg2.extras import execute_values
from sqlalchemy import text

from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.embeddings import (
    embed_batch,
    build_cve_text,
    build_software_text,
    build_vendor_text,
    build_weakness_text,
    build_technique_text,
    build_pattern_text,
    is_enabled,
)
from domains.cyber.app.models import SyncLog

logger = logging.getLogger(__name__)

QUERY_BATCH = 2000


def _log_sync(sync_type: str, started: datetime, records: int, status: str = "success"):
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type=sync_type,
            status=status,
            records_written=records,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()


async def _backfill_entity(
    table: str,
    query_sql: str,
    text_builder: callable,
    field_map: dict,
) -> int:
    """Generic backfill loop for any entity type.

    Args:
        table: SQL table name (safe — from our code, not user input)
        query_sql: SELECT query for entities with NULL embedding
        text_builder: function to build embedding text from entity dict
        field_map: mapping from query columns to text_builder kwargs
    """
    if not is_enabled():
        return 0

    total = 0
    while True:
        with engine.connect() as conn:
            rows = conn.execute(text(query_sql), {"lim": QUERY_BATCH}).fetchall()

        if not rows:
            break

        entities = [dict(r._mapping) for r in rows]
        texts = [text_builder(**{k: e.get(v) for k, v in field_map.items()}) for e in entities]

        embeddings = await embed_batch(texts)

        updates = []
        for entity, emb in zip(entities, embeddings):
            if emb is not None:
                updates.append((str(emb), entity["id"]))

        if updates:
            raw = engine.raw_connection()
            try:
                cur = raw.cursor()
                execute_values(
                    cur,
                    f"UPDATE {table} SET embedding = data.emb::vector, updated_at = now() "
                    f"FROM (VALUES %s) AS data(emb, id) WHERE {table}.id = data.id",
                    updates,
                    template="(%s, %s)",
                    page_size=500,
                )
                raw.commit()
                total += len(updates)
            finally:
                raw.close()

        logger.info(f"  {table}: embedded {total} so far ({len(rows)} this batch)")

    return total


async def backfill_cve_embeddings() -> int:
    return await _backfill_entity(
        table="cves",
        query_sql="""
            SELECT id, cve_id, description, attack_vector, attack_complexity
            FROM cves WHERE embedding IS NULL AND cvss_base_score IS NOT NULL
            LIMIT :lim
        """,
        text_builder=build_cve_text,
        field_map={
            "cve_id": "cve_id",
            "description": "description",
            "attack_vector": "attack_vector",
            "attack_complexity": "attack_complexity",
        },
    )


async def backfill_software_embeddings() -> int:
    return await _backfill_entity(
        table="software",
        query_sql="""
            SELECT s.id, s.name, v.name AS vendor_name, s.version, s.part
            FROM software s
            LEFT JOIN vendors v ON v.id = s.vendor_id
            WHERE s.embedding IS NULL
            LIMIT :lim
        """,
        text_builder=build_software_text,
        field_map={
            "name": "name",
            "vendor_name": "vendor_name",
            "version": "version",
            "part": "part",
        },
    )


async def backfill_vendor_embeddings() -> int:
    return await _backfill_entity(
        table="vendors",
        query_sql="""
            SELECT id, name, product_count
            FROM vendors WHERE embedding IS NULL
            LIMIT :lim
        """,
        text_builder=build_vendor_text,
        field_map={
            "name": "name",
            "product_count": "product_count",
        },
    )


async def backfill_weakness_embeddings() -> int:
    return await _backfill_entity(
        table="weaknesses",
        query_sql="""
            SELECT id, cwe_id, name, description, abstraction
            FROM weaknesses WHERE embedding IS NULL
            LIMIT :lim
        """,
        text_builder=build_weakness_text,
        field_map={
            "cwe_id": "cwe_id",
            "name": "name",
            "description": "description",
            "abstraction": "abstraction",
        },
    )


async def backfill_technique_embeddings() -> int:
    return await _backfill_entity(
        table="techniques",
        query_sql="""
            SELECT id, technique_id, name, description, platforms
            FROM techniques WHERE embedding IS NULL
            LIMIT :lim
        """,
        text_builder=build_technique_text,
        field_map={
            "technique_id": "technique_id",
            "name": "name",
            "description": "description",
            "platforms": "platforms",
        },
    )


async def backfill_pattern_embeddings() -> int:
    return await _backfill_entity(
        table="attack_patterns",
        query_sql="""
            SELECT id, capec_id, name, description, severity
            FROM attack_patterns WHERE embedding IS NULL
            LIMIT :lim
        """,
        text_builder=build_pattern_text,
        field_map={
            "capec_id": "capec_id",
            "name": "name",
            "description": "description",
            "severity": "severity",
        },
    )


async def backfill_all() -> dict:
    """Run all entity type backfills. Returns counts."""
    started = datetime.now(timezone.utc)
    logger.info("Embedding backfill starting...")

    cves = await backfill_cve_embeddings()
    software = await backfill_software_embeddings()
    vendors = await backfill_vendor_embeddings()
    weaknesses = await backfill_weakness_embeddings()
    techniques = await backfill_technique_embeddings()
    patterns = await backfill_pattern_embeddings()

    total = cves + software + vendors + weaknesses + techniques + patterns
    _log_sync("embed_entities", started, total)
    logger.info(
        f"Embedding backfill complete: {cves} CVEs, {software} software, "
        f"{vendors} vendors, {weaknesses} weaknesses, {techniques} techniques, "
        f"{patterns} patterns"
    )

    return {
        "cves": cves, "software": software, "vendors": vendors,
        "weaknesses": weaknesses, "techniques": techniques, "patterns": patterns,
        "total": total,
    }
