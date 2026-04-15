"""Embed products into product_metadata for category discovery and peer comparison.

Builds rich embedding text from product name, vendor, type, and top CWE weakness
types. Stores embeddings in the product_metadata table for downstream clustering.
"""

import asyncio
import logging

from sqlalchemy import text

from domains.cyber.app.db import engine
from domains.cyber.app.embeddings import embed_batch, build_product_text, is_enabled

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def _fetch_products_to_embed() -> list[dict]:
    """Get products that need embeddings (score >= 1 OR cve_count >= 5)."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT p.vendor_key, p.product_key, p.display_name,
                   p.vendor_name, p.part, p.cve_count
            FROM mv_product_scores p
            LEFT JOIN product_metadata pm
                ON pm.vendor_key = p.vendor_key AND pm.product_key = p.product_key
            WHERE (p.composite_score >= 1 OR p.cve_count >= 5)
              AND pm.embedding IS NULL
            ORDER BY p.cve_count DESC
        """)).mappings().fetchall()
    return [dict(r) for r in rows]


def _fetch_product_weaknesses(vendor_keys: list[str], product_keys: list[str]) -> dict:
    """Fetch top 5 CWE weakness names for a batch of products."""
    if not vendor_keys:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            WITH product_weaknesses AS (
                SELECT
                    split_part(s.cpe_id, ':', 4) AS vk,
                    split_part(s.cpe_id, ':', 5) AS pk,
                    w.name AS weakness_name,
                    COUNT(DISTINCT cs.cve_id) AS cnt
                FROM software s
                JOIN cve_software cs ON cs.software_id = s.id
                JOIN cve_weaknesses cw ON cw.cve_id = cs.cve_id
                JOIN weaknesses w ON w.id = cw.weakness_id
                WHERE split_part(s.cpe_id, ':', 4) = ANY(:vks)
                  AND split_part(s.cpe_id, ':', 5) = ANY(:pks)
                GROUP BY 1, 2, 3
            ),
            ranked AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY vk, pk ORDER BY cnt DESC) AS rn
                FROM product_weaknesses
            )
            SELECT vk, pk, weakness_name FROM ranked WHERE rn <= 5
        """), {"vks": vendor_keys, "pks": product_keys}).fetchall()

    result = {}
    for r in rows:
        key = f"{r[0]}/{r[1]}"
        result.setdefault(key, []).append(r[2])
    return result


def _upsert_embeddings(batch: list[tuple]):
    """Upsert product embeddings into product_metadata."""
    with engine.connect() as conn:
        for vendor_key, product_key, embedding in batch:
            conn.execute(text("""
                INSERT INTO product_metadata (vendor_key, product_key, embedding)
                VALUES (:vk, :pk, :emb)
                ON CONFLICT (vendor_key, product_key) DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    updated_at = now()
            """), {"vk": vendor_key, "pk": product_key, "emb": str(embedding)})
        conn.commit()


async def _embed_products():
    """Main embedding pipeline."""
    if not is_enabled():
        logger.info("OpenAI not configured — skipping product embeddings")
        return {"embedded": 0}

    products = _fetch_products_to_embed()
    if not products:
        logger.info("All products already embedded")
        return {"embedded": 0}

    logger.info(f"Embedding {len(products)} products...")
    total_embedded = 0

    for start in range(0, len(products), BATCH_SIZE):
        batch = products[start:start + BATCH_SIZE]
        vks = [p["vendor_key"] for p in batch]
        pks = [p["product_key"] for p in batch]

        # Fetch weakness profiles for this batch
        weaknesses = _fetch_product_weaknesses(vks, pks)

        # Build embedding texts
        texts = []
        for p in batch:
            key = f"{p['vendor_key']}/{p['product_key']}"
            top_w = weaknesses.get(key, [])
            texts.append(build_product_text(
                display_name=p["display_name"],
                vendor_name=p["vendor_name"],
                part=p["part"],
                top_weaknesses=top_w,
                cve_count=p["cve_count"],
            ))

        # Embed batch
        embeddings = await embed_batch(texts)

        # Upsert successes
        to_upsert = []
        for p, emb in zip(batch, embeddings):
            if emb is not None:
                to_upsert.append((p["vendor_key"], p["product_key"], emb))
                total_embedded += 1

        if to_upsert:
            _upsert_embeddings(to_upsert)

        logger.info(f"  Batch {start}-{start + len(batch)}: {len(to_upsert)} embedded")

    return {"embedded": total_embedded}


async def handle_embed_products(task_row: dict) -> dict:
    """Task handler entry point."""
    return await _embed_products()
