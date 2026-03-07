"""One-shot backfill: fetch V2EX AI-node posts from Jan 1 2026 onward.

Paginates through target nodes (openai, claude, claudecode) until
posts are older than the date floor. Idempotent — ON CONFLICT DO NOTHING.

Rate limit: 1 request per 6 seconds (conservative, 600 req/hr cap).
"""
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import Project, Lab
from app.settings import settings
from app.ingest.hn import _match_project, _match_lab
from app.ingest.v2ex import V2EX_API_V2, TARGET_NODES, _build_row

# Backfill window
DATE_FLOOR = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def main():
    if not settings.V2EX_TOKEN:
        print("ERROR: V2EX_TOKEN not set in .env")
        sys.exit(1)

    session = SessionLocal()
    projects = session.query(Project).filter(Project.is_active.is_(True)).all()
    labs = session.query(Lab).all()
    lab_slug_to_id = {lab.slug: lab.id for lab in labs}
    session.close()

    headers = {
        "Authorization": f"Bearer {settings.V2EX_TOKEN}",
        "User-Agent": "pt-edge/1.0",
    }

    all_posts = []
    seen_ids: set[int] = set()
    floor_ts = int(DATE_FLOOR.timestamp())

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        for node in TARGET_NODES:
            page = 1
            node_count = 0
            while True:
                logger.info(f"  Fetching /{node} page {page}...")
                try:
                    resp = await client.get(
                        f"{V2EX_API_V2}/nodes/{node}/topics",
                        params={"p": page},
                    )
                    if resp.status_code != 200:
                        logger.warning(f"  V2EX API {resp.status_code} for /{node} p{page}")
                        break

                    data = resp.json()
                    topics = data if isinstance(data, list) else data.get("result", [])

                    if not topics:
                        logger.info(f"  /{node}: no more topics at page {page}")
                        break

                    hit_floor = False
                    for t in topics:
                        created = t.get("created", 0)
                        if created < floor_ts:
                            hit_floor = True
                            continue

                        row = _build_row(t, projects, lab_slug_to_id)
                        if row and row["v2ex_id"] not in seen_ids:
                            seen_ids.add(row["v2ex_id"])
                            all_posts.append(row)
                            node_count += 1

                    if hit_floor:
                        logger.info(f"  /{node}: hit date floor at page {page}")
                        break

                    page += 1

                except Exception as e:
                    logger.error(f"  Error fetching /{node} p{page}: {e}")
                    break

                await asyncio.sleep(6.0)  # 600 req/hr = 1 every 6s

            logger.info(f"  /{node}: {node_count} posts collected")

    logger.info(f"Total unique posts collected: {len(all_posts)}")

    # Batch insert
    if all_posts:
        new_count = 0
        with engine.connect() as conn:
            for post in all_posts:
                try:
                    result = conn.execute(
                        text("""
                            INSERT INTO v2ex_posts
                                (v2ex_id, title, url, content, author, replies,
                                 node_name, posted_at, captured_at, project_id, lab_id)
                            VALUES
                                (:v2ex_id, :title, :url, :content, :author, :replies,
                                 :node_name, :posted_at, :captured_at, :project_id, :lab_id)
                            ON CONFLICT (v2ex_id) DO NOTHING
                        """),
                        post,
                    )
                    if result.rowcount > 0:
                        new_count += 1
                except Exception as e:
                    logger.error(f"Insert error for v2ex_id={post['v2ex_id']}: {e}")
            conn.commit()
        logger.info(f"Inserted {new_count} new posts (skipped {len(all_posts) - new_count} duplicates)")
    else:
        logger.info("No posts collected.")


if __name__ == "__main__":
    start = time.time()
    asyncio.run(main())
    elapsed = time.time() - start
    print(f"\n✓ V2EX backfill complete ({elapsed:.0f}s)")
