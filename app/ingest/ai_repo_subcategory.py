"""Classify ai_repos by subcategory using keyword matching + LLM fallback.

Supports multiple domains: mcp, agents, perception, ai-coding, rag.
Each domain has its own subcategory taxonomy.

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

# ---------------------------------------------------------------------------
# Subcategory patterns per domain — ordered specific → general, first match wins
# ---------------------------------------------------------------------------

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

AGENTS_SUBCATEGORIES: list[tuple[str, re.Pattern]] = [
    ("browser-agent", re.compile(r"browser.agent|web.agent|browser.use|playwright.agent", re.IGNORECASE)),
    ("coding-agent", re.compile(r"coding.agent|code.agent|devin|swe.agent|software.engineer", re.IGNORECASE)),
    ("research-agent", re.compile(r"research.agent|deep.research|web.research|search.agent", re.IGNORECASE)),
    ("multi-agent", re.compile(r"multi.agent|swarm|crew|orchestra|collaborative.agent", re.IGNORECASE)),
    ("agent-framework", re.compile(r"agent.framework|agent.sdk|agent.platform|build.agent|create.agent", re.IGNORECASE)),
]

PERCEPTION_SUBCATEGORIES: list[tuple[str, re.Pattern]] = [
    ("browser-automation", re.compile(r"browser.autom|playwright|puppeteer|selenium|headless|browser.use", re.IGNORECASE)),
    ("scraper", re.compile(r"scrap|crawl|spider|extract|parse.html", re.IGNORECASE)),
    ("search", re.compile(r"\bsearch\b|serp|google.search|web.search", re.IGNORECASE)),
    ("cli-access", re.compile(r"\bcli\b|command.line|terminal|shell.access", re.IGNORECASE)),
]

AI_CODING_SUBCATEGORIES: list[tuple[str, re.Pattern]] = [
    ("code-editor", re.compile(r"editor|ide|vscode|cursor|neovim|copilot.plugin", re.IGNORECASE)),
    ("code-review", re.compile(r"code.review|pull.request|pr.review|lint|static.analysis", re.IGNORECASE)),
    ("code-generation", re.compile(r"code.gen|codegen|autocomplete|code.complet|generate.code", re.IGNORECASE)),
    ("context-tools", re.compile(r"context|codebase.index|code.search|repo.map|code.graph", re.IGNORECASE)),
]

RAG_SUBCATEGORIES: list[tuple[str, re.Pattern]] = [
    ("chunking", re.compile(r"chunk|split|segment|partition|text.split", re.IGNORECASE)),
    ("retrieval", re.compile(r"retriev|search|query|hybrid.search|rerank", re.IGNORECASE)),
    ("ingestion", re.compile(r"ingest|loader|document.load|pdf|parse|extract", re.IGNORECASE)),
    ("evaluation", re.compile(r"eval|benchmark|ragas|faithfulness|relevance.score", re.IGNORECASE)),
    ("pipeline", re.compile(r"pipeline|rag.framework|orchestrat|chain|workflow", re.IGNORECASE)),
]

VOICE_AI_SUBCATEGORIES: list[tuple[str, re.Pattern]] = [
    ("tts", re.compile(r"\btts\b|text.to.speech|speech.synth|voice.clone|voice.gen", re.IGNORECASE)),
    ("stt", re.compile(r"\bstt\b|speech.to.text|speech.recog|transcri|whisper|asr\b", re.IGNORECASE)),
    ("voice-agent", re.compile(r"voice.agent|voice.assistant|voice.bot|conversation.ai|voice.ai", re.IGNORECASE)),
    ("real-time-audio", re.compile(r"real.time.audio|streaming.audio|webrtc|audio.stream|live.audio", re.IGNORECASE)),
    ("audio-processing", re.compile(r"audio.process|sound|noise|denois|audio.effect|music", re.IGNORECASE)),
]

DIFFUSION_SUBCATEGORIES: list[tuple[str, re.Pattern]] = [
    ("image-generation", re.compile(r"image.gen|txt2img|text.to.image|stable.diffusion|sdxl|flux", re.IGNORECASE)),
    ("video-generation", re.compile(r"video.gen|txt2vid|text.to.video|animate|motion", re.IGNORECASE)),
    ("ui-workflow", re.compile(r"comfyui|webui|gradio|interface|gui|frontend", re.IGNORECASE)),
    ("fine-tuning", re.compile(r"fine.tun|lora|dreambooth|textual.inversion|train", re.IGNORECASE)),
    ("controlnet", re.compile(r"controlnet|inpaint|img2img|image.edit|upscal", re.IGNORECASE)),
]

VECTOR_DB_SUBCATEGORIES: list[tuple[str, re.Pattern]] = [
    ("database", re.compile(r"vector.db|vector.database|vector.store|chroma|qdrant|weaviate|milvus|pinecone", re.IGNORECASE)),
    ("client-sdk", re.compile(r"client|sdk|python.client|javascript.client|connector", re.IGNORECASE)),
    ("indexing", re.compile(r"index|hnsw|ann\b|approximate.nearest|faiss|scann", re.IGNORECASE)),
    ("hybrid-search", re.compile(r"hybrid.search|full.text|bm25|sparse|keyword", re.IGNORECASE)),
    ("integration", re.compile(r"integrat|plugin|langchain|llamaindex|connector", re.IGNORECASE)),
]

EMBEDDINGS_SUBCATEGORIES: list[tuple[str, re.Pattern]] = [
    ("model", re.compile(r"embedding.model|sentence.transform|e5\b|bge\b|instructor|nomic", re.IGNORECASE)),
    ("server", re.compile(r"embedding.server|embedding.api|serve|inference|endpoint", re.IGNORECASE)),
    ("fine-tuning", re.compile(r"fine.tun|train|contrastive|triplet|matryoshka", re.IGNORECASE)),
    ("evaluation", re.compile(r"eval|benchmark|mteb|beir|retrieval.eval", re.IGNORECASE)),
    ("utility", re.compile(r"util|chunk|cache|batch|compress|quantiz", re.IGNORECASE)),
]

PROMPT_ENGINEERING_SUBCATEGORIES: list[tuple[str, re.Pattern]] = [
    ("prompt-framework", re.compile(r"dspy|prompt.framework|prompt.chain|prompt.flow|lmql", re.IGNORECASE)),
    ("prompt-library", re.compile(r"prompt.library|prompt.template|awesome.prompt|collection", re.IGNORECASE)),
    ("guardrails", re.compile(r"guardrail|safety|moderat|filter|content.policy|nemo", re.IGNORECASE)),
    ("output-parsing", re.compile(r"output.pars|struct|json.mode|format|schema|extract", re.IGNORECASE)),
    ("optimization", re.compile(r"optim|compress|token|cost|cach|few.shot|prompt.tun", re.IGNORECASE)),
]

# Master mapping: domain → subcategory patterns
DOMAIN_SUBCATEGORIES: dict[str, list[tuple[str, re.Pattern]]] = {
    "mcp": MCP_SUBCATEGORIES,
    "agents": AGENTS_SUBCATEGORIES,
    "perception": PERCEPTION_SUBCATEGORIES,
    "ai-coding": AI_CODING_SUBCATEGORIES,
    "rag": RAG_SUBCATEGORIES,
    "voice-ai": VOICE_AI_SUBCATEGORIES,
    "diffusion": DIFFUSION_SUBCATEGORIES,
    "vector-db": VECTOR_DB_SUBCATEGORIES,
    "embeddings": EMBEDDINGS_SUBCATEGORIES,
    "prompt-engineering": PROMPT_ENGINEERING_SUBCATEGORIES,
}

CLASSIFIED_DOMAINS = list(DOMAIN_SUBCATEGORIES.keys())


def _classify_repo(domain: str, name: str, description: str, topics: list[str] | None) -> str | None:
    """Return the first matching subcategory for the given domain, or None."""
    subcategories = DOMAIN_SUBCATEGORIES.get(domain)
    if not subcategories:
        return None
    search_text = f"{name} {description} {' '.join(topics or [])}"
    for subcategory, pattern in subcategories:
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
    """Classify uncategorized repos by subcategory across all supported domains."""
    started_at = datetime.now(timezone.utc)

    placeholders = ", ".join(f":d{i}" for i in range(len(CLASSIFIED_DOMAINS)))
    params: dict = {"lim": limit}
    params.update({f"d{i}": d for i, d in enumerate(CLASSIFIED_DOMAINS)})

    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, domain, name, description, topics
            FROM ai_repos
            WHERE domain IN ({placeholders}) AND subcategory IS NULL
            ORDER BY stars DESC
            LIMIT :lim
        """), params).fetchall()

    if not rows:
        logger.info("No uncategorized repos to classify")
        return {"classified": 0, "unmatched": 0}

    logger.info(f"Classifying {len(rows)} repos by subcategory across {CLASSIFIED_DOMAINS}")

    updates: list[tuple[str, int]] = []
    unmatched = 0

    for i, r in enumerate(rows):
        m = r._mapping
        subcategory = _classify_repo(
            m["domain"] or "",
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
    # MCP
    "testing", "security", "observability", "transport", "gateway",
    "discovery", "billing", "ide", "agent-memory", "framework",
    # Agents
    "agent-framework", "multi-agent", "coding-agent", "browser-agent", "research-agent",
    # Perception
    "scraper", "browser-automation", "cli-access", "search",
    # AI-Coding
    "code-editor", "code-review", "code-generation", "context-tools",
    # Fallback
    "other",
}

LLM_BATCH_SIZE = 30

DOMAIN_LABELS = {
    "mcp": "MCP (Model Context Protocol)",
    "agents": "AI Agent",
    "perception": "Perception / Web Data",
    "ai-coding": "AI Coding",
}

DOMAIN_VALID_SUBCATEGORIES = {
    "mcp": "testing, security, observability, transport, gateway, discovery, billing, ide, agent-memory, framework, other",
    "agents": "agent-framework, multi-agent, coding-agent, browser-agent, research-agent, other",
    "perception": "scraper, browser-automation, cli-access, search, other",
    "ai-coding": "code-editor, code-review, code-generation, context-tools, other",
}

SUBCATEGORY_LLM_PROMPT = """\
Classify each {domain_label} repository into exactly one subcategory. \
Choose from: {valid_subcategories}.

Rules:
- "other" for repos that don't fit any specific subcategory.
- Use the subcategory that best matches the PRIMARY purpose.
- Return valid JSON only — an array of objects.

Return format:
[{{"id": <repo_id>, "subcategory": "<subcategory>"}}, ...]

Repos:
{repos_text}"""


async def classify_subcategory_llm(limit: int = 7500) -> dict:
    """Use LLM to classify repos that regex didn't match, across all supported domains."""
    if not settings.GEMINI_API_KEY:
        logger.info("No GEMINI_API_KEY — skipping LLM subcategory classification")
        return {"classified": 0, "skipped": "no API key"}

    started_at = datetime.now(timezone.utc)

    placeholders = ", ".join(f":d{i}" for i in range(len(CLASSIFIED_DOMAINS)))
    params: dict = {"lim": limit}
    params.update({f"d{i}": d for i, d in enumerate(CLASSIFIED_DOMAINS)})

    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, domain, name, LEFT(description, 200) AS description, topics
            FROM ai_repos
            WHERE domain IN ({placeholders}) AND subcategory IS NULL
            ORDER BY stars DESC
            LIMIT :lim
        """), params).fetchall()

    if not rows:
        logger.info("No unclassified repos for LLM")
        return {"classified": 0, "batches": 0}

    logger.info(f"LLM subcategory classification: processing {len(rows)} repos")

    # Group rows by domain for domain-specific prompts
    domain_rows: dict[str, list] = {}
    for r in rows:
        d = r._mapping["domain"]
        domain_rows.setdefault(d, []).append(r)

    id_set = {r._mapping["id"] for r in rows}
    total_classified = 0
    errors = 0

    for domain, d_rows in domain_rows.items():
        domain_label = DOMAIN_LABELS.get(domain, domain)
        valid_subs = DOMAIN_VALID_SUBCATEGORIES.get(domain)
        if not valid_subs:
            continue

        batches = [d_rows[i:i + LLM_BATCH_SIZE] for i in range(0, len(d_rows), LLM_BATCH_SIZE)]

        for batch_idx, batch in enumerate(batches):
            lines = []
            for r in batch:
                m = r._mapping
                desc = (m["description"] or "").replace("\n", " ").strip()
                topics_csv = ", ".join(m["topics"]) if m["topics"] else ""
                lines.append(f'{m["id"]}. {m["name"]} — "{desc}" [topics: {topics_csv}]')
            repos_text = "\n".join(lines)

            predictions = await call_haiku(
                SUBCATEGORY_LLM_PROMPT.format(
                    domain_label=domain_label,
                    valid_subcategories=valid_subs,
                    repos_text=repos_text,
                )
            )
            if not predictions:
                logger.warning(f"[{domain}] Batch {batch_idx + 1}/{len(batches)}: LLM returned no results")
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
                f"[{domain}] Batch {batch_idx + 1}/{len(batches)}: "
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

    result = {"classified": total_classified, "batches": sum(len(v) for v in domain_rows.values()) // LLM_BATCH_SIZE + 1, "errors": errors}
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
