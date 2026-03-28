"""Discover two-level categories via UMAP + HDBSCAN + LLM labelling.

Based on best practices from taxonomy construction literature:
1. UMAP reduces 1536d → 30d (avoids curse of dimensionality)
2. HDBSCAN finds natural clusters (allows noise/outliers)
3. Haiku labels clusters from representative + boundary samples
4. Recursive: large clusters get re-projected and re-clustered
5. Post-processing: LLM deduplicates and scopes sibling categories

Usage:
    python scripts/discover_categories.py --domain voice-ai
    python scripts/discover_categories.py --domain voice-ai --apply
    python scripts/discover_categories.py --all-domains
"""
import argparse
import asyncio
import logging
import os
import sys

import numpy as np
from sklearn.cluster import HDBSCAN
from sqlalchemy import text as sql_text
import umap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db import engine, readonly_engine
from app.ingest.llm import call_haiku_text

logger = logging.getLogger(__name__)

ALL_DOMAINS = [
    "mcp", "agents", "rag", "ai-coding", "voice-ai",
    "diffusion", "vector-db", "embeddings", "prompt-engineering",
]

# Clusters smaller than this get merged into nearest sibling
MIN_CLUSTER_SIZE = 15
# Clusters larger than this get recursively split
SHARD_THRESHOLD = 400
# Maximum recursion depth
MAX_DEPTH = 2
# UMAP target dimensions
UMAP_DIMS = 30


def parse_pgvector(text_val):
    return np.fromstring(text_val.strip("[]"), sep=",", dtype=np.float32)


def fetch_repos(domain):
    with readonly_engine.connect() as conn:
        rows = conn.execute(sql_text("""
            SELECT id, full_name, description, stars,
                   embedding_1536::text as embedding_text
            FROM ai_repos
            WHERE domain = :domain AND embedding_1536 IS NOT NULL
            ORDER BY stars DESC NULLS LAST
        """), {"domain": domain}).fetchall()
    return [dict(r._mapping) for r in rows]


def reduce_dims(embeddings, n_components=UMAP_DIMS):
    """UMAP reduction — critical for clustering quality."""
    reducer = umap.UMAP(
        n_components=n_components,
        n_neighbors=20,
        min_dist=0.0,  # tight clusters, not for visualization
        metric="cosine",
        random_state=42,
    )
    return reducer.fit_transform(embeddings)


def cluster(reduced_embeddings):
    """HDBSCAN on UMAP-reduced embeddings."""
    clusterer = HDBSCAN(
        min_cluster_size=MIN_CLUSTER_SIZE,
        min_samples=5,
        metric="euclidean",
    )
    labels = clusterer.fit_predict(reduced_embeddings)
    return labels


async def label_cluster(domain, centroid_samples, boundary_samples, parent_label=None, sibling_labels=None):
    """Label a cluster using representative + boundary samples, with scope definition."""
    centroid_text = "\n".join(f"- {n}: {d or 'No desc'}" for n, d in centroid_samples)
    boundary_text = "\n".join(f"- {n}: {d or 'No desc'}" for n, d in boundary_samples)

    parent_ctx = f'\nThis is a subcategory within "{parent_label}".' if parent_label else ""
    sibling_ctx = ""
    if sibling_labels:
        sibling_ctx = f'\nSibling categories already named: {", ".join(sibling_labels)}. Your label MUST be distinct from these.'

    prompt = f"""You are building a hierarchical taxonomy for a directory of {domain} AI tools.

These repos were automatically grouped together.

Representative repos (core of this group):
{centroid_text}

Boundary repos (edge of this group):
{boundary_text}
{parent_ctx}{sibling_ctx}

Provide exactly 2 lines:
1. A concise category label (2-4 words, lowercase, hyphenated) — think "what would someone Google?"
2. A scope definition: what belongs here and what does NOT belong here

Example:
voice-cloning
Tools for cloning and synthesizing voices from audio samples. Does NOT include general text-to-speech or speech recognition."""

    result = await call_haiku_text(prompt, max_tokens=150)
    if not result:
        return "unknown", "Could not label"
    lines = result.strip().split("\n")
    label = lines[0].strip().lower().strip('"\'')
    scope = lines[1].strip() if len(lines) > 1 else ""
    return label, scope


async def deduplicate_siblings(domain, categories):
    """Post-processing: ask LLM to merge or re-scope overlapping siblings."""
    if len(categories) <= 2:
        return categories

    cat_descriptions = "\n".join(
        f'- "{c["label"]}" ({c["count"]} repos): {c["scope"]}'
        for c in categories
    )
    prompt = f"""You are reviewing category labels for a {domain} AI tools directory.

These are sibling categories at the same level:
{cat_descriptions}

Are any of these overlapping or redundant? If so, suggest merges.
For each merge, output: MERGE "label1" INTO "label2"
If a label is vague or too broad, suggest a rename: RENAME "old" TO "new"
If everything is fine, output: OK

Only output MERGE/RENAME/OK lines, nothing else."""

    result = await call_haiku_text(prompt, max_tokens=300)
    if not result or "OK" in result.upper().split("\n")[0]:
        return categories

    # Apply merges
    merged = {c["label"]: c for c in categories}
    for line in result.strip().split("\n"):
        line = line.strip()
        if line.startswith("MERGE"):
            parts = line.split('"')
            if len(parts) >= 4:
                src, dst = parts[1], parts[3]
                if src in merged and dst in merged:
                    merged[dst]["count"] += merged[src]["count"]
                    merged[dst]["member_indices"].extend(merged[src]["member_indices"])
                    del merged[src]
                    logger.info(f"  Merged '{src}' into '{dst}'")
        elif line.startswith("RENAME"):
            parts = line.split('"')
            if len(parts) >= 4:
                old, new = parts[1], parts[3]
                if old in merged:
                    merged[old]["label"] = new
                    merged[new] = merged.pop(old)
                    logger.info(f"  Renamed '{old}' to '{new}'")

    return list(merged.values())


def get_samples(repos, indices, embeddings_reduced, n_centroid=10, n_boundary=5):
    """Get representative (near centroid) and boundary (far from centroid) samples."""
    if len(indices) == 0:
        return [], []

    subset = embeddings_reduced[indices]
    centroid = subset.mean(axis=0)
    distances = np.linalg.norm(subset - centroid, axis=1)

    # Sort by distance to centroid
    sorted_by_dist = np.argsort(distances)

    # Closest = representative
    centroid_idx = sorted_by_dist[:n_centroid]
    centroid_samples = [(repos[indices[i]]["full_name"], repos[indices[i]]["description"]) for i in centroid_idx]

    # Farthest = boundary
    boundary_idx = sorted_by_dist[-n_boundary:]
    boundary_samples = [(repos[indices[i]]["full_name"], repos[indices[i]]["description"]) for i in boundary_idx]

    return centroid_samples, boundary_samples


async def discover_level(domain, repos, embeddings, depth=0, parent_label=None):
    """Discover categories at one level, recursing into large clusters."""
    indent = "  " * depth

    # UMAP reduction at this level (re-project for each sub-corpus)
    print(f"{indent}UMAP {len(repos)} repos → {UMAP_DIMS}d...")
    if len(repos) < UMAP_DIMS + 2:
        print(f"{indent}  Too few repos for UMAP, skipping level")
        return [{"label": parent_label or "general", "count": len(repos),
                 "scope": "", "member_indices": list(range(len(repos))), "children": []}]

    reduced = reduce_dims(embeddings)

    # Cluster
    labels = cluster(reduced)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    noise_count = (labels == -1).sum()
    print(f"{indent}  {n_clusters} clusters, {noise_count} noise")

    if n_clusters == 0:
        return [{"label": parent_label or "general", "count": len(repos),
                 "scope": "", "member_indices": list(range(len(repos))), "children": []}]

    # Build cluster info
    clusters = {}
    for idx, label in enumerate(labels):
        if label == -1:
            clusters.setdefault(-1, []).append(idx)
        else:
            clusters.setdefault(label, []).append(idx)

    # Label each cluster
    print(f"{indent}  Labelling clusters...")
    categories = []
    assigned_labels = []

    for cluster_id in sorted(clusters.keys()):
        if cluster_id == -1:
            continue
        indices = clusters[cluster_id]
        centroid_samples, boundary_samples = get_samples(repos, indices, reduced)
        label, scope = await label_cluster(domain, centroid_samples, boundary_samples,
                                           parent_label=parent_label, sibling_labels=assigned_labels)
        assigned_labels.append(label)
        categories.append({
            "label": label, "scope": scope, "count": len(indices),
            "member_indices": indices, "children": [],
        })

    # Assign noise to nearest cluster
    if -1 in clusters and clusters[-1]:
        noise_indices = clusters[-1]
        noise_reduced = reduced[noise_indices]
        # Compute centroids of real clusters
        centroids = []
        for c in categories:
            c_reduced = reduced[c["member_indices"]]
            centroids.append(c_reduced.mean(axis=0))
        centroids = np.array(centroids)

        for ni in noise_indices:
            dists = np.linalg.norm(centroids - reduced[ni], axis=1)
            nearest = np.argmin(dists)
            categories[nearest]["member_indices"].append(ni)
            categories[nearest]["count"] += 1

        print(f"{indent}  Assigned {len(noise_indices)} noise repos to nearest categories")

    # Deduplicate siblings
    categories = await deduplicate_siblings(domain, categories)

    # Print summary
    for c in sorted(categories, key=lambda x: -x["count"]):
        top_by_stars = sorted(c["member_indices"], key=lambda i: repos[i]["stars"] or 0, reverse=True)[:5]
        top_names = ", ".join(repos[i]["full_name"].split("/")[-1] for i in top_by_stars)
        print(f"{indent}  \"{c['label']}\" ({c['count']}) — {top_names}")

    # Recurse into large clusters
    if depth < MAX_DEPTH:
        for c in categories:
            if c["count"] > SHARD_THRESHOLD:
                print(f"{indent}  → Sharding \"{c['label']}\" ({c['count']} > {SHARD_THRESHOLD})...")
                sub_repos = [repos[i] for i in c["member_indices"]]
                sub_embeddings = embeddings[c["member_indices"]]
                c["children"] = await discover_level(
                    domain, sub_repos, sub_embeddings,
                    depth=depth + 1, parent_label=c["label"],
                )

    return categories


def print_tree(categories, depth=0):
    indent = "  " * depth
    for c in sorted(categories, key=lambda x: -x["count"]):
        arrow = " ↳" if c["children"] else ""
        print(f"{indent}{c['label']} ({c['count']}){arrow}")
        if c["children"]:
            print_tree(c["children"], depth + 1)


def collect_leaves(categories, parent_path=""):
    leaves = []
    for c in categories:
        path = f"{parent_path}/{c['label']}" if parent_path else c["label"]
        if c["children"]:
            leaves.extend(collect_leaves(c["children"], path))
        else:
            leaves.append({"path": path, "label": c["label"], "count": c["count"],
                           "scope": c.get("scope", ""), "member_indices": c.get("member_indices", [])})
    return leaves


def apply_labels(domain, repos, categories, depth=0):
    """Write category (depth 0) and subcategory (depth 1+) labels."""
    with engine.connect() as conn:
        for c in categories:
            ids = [repos[i]["id"] for i in c.get("member_indices", [])]
            if not ids:
                continue
            if depth == 0:
                conn.execute(sql_text("""
                    UPDATE ai_repos SET category = :label WHERE id = ANY(:ids)
                """), {"label": c["label"], "ids": ids})
            if depth >= 1 or not c["children"]:
                conn.execute(sql_text("""
                    UPDATE ai_repos SET subcategory = :label WHERE id = ANY(:ids)
                """), {"label": c["label"], "ids": ids})
            if c["children"]:
                sub_repos = [repos[i] for i in c["member_indices"]]
                apply_labels(domain, sub_repos, c["children"], depth + 1)
        conn.commit()


async def discover_domain(domain, apply=False):
    print(f"\n{'=' * 60}")
    print(f"Discovering categories for: {domain}")
    print(f"{'=' * 60}")

    repos = fetch_repos(domain)
    if len(repos) < 30:
        print(f"  Only {len(repos)} repos — skipping")
        return

    print(f"  {len(repos):,} repos")

    embeddings = np.array([parse_pgvector(r["embedding_text"]) for r in repos])

    categories = await discover_level(domain, repos, embeddings)

    print(f"\n{'=' * 60}")
    print(f"CATEGORY TREE: {domain}")
    print(f"{'=' * 60}")
    print_tree(categories)

    leaves = collect_leaves(categories)
    print(f"\n{len(leaves)} leaf categories:")
    for l in sorted(leaves, key=lambda x: -x["count"]):
        print(f"  {l['path']} ({l['count']})")

    if apply:
        print("\nApplying labels to database...")
        apply_labels(domain, repos, categories)
        total = sum(c["count"] for c in categories)
        print(f"  Applied labels to {total:,} repos")


async def main():
    parser = argparse.ArgumentParser(description="Discover categories via UMAP + HDBSCAN + LLM")
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
