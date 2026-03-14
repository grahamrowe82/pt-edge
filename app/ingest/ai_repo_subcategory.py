"""Classify ai_repos by subcategory using keyword matching + LLM fallback.

Currently targets domain='mcp' repos, assigning ecosystem-layer subcategories
(framework, gateway, transport, etc.) based on name + description + topics.

Phase 1 (regex): Fast keyword matching — first-match-wins.
Phase 2 (LLM):  For repos regex missed, batch to Claude Haiku for classification.

Idempotent: only processes rows where subcategory IS NULL.

Run standalone:  python -m app.ingest.ai_repo_subcategory [limit]
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine, SessionLocal
from app.ingest.llm import call_haiku
from app.models import SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

# Ordered specific → general. First match wins.
MCP_SUBCATEGORIES: list[tuple[str, re.Pattern]] = [
    ("testing", re.compile(r"\btest|mock|fixture|bench", re.IGNORECASE)),
    ("security", re.compile(r"\bauth\b|\boauth\b|security|\brbac\b|permission", re.IGNORECASE)),
    ("observability", re.compile(r"monitor|inspector|debug|observ|trace|telemetry", re.IGNORECASE)),
    ("transport", re.compile(r"transport|\bsse\b|\bstdio\b|streamable.http", re.IGNORECASE)),
    ("gateway", re.compile(r"gateway|proxy|router|\bhub\b|multiplexer|aggregator|metamcp", re.IGNORECASE)),
    ("discovery", re.compile(r"registry|catalog|marketplace|directory", re.IGNORECASE)),
    ("billing", re.compile(r"billing|payment|monetiz|metering", re.IGNORECASE)),
    ("ide", re.compile(r"vscode|neovim|\bvim\b|emacs|jetbrains|unity|unreal|cursor", re.IGNORECASE)),
    ("agent-memory", re.compile(r"\bmemory\b|knowledge.graph|long.term.memory", re.IGNORECASE)),
    ("framework", re.compile(r"fastmcp|mcp.framework|mcp.sdk|create.mcp|\bsdk\b", re.IGNORECASE)),
]


def _classify_mcp(name: str, description: str, topics: list[str] | None) -> str | None:
    """Return the first matching subcategory or None."""
    search_text = f"{name} {description} {' '.join(topics or [])}"
    for subcategory, pattern in MCP_SUBCATEGORIES:
        if pattern.search(search_text):
            return subcategory
    return None


def _batch_update_subcategory(updates: list[tuple[str, int]]) -> int:
    """Batch update subcategory using temp table + execute_values.

    Each tuple: (subcategory, id)
    """
    if not updates:
        return 0
    from psycopg2.extras import execute_values

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        cur.execute("""
            CREATE TEMP TABLE _sub_batch (
                id INTEGER PRIMARY KEY,
                subcategory VARCHAR(50) NOT NULL
            ) ON COMMIT DROP
        """)
        execute_values(
            cur,
            "INSERT INTO _sub_batch (id, subcategory) VALUES %s",
            [(rid, sub) for sub, rid in updates],
            template="(%s, %s)",
            page_size=1000,
        )
        cur.execute("""
            UPDATE ai_repos a
            SET subcategory = b.subcategory
            FROM _sub_batch b
            WHERE a.id = b.id
        """)
        count = cur.rowcount
        raw_conn.commit()
        return count
    except Exception as e:
        try:
            raw_conn.rollback()
        except Exception:
            pass
        logger.error(f"Batch subcategory update failed: {e}")
        return 0
    finally:
        try:
            raw_conn.close()
        except Exception:
            pass


async def ingest_subcategories(limit: int = 50000) -> dict:
    """Classify uncategorized MCP repos by subcategory."""
    started_at = datetime.now(timezone.utc)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, name, description, topics
            FROM ai_repos
            WHERE domain = 'mcp' AND subcategory IS NULL
            ORDER BY stars DESC
            LIMIT :lim
        """), {"lim": limit}).fetchall()

    if not rows:
        logger.info("No uncategorized MCP repos to classify")
        return {"classified": 0, "unmatched": 0}

    logger.info(f"Classifying {len(rows)} MCP repos by subcategory")

    updates: list[tuple[str, int]] = []
    unmatched = 0

    for i, r in enumerate(rows):
        m = r._mapping
        subcategory = _classify_mcp(
            m["name"] or "",
            m["description"] or "",
            list(m["topics"]) if m["topics"] else None,
        )
        if subcategory:
            updates.append((subcategory, m["id"]))
        else:
            unmatched += 1

        if (i + 1) % 5000 == 0:
            logger.info(f"  classified {i + 1}/{len(rows)} ({len(updates)} matched)")

    classified = _batch_update_subcategory(updates)
    logger.info(f"Subcategory classification: {classified} classified, {unmatched} unmatched")

    # Sync log
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="ai_repo_subcategory",
            status="success",
            records_written=classified,
            error_message=f"{unmatched} unmatched" if unmatched else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    return {"classified": classified, "unmatched": unmatched}


# ---------------------------------------------------------------------------
# Phase 2: LLM fallback for repos regex didn't match
# ---------------------------------------------------------------------------

VALID_SUBCATEGORIES = {
    "testing", "security", "observability", "transport", "gateway",
    "discovery", "billing", "ide", "agent-memory", "framework", "other",
}

LLM_BATCH_SIZE = 30

SUBCATEGORY_LLM_PROMPT = """\
Classify each MCP (Model Context Protocol) repository into exactly one \
subcategory. Choose from: testing, security, observability, transport, \
gateway, discovery, billing, ide, agent-memory, framework, other.

Rules:
- "other" for repos that don't fit any specific subcategory.
- Use the subcategory that best matches the PRIMARY purpose.
- Return valid JSON only — an array of objects.

Return format:
[{{"id": <repo_id>, "subcategory": "<subcategory>"}}, ...]

Repos:
{repos_text}"""


async def classify_subcategory_llm(limit: int = 7500) -> dict:
    """Use LLM to classify MCP repos that regex didn't match."""
    if not settings.ANTHROPIC_API_KEY:
        logger.info("No ANTHROPIC_API_KEY — skipping LLM subcategory classification")
        return {"classified": 0, "skipped": "no API key"}

    started_at = datetime.now(timezone.utc)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, name, LEFT(description, 200) AS description, topics
            FROM ai_repos
            WHERE domain = 'mcp' AND subcategory IS NULL
            ORDER BY stars DESC
            LIMIT :lim
        """), {"lim": limit}).fetchall()

    if not rows:
        logger.info("No unclassified MCP repos for LLM")
        return {"classified": 0, "batches": 0}

    logger.info(f"LLM subcategory classification: processing {len(rows)} repos")

    # Build batches
    batches = [rows[i:i + LLM_BATCH_SIZE] for i in range(0, len(rows), LLM_BATCH_SIZE)]
    id_set = {r._mapping["id"] for r in rows}

    total_classified = 0
    errors = 0

    for batch_idx, batch in enumerate(batches):
        lines = []
        for r in batch:
            m = r._mapping
            desc = (m["description"] or "").replace("\n", " ").strip()
            topics_csv = ", ".join(m["topics"]) if m["topics"] else ""
            lines.append(f'{m["id"]}. {m["name"]} — "{desc}" [topics: {topics_csv}]')
        repos_text = "\n".join(lines)

        predictions = await call_haiku(
            SUBCATEGORY_LLM_PROMPT.format(repos_text=repos_text)
        )
        if not predictions:
            logger.warning(f"Batch {batch_idx + 1}/{len(batches)}: LLM returned no results")
            errors += 1
            continue

        updates: list[tuple[str, int]] = []
        for pred in predictions:
            if not isinstance(pred, dict):
                continue
            rid = pred.get("id")
            sub = (pred.get("subcategory") or "").lower().strip()
            if rid not in id_set or sub not in VALID_SUBCATEGORIES:
                continue
            if sub == "other":
                continue  # Leave NULL for manual review
            updates.append((sub, rid))

        if updates:
            written = _batch_update_subcategory(updates)
            total_classified += written

        logger.info(
            f"Batch {batch_idx + 1}/{len(batches)}: "
            f"{len(updates)} classified, {total_classified} total"
        )

    # Sync log
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="subcategory_llm",
            status="success" if not errors else "partial",
            records_written=total_classified,
            error_message=f"{errors} LLM errors" if errors else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()

    result = {"classified": total_classified, "batches": len(batches), "errors": errors}
    logger.info(f"LLM subcategory classification complete: {result}")
    return result


async def main():
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 50000
    result = await ingest_subcategories(limit=lim)
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
