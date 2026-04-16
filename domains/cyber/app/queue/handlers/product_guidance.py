"""Compute product categories, peer comparisons, and risk guidance.

Runs after embed_products. Uses UMAP + HDBSCAN on product embeddings to
discover categories, Gemini to label them and generate category-specific
risk guidance for non-technical users.

Pipeline: cluster → label (Gemini) → peers → guidance (Gemini) → store.
Falls back to deterministic templates if Gemini is not configured.
"""

import asyncio
import logging
import json

from sqlalchemy import text

from domains.cyber.app.db import engine
from domains.cyber.app.settings import settings

logger = logging.getLogger(__name__)

# Deterministic fallback when Gemini is unavailable
TIER_FALLBACK = {
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


def _categorize_products() -> tuple[int, dict]:
    """Cluster products by embedding similarity. Returns (count, cluster_members)."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT pm.vendor_key, pm.product_key, pm.embedding::text,
                   p.display_name, p.cve_count
            FROM product_metadata pm
            JOIN mv_product_scores p
                ON p.vendor_key = pm.vendor_key AND p.product_key = pm.product_key
            WHERE pm.embedding IS NOT NULL
        """)).fetchall()

    if len(rows) < 50:
        logger.info(f"Only {len(rows)} products with embeddings — skipping categorization")
        return 0, {}

    keys = []
    names = []
    vectors = []
    for r in rows:
        keys.append((r[0], r[1]))
        names.append(r[3])
        vec_str = r[2].strip("[]")
        vectors.append([float(x) for x in vec_str.split(",")])

    import numpy as np

    X = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1
    X = X / norms

    try:
        import umap
        import hdbscan
    except ImportError:
        logger.warning("umap/hdbscan not installed — skipping categorization")
        return 0, {}

    logger.info(f"Clustering {len(X)} product embeddings...")
    reducer = umap.UMAP(n_components=30, n_neighbors=20, min_dist=0.0, metric="cosine", random_state=42)
    reduced = reducer.fit_transform(X)

    clusterer = hdbscan.HDBSCAN(min_cluster_size=15, min_samples=5)
    labels = clusterer.fit_predict(reduced)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = (labels == -1).sum()
    logger.info(f"Found {n_clusters} clusters, {n_noise} noise points")

    # Assign noise to nearest centroid
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

    # Build cluster membership for downstream steps
    cluster_members = {}
    for i, (vk, pk) in enumerate(keys):
        c = int(labels[i])
        cluster_members.setdefault(c, []).append({
            "vendor_key": vk, "product_key": pk, "display_name": names[i],
        })

    # Update product_metadata with cluster IDs (labels come from Gemini next)
    updated = 0
    with engine.connect() as conn:
        for i, (vk, pk) in enumerate(keys):
            cluster_id = int(labels[i])
            conn.execute(text("""
                UPDATE product_metadata
                SET category = :cat, updated_at = now()
                WHERE vendor_key = :vk AND product_key = :pk
            """), {"cat": f"cluster_{cluster_id}", "vk": vk, "pk": pk})
            updated += 1
        conn.commit()

    logger.info(f"Assigned {updated} products to {n_clusters} categories")
    return updated, cluster_members


async def _label_clusters(cluster_members: dict) -> dict:
    """Use Gemini to generate human-readable labels for each cluster."""
    from domains.cyber.app.ingest.llm import call_llm

    cluster_labels = {}

    for cluster_id, members in cluster_members.items():
        # Pick up to 8 representative names
        sample_names = [m["display_name"] for m in members[:8]]

        prompt = (
            "You are labeling a cluster of software products that were grouped by "
            "vulnerability similarity. Given these example products, provide a short "
            "category label (2-4 words, like 'Web Content Management' or 'Network Firmware' "
            "or 'Desktop Browsers' or 'Database Servers').\n\n"
            f"Products in this cluster: {', '.join(sample_names)}\n\n"
            "Return JSON: {{\"label\": \"the category label\"}}"
        )

        result = await call_llm(prompt, max_tokens=100)
        if result and isinstance(result, dict) and "label" in result:
            cluster_labels[cluster_id] = result["label"]
            logger.info(f"  Cluster {cluster_id} ({len(members)} products): {result['label']}")
        else:
            # Fallback: use the first product name
            cluster_labels[cluster_id] = f"{sample_names[0]} and similar"
            logger.info(f"  Cluster {cluster_id}: fallback label '{cluster_labels[cluster_id]}'")

    # Write labels to product_metadata
    with engine.connect() as conn:
        for cluster_id, label in cluster_labels.items():
            conn.execute(text("""
                UPDATE product_metadata
                SET category_label = :label, updated_at = now()
                WHERE category = :cat
            """), {"label": label, "cat": f"cluster_{cluster_id}"})
        conn.commit()

    logger.info(f"Labeled {len(cluster_labels)} clusters via Gemini")
    return cluster_labels


async def _generate_category_guidance(cluster_labels: dict, cluster_members: dict) -> int:
    """Use Gemini to generate category × tier risk guidance for non-technical users."""
    from domains.cyber.app.ingest.llm import call_llm

    tiers = ["critical-risk", "high-risk", "moderate-risk", "low-risk"]
    generated = 0

    # For each category, generate guidance for each tier
    guidance_cache = {}  # (category, tier) → {summary, actions}

    for cluster_id, label in cluster_labels.items():
        members = cluster_members.get(cluster_id, [])
        sample_names = [m["display_name"] for m in members[:5]]

        for tier in tiers:
            tier_desc = {
                "critical-risk": "critical exploitation rates — most vulnerabilities are actively exploited",
                "high-risk": "actively targeted — significant proportion of vulnerabilities being exploited",
                "moderate-risk": "some exploitation signals — a small proportion of vulnerabilities are targeted",
                "low-risk": "low exploitation rates — very few vulnerabilities are being actively exploited",
            }[tier]

            prompt = (
                f"Write a security advisory for a non-technical business owner. "
                f"The software category is '{label}' (examples: {', '.join(sample_names)}). "
                f"The risk level is {tier}: {tier_desc}.\n\n"
                f"Return JSON with:\n"
                f"- \"summary\": one sentence explaining the risk in plain English. "
                f"Use {{name}} as a placeholder for the product name. No jargon.\n"
                f"- \"actions\": array of 3 specific recommended actions. "
                f"Be specific to this category of software (e.g., 'review your plugins' for CMS, "
                f"'check firmware update availability' for routers). No acronyms.\n\n"
                f"Example: {{\"summary\": \"{{name}} is widely targeted but patches come quickly. "
                f"Keep it updated and your risk is low.\", "
                f"\"actions\": [\"Turn on automatic updates\", \"Review installed plugins\", "
                f"\"Ask your hosting provider about managed security\"]}}"
            )

            result = await call_llm(prompt, max_tokens=300)
            if result and isinstance(result, dict) and "summary" in result:
                guidance_cache[(cluster_id, tier)] = result
                generated += 1
            else:
                # Fallback to deterministic
                guidance_cache[(cluster_id, tier)] = TIER_FALLBACK.get(tier, TIER_FALLBACK["low-risk"])

    logger.info(f"Generated {generated} Gemini guidance entries (of {len(guidance_cache)} total)")

    # Apply guidance to each product based on its category + tier
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT pm.vendor_key, pm.product_key, pm.category,
                   p.display_name, p.quality_tier
            FROM product_metadata pm
            JOIN mv_product_scores p
                ON p.vendor_key = pm.vendor_key AND p.product_key = pm.product_key
            WHERE pm.category IS NOT NULL
        """)).mappings().fetchall()

        updated = 0
        for r in rows:
            cat = r["category"]
            tier = r["quality_tier"] or "low-risk"
            # Extract cluster_id from category string "cluster_N"
            try:
                cid = int(cat.replace("cluster_", ""))
            except (ValueError, AttributeError):
                cid = -1

            guidance = guidance_cache.get((cid, tier), TIER_FALLBACK.get(tier, TIER_FALLBACK["low-risk"]))
            summary = guidance["summary"].format(name=r["display_name"])
            actions = json.dumps(guidance["actions"])

            conn.execute(text("""
                UPDATE product_metadata
                SET risk_summary = :summary, recommended_actions = :actions, updated_at = now()
                WHERE vendor_key = :vk AND product_key = :pk
            """), {"summary": summary, "actions": actions, "vk": r["vendor_key"], "pk": r["product_key"]})
            updated += 1
        conn.commit()

    logger.info(f"Applied guidance to {updated} products")
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

    categories = {}
    for r in rows:
        categories.setdefault(r["category"], []).append(dict(r))

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


async def _run_guidance_pipeline():
    """Full pipeline: cluster → label → peers → guidance."""
    categorized, cluster_members = _categorize_products()

    if not cluster_members:
        logger.info("No clusters — generating fallback guidance for all products")
        # Apply deterministic fallback for products without categories
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT pm.vendor_key, pm.product_key, p.display_name, p.quality_tier
                FROM product_metadata pm
                JOIN mv_product_scores p
                    ON p.vendor_key = pm.vendor_key AND p.product_key = pm.product_key
                WHERE pm.risk_summary IS NULL
            """)).mappings().fetchall()

            for r in rows:
                tier = r["quality_tier"] or "low-risk"
                guidance = TIER_FALLBACK.get(tier, TIER_FALLBACK["low-risk"])
                conn.execute(text("""
                    UPDATE product_metadata
                    SET risk_summary = :summary, recommended_actions = :actions, updated_at = now()
                    WHERE vendor_key = :vk AND product_key = :pk
                """), {
                    "summary": guidance["summary"].format(name=r["display_name"]),
                    "actions": json.dumps(guidance["actions"]),
                    "vk": r["vendor_key"], "pk": r["product_key"],
                })
            conn.commit()
        return {"categorized": 0, "labeled": 0, "peers": 0, "guided": len(rows)}

    # Label clusters with Gemini (or fallback)
    if settings.GEMINI_API_KEY:
        cluster_labels = await _label_clusters(cluster_members)
    else:
        logger.info("Gemini not configured — using fallback cluster labels")
        cluster_labels = {
            cid: f"{members[0]['display_name']} and similar"
            for cid, members in cluster_members.items()
        }
        with engine.connect() as conn:
            for cid, label in cluster_labels.items():
                conn.execute(text("""
                    UPDATE product_metadata SET category_label = :label, updated_at = now()
                    WHERE category = :cat
                """), {"label": label, "cat": f"cluster_{cid}"})
            conn.commit()

    # Compute peers
    peers = _compute_peer_products()

    # Generate category-specific guidance with Gemini (or fallback)
    if settings.GEMINI_API_KEY:
        guided = await _generate_category_guidance(cluster_labels, cluster_members)
    else:
        logger.info("Gemini not configured — using deterministic tier guidance")
        guided = 0
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT pm.vendor_key, pm.product_key, p.display_name, p.quality_tier
                FROM product_metadata pm
                JOIN mv_product_scores p
                    ON p.vendor_key = pm.vendor_key AND p.product_key = pm.product_key
                WHERE pm.risk_summary IS NULL
            """)).mappings().fetchall()
            for r in rows:
                tier = r["quality_tier"] or "low-risk"
                g = TIER_FALLBACK.get(tier, TIER_FALLBACK["low-risk"])
                conn.execute(text("""
                    UPDATE product_metadata
                    SET risk_summary = :summary, recommended_actions = :actions, updated_at = now()
                    WHERE vendor_key = :vk AND product_key = :pk
                """), {
                    "summary": g["summary"].format(name=r["display_name"]),
                    "actions": json.dumps(g["actions"]),
                    "vk": r["vendor_key"], "pk": r["product_key"],
                })
                guided += 1
            conn.commit()

    return {
        "categorized": categorized,
        "labeled": len(cluster_labels),
        "peers": peers,
        "guided": guided,
    }


def handle_product_guidance(task_row: dict) -> dict:
    """Task handler: categorize → label → peers → guidance."""
    return asyncio.run(_run_guidance_pipeline())
