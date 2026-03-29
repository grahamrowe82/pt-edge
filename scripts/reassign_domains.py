"""Detect and fix domain misassignments via embedding similarity.

Computes domain centroids from a sample of top repos, then checks repos
in batches against all centroids. Repos closer to a different domain's
centroid than their assigned domain are reassigned.

Designed to run in the daily ingest pipeline (2,000 per run) or as a
standalone script with configurable batch size.

Usage:
    # Compute and store domain centroids (lightweight, run once)
    python scripts/reassign_domains.py --compute-centroids

    # Check and reassign repos (2,000 per run, saves results first)
    python scripts/reassign_domains.py --check --limit 2000

    # Apply saved reassignments
    python scripts/reassign_domains.py --apply-from data/domain_reassignments.json
"""
import argparse
import json
import logging
import os
import sys
import time

import numpy as np
from sqlalchemy import text as sql_text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db import engine, readonly_engine

logger = logging.getLogger(__name__)

SAVE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "domain_reassignments.json")
CENTROID_SAMPLE_SIZE = 1000  # top repos per domain for centroid computation

ALL_DOMAINS = [
    "mcp", "agents", "rag", "ai-coding", "voice-ai",
    "diffusion", "vector-db", "embeddings", "prompt-engineering",
    "ml-frameworks", "llm-tools", "nlp", "transformers",
    "generative-ai", "computer-vision", "data-engineering", "mlops",
]

MIN_IMPROVEMENT = 0.05  # cosine similarity improvement threshold


def parse_pgvector(text_val):
    return np.fromstring(text_val.strip("[]"), sep=",", dtype=np.float32)


def compute_and_store_centroids():
    """Compute domain centroids from top repos and store in category_centroids."""
    print("Computing domain centroids...")

    centroids = {}
    with readonly_engine.connect() as conn:
        for domain in ALL_DOMAINS:
            rows = conn.execute(sql_text("""
                SELECT embedding_1536::text as emb
                FROM ai_repos
                WHERE domain = :domain AND embedding_1536 IS NOT NULL
                ORDER BY stars DESC NULLS LAST
                LIMIT :limit
            """), {"domain": domain, "limit": CENTROID_SAMPLE_SIZE}).fetchall()

            if not rows:
                print(f"  {domain}: no embeddings, skipping")
                continue

            vecs = np.array([parse_pgvector(r._mapping["emb"]) for r in rows])
            centroid = vecs.mean(axis=0)
            norm = np.linalg.norm(centroid)
            if norm > 0:
                centroid = centroid / norm
            centroids[domain] = centroid
            print(f"  {domain}: centroid from {len(rows)} repos")

    # Store centroids
    centroid_text = {}
    with engine.connect() as conn:
        for domain, centroid in centroids.items():
            ct = "[" + ",".join(f"{v:.6f}" for v in centroid) + "]"
            centroid_text[domain] = ct
            conn.execute(sql_text("""
                INSERT INTO category_centroids (domain, level, label, description, centroid, repo_count)
                VALUES (:domain, 'domain', :domain, :desc, :centroid, :count)
                ON CONFLICT (domain, level, label) DO UPDATE SET
                    centroid = EXCLUDED.centroid, repo_count = EXCLUDED.repo_count
            """), {
                "domain": domain, "desc": f"Domain centroid for {domain}",
                "centroid": ct, "count": len(centroids.get(domain, [])),
            })
        conn.commit()

    print(f"Stored {len(centroids)} domain centroids")
    return centroids


def load_centroids():
    """Load domain centroids from category_centroids table."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(sql_text("""
            SELECT label, centroid FROM category_centroids
            WHERE level = 'domain'
        """)).fetchall()

    centroids = {}
    for r in rows:
        m = r._mapping
        centroids[m["label"]] = parse_pgvector(m["centroid"])
    return centroids


def check_repos(limit=2000, offset=0, min_improvement=MIN_IMPROVEMENT):
    """Check a batch of repos for domain misassignment. Light DB load."""
    centroids = load_centroids()
    if not centroids:
        print("No domain centroids found. Run --compute-centroids first.")
        return []

    domain_labels = list(centroids.keys())
    centroid_matrix = np.array([centroids[d] for d in domain_labels])
    domain_index = {d: i for i, d in enumerate(domain_labels)}

    print(f"Checking repos {offset+1}-{offset+limit} by stars...")
    t0 = time.time()

    with readonly_engine.connect() as conn:
        rows = conn.execute(sql_text("""
            SELECT id, full_name, domain, stars, embedding_1536::text as emb
            FROM ai_repos
            WHERE embedding_1536 IS NOT NULL
            ORDER BY stars DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """), {"limit": limit, "offset": offset}).fetchall()

    reassignments = []
    for r in rows:
        m = r._mapping
        if m["domain"] not in domain_index:
            continue

        vec = parse_pgvector(m["emb"])
        norm = np.linalg.norm(vec)
        if norm == 0:
            continue
        vec = vec / norm

        sims = centroid_matrix @ vec
        current_idx = domain_index[m["domain"]]
        current_sim = sims[current_idx]
        best_idx = np.argmax(sims)
        best_sim = sims[best_idx]

        if best_idx != current_idx and (best_sim - current_sim) >= min_improvement:
            reassignments.append({
                "repo_id": m["id"],
                "full_name": m["full_name"],
                "stars": m["stars"],
                "current_domain": m["domain"],
                "new_domain": domain_labels[best_idx],
                "current_sim": round(float(current_sim), 4),
                "new_sim": round(float(best_sim), 4),
                "improvement": round(float(best_sim - current_sim), 4),
            })

    elapsed = time.time() - t0
    print(f"  Checked {len(rows)} repos in {elapsed:.1f}s, {len(reassignments)} flagged")
    return reassignments


def save_results(reassignments, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(reassignments, f, indent=2)
    print(f"Saved {len(reassignments)} reassignments to {path}")


def print_summary(reassignments):
    if not reassignments:
        print("\nNo reassignments needed.")
        return

    flows = {}
    for r in reassignments:
        key = (r["current_domain"], r["new_domain"])
        flows.setdefault(key, []).append(r)

    print(f"\n{'=' * 60}")
    print(f"DOMAIN REASSIGNMENT SUMMARY: {len(reassignments)} repos")
    print(f"{'=' * 60}")

    for (src, dst), items in sorted(flows.items(), key=lambda x: -len(x[1])):
        print(f"\n  {src} -> {dst}: {len(items)} repos")
        for item in sorted(items, key=lambda x: -x.get("stars", 0))[:5]:
            print(f"    {item['full_name']} ({item.get('stars', 0):,} stars, sim: {item['current_sim']:.3f} -> {item['new_sim']:.3f})")


def apply_from_file(path):
    with open(path) as f:
        reassignments = json.load(f)

    if not reassignments:
        print("No reassignments to apply.")
        return

    print(f"Applying {len(reassignments)} domain reassignments...")
    by_domain = {}
    for r in reassignments:
        by_domain.setdefault(r["new_domain"], []).append(r["repo_id"])

    with engine.connect() as conn:
        total = 0
        for new_domain, ids in by_domain.items():
            conn.execute(sql_text("""
                UPDATE ai_repos SET domain = :domain WHERE id = ANY(:ids)
            """), {"domain": new_domain, "ids": ids})
            total += len(ids)
            print(f"  {new_domain}: {len(ids)} repos")
        conn.commit()

    print(f"Applied {total} reassignments. Views will update on next ingest cycle.")


def main():
    parser = argparse.ArgumentParser(description="Domain reassignment via embedding similarity")
    parser.add_argument("--compute-centroids", action="store_true",
                        help="Compute and store domain centroids (lightweight)")
    parser.add_argument("--check", action="store_true",
                        help="Check repos for misassignment and save results")
    parser.add_argument("--limit", type=int, default=2000,
                        help="Number of repos to check per run")
    parser.add_argument("--offset", type=int, default=0,
                        help="Skip first N repos (for batching)")
    parser.add_argument("--apply-from", type=str,
                        help="Apply reassignments from saved JSON file")
    parser.add_argument("--save-path", default=SAVE_PATH)
    parser.add_argument("--min-improvement", type=float, default=MIN_IMPROVEMENT)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if args.apply_from:
        apply_from_file(args.apply_from)
        return

    if args.compute_centroids:
        compute_and_store_centroids()
        return

    if args.check:
        reassignments = check_repos(limit=args.limit, offset=args.offset, min_improvement=args.min_improvement)
        print_summary(reassignments)
        if reassignments:
            save_results(reassignments, args.save_path)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
