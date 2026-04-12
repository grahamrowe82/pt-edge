"""Auto-categorization via UMAP + HDBSCAN clustering.

Discovers natural categories from entity embeddings. Following PT-Edge's
discover_categories.py pattern: UMAP dimensionality reduction → HDBSCAN
clustering → recursive sharding of large clusters → centroid computation
→ LLM labelling of discovered clusters.

Usage:
    from app.ingest.categorize import categorize_entities
    await categorize_entities()  # runs on all entity types
"""

import logging
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import text

from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.models import SyncLog

logger = logging.getLogger(__name__)

# Clustering parameters (tuned for cybersecurity entities, same as bio-edge/PT-Edge)
UMAP_COMPONENTS = 30
UMAP_NEIGHBORS = 20
UMAP_MIN_DIST = 0.0
HDBSCAN_MIN_CLUSTER_SIZE = 15
HDBSCAN_MIN_SAMPLES = 5
MAX_CLUSTER_SIZE = 400  # clusters larger than this get recursively split
MAX_RECURSION_DEPTH = 2
MIN_ENTITIES_FOR_CLUSTERING = 50

# Pre-built SQL per entity type — avoids f-string SQL (injection risk flag)
_ENTITY_SQL = {
    "cve": text("SELECT id, embedding::text FROM cves WHERE embedding IS NOT NULL ORDER BY id"),
    "software": text("SELECT id, embedding::text FROM software WHERE embedding IS NOT NULL ORDER BY id"),
    "vendor": text("SELECT id, embedding::text FROM vendors WHERE embedding IS NOT NULL ORDER BY id"),
    "weakness": text("SELECT id, embedding::text FROM weaknesses WHERE embedding IS NOT NULL ORDER BY id"),
    "technique": text("SELECT id, embedding::text FROM techniques WHERE embedding IS NOT NULL ORDER BY id"),
    "pattern": text("SELECT id, embedding::text FROM attack_patterns WHERE embedding IS NOT NULL ORDER BY id"),
}
_NAME_SQL = {
    "cve": text("SELECT id, cve_id FROM cves WHERE id = ANY(:ids)"),
    "software": text("SELECT id, name FROM software WHERE id = ANY(:ids)"),
    "vendor": text("SELECT id, name FROM vendors WHERE id = ANY(:ids)"),
    "weakness": text("SELECT id, cwe_id || ': ' || name FROM weaknesses WHERE id = ANY(:ids)"),
    "technique": text("SELECT id, technique_id || ': ' || name FROM techniques WHERE id = ANY(:ids)"),
    "pattern": text("SELECT id, capec_id || ': ' || name FROM attack_patterns WHERE id = ANY(:ids)"),
}
_ASSIGN_SQL = {
    "cve": text("UPDATE cves SET category = :cat WHERE id = ANY(:ids)"),
    "software": text("UPDATE software SET category = :cat WHERE id = ANY(:ids)"),
    "vendor": text("UPDATE vendors SET category = :cat WHERE id = ANY(:ids)"),
    "weakness": text("UPDATE weaknesses SET category = :cat WHERE id = ANY(:ids)"),
    "technique": text("UPDATE techniques SET category = :cat WHERE id = ANY(:ids)"),
    "pattern": text("UPDATE attack_patterns SET category = :cat WHERE id = ANY(:ids)"),
}


def _load_embeddings(entity_type: str) -> tuple[list[int], np.ndarray]:
    """Load entity IDs and embeddings as numpy array. Returns (ids, matrix)."""
    with engine.connect() as conn:
        rows = conn.execute(_ENTITY_SQL[entity_type]).fetchall()

    if not rows:
        return [], np.empty((0, 1536))

    ids = [r[0] for r in rows]
    vectors = np.array(
        [np.fromstring(r[1].strip("[]"), sep=",", dtype=np.float32) for r in rows]
    )

    # L2 normalize
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vectors = vectors / norms

    return ids, vectors


def _cluster_embeddings(
    vectors: np.ndarray,
    depth: int = 0,
) -> list[np.ndarray]:
    """UMAP + HDBSCAN clustering with recursive sharding of large clusters.

    Returns list of index arrays, one per discovered cluster.
    """
    from sklearn.cluster import HDBSCAN
    import umap

    if len(vectors) < MIN_ENTITIES_FOR_CLUSTERING:
        return [np.arange(len(vectors))]

    # Dimensionality reduction
    reducer = umap.UMAP(
        n_components=min(UMAP_COMPONENTS, len(vectors) - 2),
        n_neighbors=min(UMAP_NEIGHBORS, len(vectors) - 1),
        min_dist=UMAP_MIN_DIST,
        metric="cosine",
        random_state=42,
    )
    reduced = reducer.fit_transform(vectors)

    # Cluster
    clusterer = HDBSCAN(
        min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE,
        min_samples=HDBSCAN_MIN_SAMPLES,
        metric="euclidean",
    )
    labels = clusterer.fit_predict(reduced)

    unique_labels = set(labels)
    unique_labels.discard(-1)  # noise

    if not unique_labels:
        return [np.arange(len(vectors))]

    clusters = []
    for label in sorted(unique_labels):
        member_indices = np.where(labels == label)[0]

        # Recursive sharding for large clusters
        if len(member_indices) > MAX_CLUSTER_SIZE and depth < MAX_RECURSION_DEPTH:
            sub_vectors = vectors[member_indices]
            sub_clusters = _cluster_embeddings(sub_vectors, depth=depth + 1)
            for sub_idx in sub_clusters:
                clusters.append(member_indices[sub_idx])
        else:
            clusters.append(member_indices)

    # Assign noise points to nearest cluster centroid
    noise_indices = np.where(labels == -1)[0]
    if len(noise_indices) > 0 and clusters:
        centroids = np.array([vectors[c].mean(axis=0) for c in clusters])
        centroid_norms = np.linalg.norm(centroids, axis=1, keepdims=True)
        centroid_norms[centroid_norms == 0] = 1.0
        centroids = centroids / centroid_norms

        for idx in noise_indices:
            similarities = centroids @ vectors[idx]
            best_cluster = np.argmax(similarities)
            clusters[best_cluster] = np.append(clusters[best_cluster], idx)

    return clusters


def _compute_centroids(vectors: np.ndarray, clusters: list[np.ndarray]) -> list[np.ndarray]:
    """Compute L2-normalised centroid for each cluster."""
    centroids = []
    for member_indices in clusters:
        centroid = vectors[member_indices].mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        centroids.append(centroid)
    return centroids


def _get_representative_names(
    entity_type: str, ids: list[int], member_indices: np.ndarray,
    vectors: np.ndarray, centroid: np.ndarray, n: int = 5,
) -> tuple[list[str], list[str]]:
    """Get names of entities closest to and furthest from the centroid.

    Returns (closest_names, boundary_names) for LLM labelling.
    """
    member_ids = [ids[i] for i in member_indices]
    member_vectors = vectors[member_indices]
    similarities = member_vectors @ centroid

    # Closest to centroid (most representative)
    closest_order = np.argsort(-similarities)[:n]
    closest_ids = [member_ids[i] for i in closest_order]

    # Furthest from centroid (boundary members)
    boundary_order = np.argsort(similarities)[:n]
    boundary_ids = [member_ids[i] for i in boundary_order]

    all_ids = list(set(closest_ids + boundary_ids))
    with engine.connect() as conn:
        rows = conn.execute(
            _NAME_SQL[entity_type],
            {"ids": all_ids},
        ).fetchall()
    name_map = {r[0]: r[1] for r in rows}

    closest_names = [name_map.get(i, "?") for i in closest_ids]
    boundary_names = [name_map.get(i, "?") for i in boundary_ids]
    return closest_names, boundary_names


async def _label_cluster(
    entity_type: str, closest_names: list[str], boundary_names: list[str],
    member_count: int,
) -> str | None:
    """Use LLM to generate a short label for a cluster.

    Returns a slug-style label like "memory-corruption" or "web-injection".
    """
    from domains.cyber.app.embeddings import is_enabled
    if not is_enabled():
        return None

    entity_labels = {
        "cve": "CVE", "software": "software product",
        "vendor": "vendor", "weakness": "weakness type",
        "technique": "ATT&CK technique", "pattern": "attack pattern",
    }
    entity_label = entity_labels.get(entity_type, entity_type)

    prompt = (
        f"Below are {entity_label}s from a cluster of {member_count} {entity_label}s "
        f"in a cybersecurity knowledge graph.\n\n"
        f"Most representative members: {', '.join(closest_names)}\n"
        f"Boundary members: {', '.join(boundary_names)}\n\n"
        f"Generate a short category label (2-4 words) that describes what these {entity_label}s "
        f"have in common. Return ONLY the label in lowercase-hyphenated format "
        f"(e.g. 'memory-corruption', 'web-injection', 'supply-chain-attacks'). No explanation."
    )

    try:
        from openai import AsyncOpenAI
        from domains.cyber.app.settings import settings
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
            temperature=0,
        )
        label = resp.choices[0].message.content.strip().lower().strip("'\"")
        # Sanitize: only allow lowercase letters, numbers, hyphens
        import re
        label = re.sub(r"[^a-z0-9-]", "-", label).strip("-")
        return label if label else None
    except Exception as e:
        logger.warning(f"LLM labelling failed: {e}")
        return None


def _store_categories(
    entity_type: str, clusters: list[np.ndarray], centroids: list[np.ndarray],
    labels: list[str | None], ids: list[int],
):
    """Store category centroids and assign entities to categories."""
    # Upsert entity_categories
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        for i, (cluster_indices, centroid, label) in enumerate(zip(clusters, centroids, labels)):
            if not label:
                label = f"cluster-{i}"
            centroid_str = "[" + ",".join(f"{v:.6f}" for v in centroid) + "]"

            cur.execute("""
                INSERT INTO entity_categories
                    (entity_type, level, label, centroid, entity_count)
                VALUES (%s, 'category', %s, %s, %s)
                ON CONFLICT (entity_type, level, label) DO UPDATE SET
                    centroid = EXCLUDED.centroid,
                    entity_count = EXCLUDED.entity_count
            """, (entity_type, label, centroid_str, len(cluster_indices)))

        raw.commit()
    finally:
        raw.close()

    # Assign entities to categories
    assign_sql = _ASSIGN_SQL[entity_type]
    for cluster_indices, label in zip(clusters, labels):
        if not label:
            label = f"cluster-{clusters.index(cluster_indices)}"
        member_ids = [ids[int(i)] for i in cluster_indices]

        with engine.connect() as conn:
            conn.execute(assign_sql, {"cat": label, "ids": member_ids})
            conn.commit()


async def categorize_entity_type(entity_type: str) -> dict:
    """Run full clustering pipeline for one entity type."""
    logger.info(f"Categorizing {entity_type}s...")

    ids, vectors = _load_embeddings(entity_type)
    if len(ids) < MIN_ENTITIES_FOR_CLUSTERING:
        logger.info(f"  Too few {entity_type}s with embeddings ({len(ids)}) — skipping")
        return {"entity_type": entity_type, "clusters": 0, "entities": len(ids)}

    logger.info(f"  Loaded {len(ids)} {entity_type} embeddings")

    clusters = _cluster_embeddings(vectors)
    centroids = _compute_centroids(vectors, clusters)
    logger.info(f"  Found {len(clusters)} clusters")

    # Label clusters via LLM
    labels = []
    for cluster_indices, centroid in zip(clusters, centroids):
        closest, boundary = _get_representative_names(
            entity_type, ids, cluster_indices, vectors, centroid,
        )
        label = await _label_cluster(entity_type, closest, boundary, len(cluster_indices))
        labels.append(label)
        if label:
            logger.info(f"    {label}: {len(cluster_indices)} entities (reps: {', '.join(closest[:3])})")

    _store_categories(entity_type, clusters, centroids, labels, ids)

    return {
        "entity_type": entity_type,
        "clusters": len(clusters),
        "entities": len(ids),
        "labels": [l for l in labels if l],
    }


async def categorize_entities() -> dict:
    """Run clustering on all entity types. Returns summary."""
    started = datetime.now(timezone.utc)
    results = {}

    for entity_type in ["cve", "software", "vendor", "weakness", "technique", "pattern"]:
        try:
            results[entity_type] = await categorize_entity_type(entity_type)
        except Exception as e:
            logger.exception(f"Categorization failed for {entity_type}: {e}")
            results[entity_type] = {"error": str(e)}

    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="categorize",
            status="success",
            records_written=sum(
                r.get("clusters", 0) for r in results.values() if isinstance(r, dict)
            ),
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    return results
