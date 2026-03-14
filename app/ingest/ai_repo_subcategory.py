"""Classify ai_repos by subcategory using keyword matching.

Currently targets domain='mcp' repos, assigning ecosystem-layer subcategories
(framework, gateway, transport, etc.) based on name + description + topics.

Idempotent: only processes rows where subcategory IS NULL.

Run standalone:  python -m app.ingest.ai_repo_subcategory
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import SyncLog

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


async def ingest_subcategories() -> dict:
    """Classify uncategorized MCP repos by subcategory."""
    started_at = datetime.now(timezone.utc)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, name, description, topics
            FROM ai_repos
            WHERE domain = 'mcp' AND subcategory IS NULL
        """)).fetchall()

    if not rows:
        logger.info("No uncategorized MCP repos to classify")
        return {"classified": 0, "unmatched": 0}

    logger.info(f"Classifying {len(rows)} MCP repos by subcategory")

    updates: list[tuple[str, int]] = []
    unmatched = 0

    for r in rows:
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

    if updates:
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE ai_repos SET subcategory = :sub WHERE id = :id"),
                [{"sub": sub, "id": rid} for sub, rid in updates],
            )
            conn.commit()

    classified = len(updates)
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


async def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = await ingest_subcategories()
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
