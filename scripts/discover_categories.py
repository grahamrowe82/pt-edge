"""Discover two-level categories via embedding clustering.

For each domain:
1. Pull 1536d embeddings from DB
2. K-means to find broad categories (every repo gets one)
3. HDBSCAN within each category to find specific subcategories (niches)
4. Label all clusters via Haiku
5. Print report (or apply with --apply)

Usage:
    python scripts/discover_categories.py --domain voice-ai
    python scripts/discover_categories.py --domain voice-ai --apply
    python scripts/discover_categories.py --all-domains
"""
import argparse
import asyncio
import json
import logging
import os
import sys

import numpy as np
from sklearn.cluster import KMeans, HDBSCAN
from sklearn.metrics import silhouette_score
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db import engine, readonly_engine
from app.ingest.llm import call_haiku_text

logger = logging.getLogger(__name__)

ALL_DOMAINS = [
    "mcp", "agents", "rag", "ai-coding", "voice-ai",
    "diffusion", "vector-db", "embeddings", "prompt-engineering",
]


def parse_pgvector(text_val):
    return np.fromstring(text_val.strip("[]"), sep=",", dtype=np.float32)


def fetch_repos(domain):
    """Fetch repos with 1536d embeddings for a domain."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, full_name, description, stars,
                   embedding_1536::text as embedding_text
            FROM ai_repos
            WHERE domain = :domain
              AND embedding_1536 IS NOT NULL
            ORDER BY stars DESC NULLS LAST
        """), {"domain": domain}).fetchall()
    return [dict(r._mapping) for r in rows]


def normalise(embeddings):
    """L2-normalise for cosine distance via euclidean."""
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return embeddings / norms


def find_best_k(embeddings, k_range=(4, 16)):
    """Find optimal k for k-means via silhouette score."""
    best_k, best_score = k_range[0], -1
    sample_size = min(5000, len(embeddings))

    for k in range(k_range[0], k_range[1]):
        if k >= len(embeddings):
            break
        km = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = km.fit_predict(embeddings)
        score = silhouette_score(embeddings, labels, sample_size=sample_size)
        logger.info(f"  k={k}: silhouette={score:.3f}")
        if score > best_score:
            best_k, best_score = k, score

    return best_k, best_score


async def label_cluster(domain, top_repos, level="category"):
    """Ask Haiku to name a cluster."""
    repos_text = "\n".join(
        f"- {name}: {desc or 'No description'}"
        for name, desc in top_repos[:15]
    )
    if level == "category":
        instruction = "What BROAD category do these repos belong to?"
    else:
        instruction = "What SPECIFIC niche or subcategory do these repos belong to?"

    prompt = f"""Here are the top repos in a cluster from the "{domain}" domain of AI tools:

{repos_text}

{instruction}
Reply with exactly one line: a short label (1-3 words, lowercase, hyphenated) followed by a colon and a one-sentence description.
Example: text-to-speech: Tools for converting written text into spoken audio"""

    result = await call_haiku_text(prompt, max_tokens=100)
    if not result:
        return "unknown", "Could not label cluster"
    label, _, desc = result.partition(":")
    return label.strip().lower(), desc.strip()


async def discover_domain(domain, apply=False):
    """Full two-pass pipeline for one domain."""
    print(f"\n{'=' * 60}")
    print(f"Discovering categories for: {domain}")
    print(f"{'=' * 60}")

    # Fetch data
    repos = fetch_repos(domain)
    if len(repos) < 30:
        print(f"  Only {len(repos)} repos with 1536d embeddings — skipping (need >= 30)")
        return

    print(f"  {len(repos):,} repos with 1536d embeddings")

    embeddings = np.array([parse_pgvector(r["embedding_text"]) for r in repos])
    embeddings = normalise(embeddings)

    # =====================================================
    # Pass 1: K-means for broad categories
    # =====================================================
    print(f"\nPass 1: Finding broad categories (k-means)...")
    best_k, best_score = find_best_k(embeddings)
    print(f"  Best k={best_k} (silhouette={best_score:.3f})")

    km = KMeans(n_clusters=best_k, n_init=10, random_state=42)
    cat_labels = km.fit_predict(embeddings)
    cat_centroids = km.cluster_centers_

    # Build category info
    categories = {}
    for idx, label in enumerate(cat_labels):
        categories.setdefault(label, []).append(idx)

    # Label categories via Haiku
    print(f"  Labelling {len(categories)} categories via Haiku...")
    cat_meta = {}
    for cat_id, members in sorted(categories.items(), key=lambda x: -len(x[1])):
        top_by_stars = sorted(members, key=lambda i: repos[i]["stars"] or 0, reverse=True)[:15]
        top_repos = [(repos[i]["full_name"], repos[i]["description"]) for i in top_by_stars]
        label, desc = await label_cluster(domain, top_repos, level="category")
        cat_meta[cat_id] = {"label": label, "desc": desc, "count": len(members), "members": members}

    # =====================================================
    # Pass 2: HDBSCAN within each category for subcategories
    # =====================================================
    print(f"\nPass 2: Finding subcategories (HDBSCAN within each category)...")
    sub_meta = {}  # cat_id -> list of subcategory dicts

    for cat_id, info in cat_meta.items():
        members = info["members"]
        if len(members) < 50:
            sub_meta[cat_id] = []
            continue

        subset_embeddings = embeddings[members]
        hdb = HDBSCAN(min_cluster_size=15, min_samples=3, metric="euclidean")
        sub_labels = hdb.fit_predict(subset_embeddings)

        sub_clusters = {}
        for local_idx, sub_label in enumerate(sub_labels):
            if sub_label == -1:
                continue
            sub_clusters.setdefault(sub_label, []).append(members[local_idx])

        sub_list = []
        for sub_id, sub_members in sorted(sub_clusters.items(), key=lambda x: -len(x[1])):
            top_by_stars = sorted(sub_members, key=lambda i: repos[i]["stars"] or 0, reverse=True)[:15]
            top_repos = [(repos[i]["full_name"], repos[i]["description"]) for i in top_by_stars]
            label, desc = await label_cluster(domain, top_repos, level="subcategory")
            sub_list.append({
                "label": label, "desc": desc,
                "count": len(sub_members), "members": sub_members,
                "top_repos": [(repos[i]["full_name"], repos[i]["stars"] or 0) for i in top_by_stars[:5]],
            })
        sub_meta[cat_id] = sub_list

    # =====================================================
    # Print report
    # =====================================================
    print(f"\n{'=' * 60}")
    print(f"=== {domain} ({len(repos):,} repos, {best_k} categories) ===")
    print(f"{'=' * 60}\n")

    for cat_id in sorted(cat_meta.keys(), key=lambda k: -cat_meta[k]["count"]):
        info = cat_meta[cat_id]
        print(f'  Category: "{info["label"]}" ({info["count"]:,} repos)')
        print(f'    {info["desc"]}')
        top_members = sorted(info["members"], key=lambda i: repos[i]["stars"] or 0, reverse=True)[:5]
        print(f'    Top: {", ".join(repos[i]["full_name"] for i in top_members)}')

        subs = sub_meta.get(cat_id, [])
        if subs:
            sub_assigned = sum(s["count"] for s in subs)
            print(f"    Subcategories ({len(subs)}):")
            for s in subs:
                top_names = ", ".join(n for n, _ in s["top_repos"][:3])
                print(f'      - "{s["label"]}" ({s["count"]} repos): {top_names}')
            print(f"      ({info['count'] - sub_assigned:,} repos in category but no subcategory)")
        print()

    # =====================================================
    # Apply if requested
    # =====================================================
    if apply:
        print("Applying labels to database...")
        with engine.connect() as conn:
            # Write categories
            for cat_id, info in cat_meta.items():
                ids = [repos[i]["id"] for i in info["members"]]
                conn.execute(text("""
                    UPDATE ai_repos SET category = :label
                    WHERE id = ANY(:ids)
                """), {"label": info["label"], "ids": ids})

            # Write subcategories
            for cat_id, subs in sub_meta.items():
                for s in subs:
                    ids = [repos[i]["id"] for i in s["members"]]
                    conn.execute(text("""
                        UPDATE ai_repos SET subcategory = :label
                        WHERE id = ANY(:ids)
                    """), {"label": s["label"], "ids": ids})

            # Store centroids
            conn.execute(text("DELETE FROM category_centroids WHERE domain = :domain"), {"domain": domain})
            for cat_id, info in cat_meta.items():
                centroid_text = "[" + ",".join(f"{v:.6f}" for v in cat_centroids[cat_id]) + "]"
                conn.execute(text("""
                    INSERT INTO category_centroids (domain, level, label, parent_label, description, centroid, repo_count)
                    VALUES (:domain, 'category', :label, NULL, :desc, :centroid, :count)
                """), {
                    "domain": domain, "label": info["label"], "desc": info["desc"],
                    "centroid": centroid_text, "count": info["count"],
                })

            conn.commit()

        total_categorised = sum(info["count"] for info in cat_meta.values())
        total_subcategorised = sum(s["count"] for subs in sub_meta.values() for s in subs)
        print(f"  Applied: {total_categorised:,} repos categorised, {total_subcategorised:,} subcategorised")


async def main():
    parser = argparse.ArgumentParser(description="Discover categories via embedding clustering")
    parser.add_argument("--domain", choices=ALL_DOMAINS)
    parser.add_argument("--all-domains", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if args.all_domains:
        domains = ALL_DOMAINS
    elif args.domain:
        domains = [args.domain]
    else:
        parser.error("Specify --domain or --all-domains")

    for domain in domains:
        await discover_domain(domain, apply=args.apply)


if __name__ == "__main__":
    asyncio.run(main())
