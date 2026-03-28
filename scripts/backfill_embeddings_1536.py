"""Backfill 1536d embeddings for ai_repos.

Uses richer text (name + description + AI summary + topics + language)
for better within-domain clustering resolution.

Usage:
    python scripts/backfill_embeddings_1536.py [--limit 50000] [--domain voice-ai]
"""
import argparse
import asyncio
import logging
import os
import sys
import time

from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db import engine
from app.embeddings import embed_batch, is_enabled

logger = logging.getLogger(__name__)

CHUNK_SIZE = 500  # DB write batch size


def build_rich_text(repo):
    """Richer text for clustering embeddings — includes AI summary."""
    parts = [repo["name"] or ""]
    if repo["description"]:
        parts[0] += f": {repo['description']}"
    if repo["ai_summary"]:
        parts.append(repo["ai_summary"])
    if repo["topics"]:
        topics = repo["topics"] if isinstance(repo["topics"], list) else []
        if topics:
            parts.append(f"Topics: {', '.join(topics)}")
    if repo["language"]:
        parts.append(f"Language: {repo['language']}")
    return ". ".join(parts) + "."


def fetch_repos(limit, domain=None):
    """Fetch repos needing 1536d embeddings."""
    domain_filter = "AND domain = :domain" if domain else ""
    params = {"lim": limit}
    if domain:
        params["domain"] = domain

    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, name, description, ai_summary, topics, language
            FROM ai_repos
            WHERE description IS NOT NULL
              AND embedding_1536 IS NULL
              {domain_filter}
            ORDER BY stars DESC NULLS LAST
            LIMIT :lim
        """), params).fetchall()
    return [dict(r._mapping) for r in rows]


def write_embeddings(id_vec_pairs):
    """Batch write 1536d embeddings via temp table."""
    from psycopg2.extras import execute_values

    for i in range(0, len(id_vec_pairs), CHUNK_SIZE):
        chunk = id_vec_pairs[i:i + CHUNK_SIZE]
        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            cur.execute("""
                CREATE TEMP TABLE _emb1536_batch (
                    id INTEGER PRIMARY KEY,
                    embedding_1536 vector(1536)
                ) ON COMMIT DROP
            """)
            execute_values(
                cur,
                "INSERT INTO _emb1536_batch (id, embedding_1536) VALUES %s",
                chunk,
                template="(%s, %s)",
                page_size=500,
            )
            cur.execute("""
                UPDATE ai_repos s
                SET embedding_1536 = b.embedding_1536
                FROM _emb1536_batch b
                WHERE s.id = b.id
            """)
            raw_conn.commit()
        except Exception as e:
            try:
                raw_conn.rollback()
            except Exception:
                pass
            logger.error(f"Batch write failed at chunk {i}: {e}")
        finally:
            try:
                raw_conn.close()
            except Exception:
                pass


async def main():
    parser = argparse.ArgumentParser(description="Backfill 1536d embeddings")
    parser.add_argument("--limit", type=int, default=50000)
    parser.add_argument("--domain", type=str, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if not is_enabled():
        print("OPENAI_API_KEY not set — cannot generate embeddings")
        return

    print(f"Fetching repos needing 1536d embeddings (limit={args.limit}, domain={args.domain or 'all'})...")
    repos = fetch_repos(args.limit, args.domain)
    if not repos:
        print("No repos need 1536d embeddings.")
        return

    print(f"  {len(repos)} repos to embed")

    t0 = time.time()
    texts = [build_rich_text(r) for r in repos]
    ids = [r["id"] for r in repos]

    print(f"Embedding {len(texts)} texts at 1536d...")
    vectors = await embed_batch(texts, dimensions=1536)

    pairs = [
        (sid, str(vec))
        for sid, vec in zip(ids, vectors)
        if vec is not None
    ]
    print(f"  {len(pairs)} embeddings generated, writing to DB...")

    write_embeddings(pairs)

    elapsed = time.time() - t0
    print(f"\nDone! {len(pairs)} repos embedded in {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
