"""Weekly structural computation for PT-Edge.

Runs expensive tasks that don't need daily refresh:
1. Comparison pair discovery (embedding similarity per category)
2. Write comparison placeholders for Haiku backfill
3. Domain centroid recomputation
4. Display label generation for new categories

Results stored in structural_cache table (JSONB) for fast startup reads.

Usage:
    python scripts/weekly_structural.py                    # all domains
    python scripts/weekly_structural.py --domain vector-db  # single domain
"""
import argparse
import asyncio
import json
import logging
import os
import sys
import time

import numpy as np
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db import engine, readonly_engine

logger = logging.getLogger(__name__)

ALL_DOMAINS = [
    "mcp", "agents", "rag", "ai-coding", "voice-ai",
    "diffusion", "vector-db", "embeddings", "prompt-engineering",
    "ml-frameworks", "llm-tools", "nlp", "transformers",
    "generative-ai", "computer-vision", "data-engineering", "mlops",
]

DOMAIN_VIEWS = {
    "mcp": "mv_mcp_quality", "agents": "mv_agents_quality",
    "rag": "mv_rag_quality", "ai-coding": "mv_ai_coding_quality",
    "voice-ai": "mv_voice_ai_quality", "diffusion": "mv_diffusion_quality",
    "vector-db": "mv_vector_db_quality", "embeddings": "mv_embeddings_quality",
    "prompt-engineering": "mv_prompt_eng_quality",
    "ml-frameworks": "mv_ml_frameworks_quality", "llm-tools": "mv_llm_tools_quality",
    "nlp": "mv_nlp_quality", "transformers": "mv_transformers_quality",
    "generative-ai": "mv_generative_ai_quality",
    "computer-vision": "mv_computer_vision_quality",
    "data-engineering": "mv_data_engineering_quality",
    "mlops": "mv_mlops_quality",
}

MIN_QUALITY_SCORE = 20


def parse_pgvector(t):
    return np.fromstring(t.strip("[]"), sep=",", dtype=np.float32)


def dynamic_threshold(score_a, score_b):
    ms = max(score_a, score_b)
    if ms >= 70: return 0.65
    elif ms >= 50: return 0.72
    elif ms >= 30: return 0.78
    else: return 0.85


def discover_comparison_pairs(domain):
    """Find comparison pairs for one domain. Returns list of pair dicts."""
    view = DOMAIN_VIEWS.get(domain)
    if not view:
        return []

    t0 = time.time()

    # Load all qualifying servers
    with readonly_engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT full_name, subcategory, quality_score, quality_tier
            FROM {view}
            WHERE quality_score >= :min AND description IS NOT NULL AND description != ''
            ORDER BY quality_score DESC
        """), {"min": MIN_QUALITY_SCORE}).fetchall()

    servers = [dict(r._mapping) for r in rows]

    # Group by subcategory
    by_cat = {}
    for s in servers:
        cat = s.get("subcategory") or "uncategorized"
        by_cat.setdefault(cat, []).append(s)

    # For each category, fetch embeddings and compute pairs
    all_pairs = []
    for cat, cat_servers in by_cat.items():
        if len(cat_servers) < 2:
            continue

        top = cat_servers[:20]
        names = [s["full_name"] for s in top]

        with readonly_engine.connect() as conn:
            emb_rows = conn.execute(text("""
                SELECT full_name, embedding_1536::text as emb
                FROM ai_repos
                WHERE full_name = ANY(:names) AND embedding_1536 IS NOT NULL
            """), {"names": names}).fetchall()

        emb_map = {}
        for r in emb_rows:
            m = r._mapping
            vec = parse_pgvector(m["emb"])
            norm = np.linalg.norm(vec)
            emb_map[m["full_name"]] = vec / norm if norm > 0 else vec

        if len(emb_map) < 2:
            continue

        indexed = [(s, emb_map[s["full_name"]]) for s in top if s["full_name"] in emb_map]

        for i, (a, va) in enumerate(indexed):
            for j, (b, vb) in enumerate(indexed):
                if j <= i:
                    continue

                # Skip forks: same repo name with different owner
                repo_a = a["full_name"].split("/")[1] if "/" in a["full_name"] else a["full_name"]
                repo_b = b["full_name"].split("/")[1] if "/" in b["full_name"] else b["full_name"]
                if repo_a == repo_b:
                    continue

                # Skip near-identical embeddings (similarity > 0.95 = likely fork/clone)
                sim = float(va @ vb)
                if sim > 0.95:
                    continue

                thresh = dynamic_threshold(a["quality_score"], b["quality_score"])
                if sim >= thresh:
                    # Higher score first
                    if a["quality_score"] < b["quality_score"]:
                        a, b = b, a
                    slug = f"{a['full_name'].replace('/', '-')}-vs-{b['full_name'].replace('/', '-')}"
                    all_pairs.append({
                        "repo_a": a["full_name"],
                        "repo_b": b["full_name"],
                        "slug": slug,
                        "category": cat,
                        "similarity": round(sim, 4),
                    })

    elapsed = time.time() - t0
    logger.info(f"  {domain}: {len(all_pairs)} pairs from {len(by_cat)} categories in {elapsed:.1f}s")
    return all_pairs


def store_pairs(domain, pairs):
    """Write comparison pairs to structural_cache."""
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO structural_cache (key, value, updated_at)
            VALUES (:key, :value, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """), {"key": f"comparison_pairs:{domain}", "value": json.dumps(pairs)})
        conn.commit()


def write_placeholders(domain, pairs):
    """Insert placeholder rows into comparison_sentences for Haiku backfill."""
    if not pairs:
        return 0

    names = set()
    for p in pairs:
        names.add(p["repo_a"])
        names.add(p["repo_b"])

    with readonly_engine.connect() as conn:
        rows = conn.execute(text("SELECT id, full_name FROM ai_repos WHERE full_name = ANY(:names)"),
                            {"names": list(names)}).fetchall()
    id_map = {r._mapping["full_name"]: r._mapping["id"] for r in rows}

    written = 0
    with engine.connect() as conn:
        for p in pairs:
            a_id = id_map.get(p["repo_a"])
            b_id = id_map.get(p["repo_b"])
            if a_id and b_id:
                conn.execute(text("""
                    INSERT INTO comparison_sentences (repo_a_id, repo_b_id, domain, subcategory)
                    VALUES (:a, :b, :domain, :cat)
                    ON CONFLICT (repo_a_id, repo_b_id) DO NOTHING
                """), {"a": a_id, "b": b_id, "domain": domain, "cat": p["category"]})
                written += 1
        conn.commit()

    return written


def recompute_centroids():
    """Recompute domain centroids for domain reassignment."""
    logger.info("Recomputing domain centroids...")
    from scripts.reassign_domains import compute_and_store_centroids
    compute_and_store_centroids()


async def label_new_categories():
    """Generate display labels for any new categories missing them."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT domain, label FROM category_centroids WHERE display_label IS NULL"
        )).fetchall()

    unlabelled = [(r._mapping["domain"], r._mapping["label"]) for r in rows]
    if not unlabelled:
        logger.info("No new categories need labelling")
        return

    logger.info(f"Labelling {len(unlabelled)} new categories...")
    from app.ingest.llm import call_haiku_text
    from scripts.fix_category_labels import generate_labels, apply_labels, save_labels

    results = await generate_labels(unlabelled)
    apply_labels(results)
    logger.info(f"Labelled {len(results)} new categories")


def main():
    parser = argparse.ArgumentParser(description="Weekly structural computation")
    parser.add_argument("--domain", choices=ALL_DOMAINS, help="Single domain (default: all)")
    parser.add_argument("--skip-centroids", action="store_true")
    parser.add_argument("--skip-labels", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    domains = [args.domain] if args.domain else ALL_DOMAINS

    # Step 1: Comparison pair discovery
    logger.info("=== Step 1: Comparison pair discovery ===")
    total_pairs = 0
    for domain in domains:
        pairs = discover_comparison_pairs(domain)
        store_pairs(domain, pairs)
        placeholders = write_placeholders(domain, pairs)
        total_pairs += len(pairs)
        logger.info(f"  {domain}: {len(pairs)} pairs cached, {placeholders} placeholders written")

    logger.info(f"Total: {total_pairs} comparison pairs across {len(domains)} domains")

    # Step 2: Domain centroids
    if not args.skip_centroids:
        logger.info("=== Step 2: Domain centroid recomputation ===")
        recompute_centroids()

    # Step 3: Display labels for new categories
    if not args.skip_labels:
        logger.info("=== Step 3: Display labels for new categories ===")
        asyncio.run(label_new_categories())

    logger.info("=== Weekly structural computation complete ===")


if __name__ == "__main__":
    main()
