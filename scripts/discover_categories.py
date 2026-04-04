"""Discover two-level categories via UMAP + HDBSCAN + LLM labelling.

Based on best practices from taxonomy construction literature:
1. UMAP reduces 1536d → 30d (avoids curse of dimensionality)
2. HDBSCAN finds natural clusters (allows noise/outliers)
3. Haiku labels clusters from representative + boundary samples
4. Recursive: large clusters get re-projected and re-clustered
5. Post-processing: LLM deduplicates and scopes sibling categories

Usage:
    # Discover and save (expensive — LLM + compute)
    python scripts/discover_categories.py --domain voice-ai --save
    python scripts/discover_categories.py --all-domains --save

    # Apply from saved file (instant — just DB writes)
    python scripts/discover_categories.py --apply-from data/categories.json

    # Discover + apply in one shot
    python scripts/discover_categories.py --domain voice-ai --save --apply
"""
import argparse
import asyncio
import json
import logging
import os
import sys

import numpy as np
from sklearn.cluster import HDBSCAN
from sqlalchemy import text as sql_text
import umap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db import engine, readonly_engine
from app.ingest.llm import call_llm_text

logger = logging.getLogger(__name__)

ALL_DOMAINS = [
    "mcp", "agents", "rag", "ai-coding", "voice-ai",
    "diffusion", "vector-db", "embeddings", "prompt-engineering",
    "ml-frameworks", "llm-tools", "nlp", "transformers",
    "generative-ai", "computer-vision", "data-engineering", "mlops",
]

MIN_CLUSTER_SIZE = 15
MIN_SAMPLES = 5
SHARD_THRESHOLD = 400
MAX_DEPTH = 2
UMAP_DIMS = 30
SAVE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "categories.json")


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
    reducer = umap.UMAP(
        n_components=n_components, n_neighbors=20,
        min_dist=0.0, metric="cosine", random_state=42,
    )
    return reducer.fit_transform(embeddings)


def cluster(reduced_embeddings):
    clusterer = HDBSCAN(
        min_cluster_size=MIN_CLUSTER_SIZE, min_samples=MIN_SAMPLES, metric="euclidean",
    )
    return clusterer.fit_predict(reduced_embeddings)


async def label_cluster(domain, centroid_samples, boundary_samples, parent_label=None, sibling_labels=None):
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

    result = await call_llm_text(prompt, max_tokens=150)
    if not result:
        return "unknown", "Could not label"
    lines = result.strip().split("\n")
    label = lines[0].strip().lower().strip("\"'")
    scope = lines[1].strip() if len(lines) > 1 else ""
    return label, scope


async def deduplicate_siblings(domain, categories):
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

    result = await call_llm_text(prompt, max_tokens=300)
    if not result or "OK" in result.upper().split("\n")[0]:
        return categories

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
    if len(indices) == 0:
        return [], []
    subset = embeddings_reduced[indices]
    centroid = subset.mean(axis=0)
    distances = np.linalg.norm(subset - centroid, axis=1)
    sorted_by_dist = np.argsort(distances)
    centroid_idx = sorted_by_dist[:n_centroid]
    centroid_samples = [(repos[indices[i]]["full_name"], repos[indices[i]]["description"]) for i in centroid_idx]
    boundary_idx = sorted_by_dist[-n_boundary:]
    boundary_samples = [(repos[indices[i]]["full_name"], repos[indices[i]]["description"]) for i in boundary_idx]
    return centroid_samples, boundary_samples


async def discover_level(domain, repos, embeddings, depth=0, parent_label=None):
    indent = "  " * depth

    print(f"{indent}UMAP {len(repos)} repos → {UMAP_DIMS}d...")
    if len(repos) < UMAP_DIMS + 2:
        return [{"label": parent_label or "general", "count": len(repos),
                 "scope": "", "member_indices": list(range(len(repos))), "children": []}]

    reduced = reduce_dims(embeddings)
    labels = cluster(reduced)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    noise_count = (labels == -1).sum()
    print(f"{indent}  {n_clusters} clusters, {noise_count} noise")

    if n_clusters == 0:
        return [{"label": parent_label or "general", "count": len(repos),
                 "scope": "", "member_indices": list(range(len(repos))), "children": []}]

    clusters_dict = {}
    for idx, label in enumerate(labels):
        clusters_dict.setdefault(int(label), []).append(idx)

    print(f"{indent}  Labelling clusters...")
    categories = []
    assigned_labels = []

    for cluster_id in sorted(clusters_dict.keys()):
        if cluster_id == -1:
            continue
        indices = clusters_dict[cluster_id]
        centroid_samples, boundary_samples = get_samples(repos, indices, reduced)
        label, scope = await label_cluster(domain, centroid_samples, boundary_samples,
                                           parent_label=parent_label, sibling_labels=assigned_labels)
        assigned_labels.append(label)
        categories.append({
            "label": label, "scope": scope, "count": len(indices),
            "member_indices": indices, "children": [],
        })

    # Assign noise to nearest cluster
    if -1 in clusters_dict and clusters_dict[-1]:
        noise_indices = clusters_dict[-1]
        noise_reduced = reduced[noise_indices]
        centroids = np.array([reduced[c["member_indices"]].mean(axis=0) for c in categories])
        for ni in noise_indices:
            dists = np.linalg.norm(centroids - reduced[ni], axis=1)
            nearest = np.argmin(dists)
            categories[nearest]["member_indices"].append(ni)
            categories[nearest]["count"] += 1
        print(f"{indent}  Assigned {len(noise_indices)} noise repos to nearest categories")

    categories = await deduplicate_siblings(domain, categories)

    for c in sorted(categories, key=lambda x: -x["count"]):
        top_by_stars = sorted(c["member_indices"], key=lambda i: repos[i]["stars"] or 0, reverse=True)[:5]
        top_names = ", ".join(repos[i]["full_name"].split("/")[-1] for i in top_by_stars)
        print(f"{indent}  \"{c['label']}\" ({c['count']}) — {top_names}")

    if depth < MAX_DEPTH:
        for c in categories:
            if c["count"] > SHARD_THRESHOLD:
                print(f"{indent}  → Sharding \"{c['label']}\" ({c['count']} > {SHARD_THRESHOLD})...")
                sub_repos = [repos[i] for i in c["member_indices"]]
                sub_embeddings = embeddings[c["member_indices"]]
                c["children"] = await discover_level(
                    domain, sub_repos, sub_embeddings, depth=depth + 1, parent_label=c["label"],
                )
    return categories


# ---------------------------------------------------------------------------
# Serialisation: save/load the expensive discovery results
# ---------------------------------------------------------------------------

def build_assignments(repos, categories, depth=0):
    """Convert the category tree into a flat list of {repo_id, category, subcategory, scope}."""
    assignments = []
    for c in categories:
        if c["children"]:
            # This is a parent — its label becomes `category` for all descendants
            sub_repos = [repos[i] for i in c["member_indices"]]
            child_assignments = build_assignments(sub_repos, c["children"], depth + 1)
            for a in child_assignments:
                if depth == 0:
                    a["category"] = c["label"]
                assignments.append(a)
        else:
            # Leaf node
            for i in c["member_indices"]:
                entry = {"repo_id": repos[i]["id"], "subcategory": c["label"], "scope": c["scope"]}
                if depth == 0:
                    entry["category"] = c["label"]
                assignments.append(entry)
    return assignments


def save_results(path, all_results):
    """Save discovery results to JSON."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"Saved results to {path}")


def load_results(path):
    with open(path) as f:
        return json.load(f)


def apply_from_file(path):
    """Apply saved category assignments to the database."""
    data = load_results(path)
    total = 0
    with engine.connect() as conn:
        for domain, assignments in data.items():
            # Collect unique subcategories with scopes for centroids table
            scopes = {}
            for a in assignments:
                sub = a.get("subcategory")
                if sub and sub not in scopes:
                    scopes[sub] = a.get("scope", "")

            # Batch update by subcategory
            by_sub = {}
            for a in assignments:
                sub = a.get("subcategory", "uncategorized")
                cat = a.get("category")
                by_sub.setdefault(sub, {"ids": [], "category": cat}).get("ids").append(a["repo_id"])
                if cat:
                    by_sub[sub]["category"] = cat

            for sub, info in by_sub.items():
                ids = info["ids"]
                cat = info.get("category")
                if cat:
                    conn.execute(sql_text("""
                        UPDATE ai_repos SET category = :cat, subcategory = :sub WHERE id = ANY(:ids)
                    """), {"cat": cat, "sub": sub, "ids": ids})
                else:
                    conn.execute(sql_text("""
                        UPDATE ai_repos SET subcategory = :sub WHERE id = ANY(:ids)
                    """), {"sub": sub, "ids": ids})
                total += len(ids)

            # Store scopes in category_centroids
            conn.execute(sql_text("DELETE FROM category_centroids WHERE domain = :d"), {"d": domain})
            for label, scope in scopes.items():
                conn.execute(sql_text("""
                    INSERT INTO category_centroids (domain, level, label, description, centroid, repo_count)
                    VALUES (:domain, 'subcategory', :label, :desc, '[]', :count)
                    ON CONFLICT (domain, level, label) DO UPDATE SET description = EXCLUDED.description
                """), {"domain": domain, "label": label, "desc": scope,
                       "count": sum(1 for a in assignments if a.get("subcategory") == label)})

            conn.commit()
            domain_count = len(assignments)
            print(f"  {domain}: {domain_count:,} repos, {len(scopes)} categories")

    print(f"Applied labels to {total:,} repos total")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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
            leaves.append({"path": path, "label": c["label"], "count": c["count"]})
    return leaves


async def discover_domain(domain, save_data=None):
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
    print(f"\n{len(leaves)} leaf categories")

    # Build and save the flat assignment mapping
    if save_data is not None:
        assignments = build_assignments(repos, categories)
        save_data[domain] = assignments
        print(f"  {len(assignments):,} repo assignments queued for save")


async def main():
    parser = argparse.ArgumentParser(description="Discover categories via UMAP + HDBSCAN + LLM")
    parser.add_argument("--domain", choices=ALL_DOMAINS)
    parser.add_argument("--all-domains", action="store_true")
    parser.add_argument("--save", action="store_true", help="Save results to data/categories.json")
    parser.add_argument("--apply", action="store_true", help="Apply saved results after discovery")
    parser.add_argument("--apply-from", type=str, help="Apply from a previously saved JSON file (no discovery)")
    parser.add_argument("--save-path", type=str, default=SAVE_PATH, help="Path for save/load")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    # Apply-from mode: just read the file and write to DB
    if args.apply_from:
        print(f"Applying from {args.apply_from}...")
        apply_from_file(args.apply_from)
        return

    # Discovery mode
    if args.all_domains:
        domains = ALL_DOMAINS
    elif args.domain:
        domains = [args.domain]
    else:
        parser.error("Specify --domain, --all-domains, or --apply-from")

    save_data = {} if args.save or args.apply else None

    for domain in domains:
        await discover_domain(domain, save_data=save_data)

    if save_data and args.save:
        save_results(args.save_path, save_data)

    if save_data and args.apply:
        print("\nApplying labels to database...")
        # Save first so we never lose work
        if args.save:
            save_results(args.save_path, save_data)
        apply_from_file(args.save_path) if args.save else apply_from_data(save_data)


def apply_from_data(data):
    """Apply directly from in-memory data (when --apply without --save)."""
    import tempfile
    path = tempfile.mktemp(suffix=".json")
    save_results(path, data)
    apply_from_file(path)
    os.unlink(path)


if __name__ == "__main__":
    asyncio.run(main())
