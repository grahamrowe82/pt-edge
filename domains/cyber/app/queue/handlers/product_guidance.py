"""Compute product categories, peer comparisons, and risk guidance.

Runs after embed_products. Uses UMAP + HDBSCAN on product embeddings to
discover categories, then computes peer products within each category.

Risk summaries use deterministic tier-based templates in this version.
Follow-up: Gemini-generated category-specific guidance.
"""

import logging
import json

import numpy as np
from sqlalchemy import text

from domains.cyber.app.db import engine

logger = logging.getLogger(__name__)

# Deterministic risk guidance by tier (Gemini category-specific guidance in follow-up)
TIER_GUIDANCE = {
    "critical-risk": {
        "summary": "{name} has critical exploitation rates. Immediate action recommended.",
        "actions": [
            "Check for patches and apply immediately",
            "Review whether this software can be replaced",
            "Consult your IT provider about mitigation",
        ],
    },
    "high-risk": {
        "summary": "{name} is actively targeted. Ensure patches are applied.",
        "actions": [
            "Apply all available updates immediately",
            "Review your exposure — is this internet-facing?",
            "Monitor vendor advisories for this product",
        ],
    },
    "moderate-risk": {
        "summary": "{name} has some exploitation signals but is manageable with regular updates.",
        "actions": [
            "Keep this software updated",
            "Review your configuration for unnecessary exposure",
            "Check for known-vulnerable components or plugins",
        ],
    },
    "low-risk": {
        "summary": "{name} has low exploitation rates. Standard maintenance is sufficient.",
        "actions": [
            "Keep automatic updates enabled",
            "No urgent action needed",
            "Review periodically as part of normal maintenance",
        ],
    },
}


def _categorize_products():
    """Cluster products by embedding similarity using UMAP + HDBSCAN."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT pm.vendor_key, pm.product_key, pm.embedding::text
            FROM product_metadata pm
            WHERE pm.embedding IS NOT NULL
        """)).fetchall()

    if len(rows) < 50:
        logger.info(f"Only {len(rows)} products with embeddings — skipping categorization (need 50+)")
        return 0

    # Parse embeddings
    keys = []
    vectors = []
    for r in rows:
        keys.append((r[0], r[1]))
        vec_str = r[2].strip("[]")
        vectors.append([float(x) for x in vec_str.split(",")])

    X = np.array(vectors, dtype=np.float32)
    # L2 normalize for cosine similarity
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1
    X = X / norms

    try:
        import umap
        import hdbscan
    except ImportError:
        logger.warning("umap/hdbscan not installed — skipping categorization")
        return 0

    logger.info(f"Clustering {len(X)} product embeddings...")
    reducer = umap.UMAP(n_components=30, n_neighbors=20, min_dist=0.0, metric="cosine", random_state=42)
    reduced = reducer.fit_transform(X)

    clusterer = hdbscan.HDBSCAN(min_cluster_size=15, min_samples=5)
    labels = clusterer.fit_predict(reduced)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = (labels == -1).sum()
    logger.info(f"Found {n_clusters} clusters, {n_noise} noise points")

    # Assign noise points to nearest cluster centroid
    if n_noise > 0 and n_clusters > 0:
        centroids = {}
        for c in set(labels):
            if c == -1:
                continue
            mask = labels == c
            centroids[c] = reduced[mask].mean(axis=0)

        for i in range(len(labels)):
            if labels[i] == -1:
                dists = {c: np.linalg.norm(reduced[i] - cent) for c, cent in centroids.items()}
                labels[i] = min(dists, key=dists.get)

    # Label clusters by most common vendor_key + product_key in cluster
    cluster_labels = {}
    for c in set(labels):
        mask = labels == c
        members = [keys[i] for i in range(len(keys)) if mask[i]]
        # Use the product with highest cve_count as representative
        rep = members[0]
        cluster_labels[c] = f"cluster_{c}"  # Placeholder — Gemini labeling in follow-up

    # Update product_metadata
    updated = 0
    with engine.connect() as conn:
        for i, (vk, pk) in enumerate(keys):
            cluster_id = int(labels[i])
            label = cluster_labels.get(cluster_id, f"cluster_{cluster_id}")
            conn.execute(text("""
                UPDATE product_metadata
                SET category = :cat, category_label = :label, updated_at = now()
                WHERE vendor_key = :vk AND product_key = :pk
            """), {"cat": f"cluster_{cluster_id}", "label": label, "vk": vk, "pk": pk})
            updated += 1
        conn.commit()

    logger.info(f"Assigned {updated} products to {n_clusters} categories")
    return updated


def _compute_peer_products():
    """For each product, find top 5 peers in the same category."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT pm.vendor_key, pm.product_key, pm.category,
                   p.display_name, p.composite_score, p.quality_tier
            FROM product_metadata pm
            JOIN mv_product_scores p
                ON p.vendor_key = pm.vendor_key AND p.product_key = pm.product_key
            WHERE pm.category IS NOT NULL
            ORDER BY pm.category, p.composite_score DESC
        """)).mappings().fetchall()

    # Group by category
    categories = {}
    for r in rows:
        categories.setdefault(r["category"], []).append(dict(r))

    # For each product, find peers (other products in same category)
    updated = 0
    with engine.connect() as conn:
        for cat, members in categories.items():
            for member in members:
                peers = [
                    {
                        "id": f"{m['vendor_key']}/{m['product_key']}",
                        "name": m["display_name"],
                        "score": m["composite_score"],
                        "tier": m["quality_tier"],
                    }
                    for m in members
                    if m["vendor_key"] != member["vendor_key"] or m["product_key"] != member["product_key"]
                ][:5]

                conn.execute(text("""
                    UPDATE product_metadata
                    SET peer_products = :peers, updated_at = now()
                    WHERE vendor_key = :vk AND product_key = :pk
                """), {
                    "peers": json.dumps(peers),
                    "vk": member["vendor_key"],
                    "pk": member["product_key"],
                })
                updated += 1
        conn.commit()

    logger.info(f"Computed peers for {updated} products")
    return updated


def _compute_risk_guidance():
    """Generate deterministic risk summaries based on tier."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT pm.vendor_key, pm.product_key, p.display_name, p.quality_tier
            FROM product_metadata pm
            JOIN mv_product_scores p
                ON p.vendor_key = pm.vendor_key AND p.product_key = pm.product_key
            WHERE pm.risk_summary IS NULL
        """)).mappings().fetchall()

    if not rows:
        return 0

    updated = 0
    with engine.connect() as conn:
        for r in rows:
            tier = r["quality_tier"] or "low-risk"
            guidance = TIER_GUIDANCE.get(tier, TIER_GUIDANCE["low-risk"])
            summary = guidance["summary"].format(name=r["display_name"])
            actions = json.dumps(guidance["actions"])

            conn.execute(text("""
                UPDATE product_metadata
                SET risk_summary = :summary, recommended_actions = :actions, updated_at = now()
                WHERE vendor_key = :vk AND product_key = :pk
            """), {
                "summary": summary,
                "actions": actions,
                "vk": r["vendor_key"],
                "pk": r["product_key"],
            })
            updated += 1
        conn.commit()

    logger.info(f"Generated risk guidance for {updated} products")
    return updated


def handle_product_guidance(task_row: dict) -> dict:
    """Task handler: categorize products, compute peers, generate guidance."""
    categorized = _categorize_products()
    peers = _compute_peer_products()
    guided = _compute_risk_guidance()
    return {"categorized": categorized, "peers_computed": peers, "guidance_generated": guided}
