"""LLM-assisted matching for HN posts to labs and projects.

Runs after the regex-based backfill_hn_links() and backfill_hn_lab_links()
to handle posts that substring matching missed.

Idempotent: only processes posts where lab_id IS NULL OR project_id IS NULL.

Run standalone:  python -m app.ingest.hn_llm_match [limit]
"""
import asyncio
import logging
from datetime import datetime, timezone

from psycopg2.extras import execute_values
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.ingest.llm import call_haiku
from app.models import SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 20

HN_MATCH_PROMPT = """\
Match each Hacker News post to the AI lab and/or AI project it is \
primarily about. A post can match zero or one lab and zero or one project.

Labs (id: slug — name):
{labs_text}

Projects (id: slug — name):
{projects_text}

Rules:
- Only match if the post is PRIMARILY about that lab or project.
- lab_id and project_id are independent — a post can match one without the other.
- Return null for no match.
- Return valid JSON only — an array of objects.

Return format:
[{{"id": <post_id>, "lab_id": <lab_id or null>, "project_id": <project_id or null>}}, ...]

Posts:
{posts_text}"""


async def match_hn_posts_llm(limit: int = 5000) -> dict:
    """Use LLM to match HN posts to labs and projects."""
    if not settings.GEMINI_API_KEY:
        logger.info("No GEMINI_API_KEY — skipping HN LLM matching")
        return {"matched_labs": 0, "matched_projects": 0, "skipped": "no API key"}

    started_at = datetime.now(timezone.utc)

    # Fetch reference data once
    with engine.connect() as conn:
        lab_rows = conn.execute(text(
            "SELECT id, slug, name FROM labs ORDER BY id"
        )).fetchall()
        project_rows = conn.execute(text(
            "SELECT id, slug, name FROM projects WHERE is_active = true ORDER BY id"
        )).fetchall()
        post_rows = conn.execute(text("""
            SELECT id, title, url
            FROM hn_posts
            WHERE (lab_id IS NULL OR project_id IS NULL)
              AND llm_reviewed_at IS NULL
            ORDER BY posted_at DESC
            LIMIT :lim
        """), {"lim": limit}).fetchall()

    if not post_rows:
        logger.info("No unmatched HN posts for LLM")
        return {"matched_labs": 0, "matched_projects": 0}

    # Build reference text (passed in every prompt)
    labs_text = "\n".join(
        f'{r._mapping["id"]}: {r._mapping["slug"]} — {r._mapping["name"]}'
        for r in lab_rows
    )
    projects_text = "\n".join(
        f'{r._mapping["id"]}: {r._mapping["slug"]} — {r._mapping["name"]}'
        for r in project_rows
    )
    valid_lab_ids = {r._mapping["id"] for r in lab_rows}
    valid_project_ids = {r._mapping["id"] for r in project_rows}

    logger.info(f"HN LLM matching: processing {len(post_rows)} posts ({len(lab_rows)} labs, {len(project_rows)} projects)")

    batches = [post_rows[i:i + BATCH_SIZE] for i in range(0, len(post_rows), BATCH_SIZE)]
    post_id_set = {r._mapping["id"] for r in post_rows}

    all_updates: list[tuple[int | None, int | None, int]] = []  # (lab_id, project_id, post_id)
    errors = 0

    for batch_idx, batch in enumerate(batches):
        lines = []
        for r in batch:
            m = r._mapping
            url_part = f" (url: {m['url']})" if m.get("url") else ""
            lines.append(f'{m["id"]}. "{m["title"]}"{url_part}')
        posts_text = "\n".join(lines)

        predictions = await call_haiku(
            HN_MATCH_PROMPT.format(
                labs_text=labs_text,
                projects_text=projects_text,
                posts_text=posts_text,
            )
        )
        if not predictions:
            logger.warning(f"Batch {batch_idx + 1}/{len(batches)}: LLM returned no results")
            errors += 1
            continue

        for pred in predictions:
            if not isinstance(pred, dict):
                continue
            pid = pred.get("id")
            if pid not in post_id_set:
                continue

            lab_id = pred.get("lab_id")
            project_id = pred.get("project_id")

            # Validate IDs exist
            if lab_id is not None and lab_id not in valid_lab_ids:
                lab_id = None
            if project_id is not None and project_id not in valid_project_ids:
                project_id = None

            if lab_id is not None or project_id is not None:
                all_updates.append((lab_id, project_id, pid))

        logger.info(
            f"Batch {batch_idx + 1}/{len(batches)}: "
            f"{len(all_updates)} matches so far"
        )

    # Batch write matches + mark all processed posts as reviewed
    matched_labs = 0
    matched_projects = 0
    all_processed_ids = [r._mapping["id"] for r in post_rows]

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()

        if all_updates:
            cur.execute("""
                CREATE TEMP TABLE _hn_llm_batch (
                    id INTEGER PRIMARY KEY,
                    lab_id INTEGER,
                    project_id INTEGER
                ) ON COMMIT DROP
            """)
            execute_values(
                cur,
                "INSERT INTO _hn_llm_batch (lab_id, project_id, id) VALUES %s",
                all_updates,
                template="(%s, %s, %s)",
                page_size=1000,
            )
            # Update lab_id where currently NULL and LLM found a match
            cur.execute("""
                UPDATE hn_posts hp
                SET lab_id = b.lab_id
                FROM _hn_llm_batch b
                WHERE hp.id = b.id AND hp.lab_id IS NULL AND b.lab_id IS NOT NULL
            """)
            matched_labs = cur.rowcount

            # Update project_id where currently NULL and LLM found a match
            cur.execute("""
                UPDATE hn_posts hp
                SET project_id = b.project_id
                FROM _hn_llm_batch b
                WHERE hp.id = b.id AND hp.project_id IS NULL AND b.project_id IS NOT NULL
            """)
            matched_projects = cur.rowcount

        # Mark ALL processed posts as reviewed (match or no match)
        # so they are not reprocessed on the next run
        for chunk_start in range(0, len(all_processed_ids), 1000):
            chunk = all_processed_ids[chunk_start:chunk_start + 1000]
            cur.execute(
                "UPDATE hn_posts SET llm_reviewed_at = NOW() WHERE id = ANY(%s)",
                (chunk,)
            )

        raw_conn.commit()
    except Exception as e:
        try:
            raw_conn.rollback()
        except Exception:
            pass
        logger.error(f"HN LLM batch update failed: {e}")
        errors += 1
    finally:
        try:
            raw_conn.close()
        except Exception:
            pass

    # Sync log
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="hn_llm_match",
            status="success" if not errors else "partial",
            records_written=matched_labs + matched_projects,
            error_message=f"{errors} errors" if errors else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    result = {
        "matched_labs": matched_labs,
        "matched_projects": matched_projects,
        "batches": len(batches),
        "errors": errors,
    }
    logger.info(f"HN LLM matching complete: {result}")
    return result


async def main():
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    result = await match_hn_posts_llm(limit=lim)
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
