"""Classify projects by AI stack layer using LLM.

7 layers: model, inference, orchestration, data, eval, interface, infra.

Follows the ai_repo_subcategory.py batch JSON pattern.
Idempotent: only processes rows where stack_layer IS NULL AND is_active = true.

Run standalone:  python -m app.ingest.stack_layer
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine, SessionLocal
from app.ingest.llm import call_haiku
from app.models import SyncLog
from app.settings import settings

logger = logging.getLogger(__name__)

VALID_STACK_LAYERS = {
    "model", "inference", "orchestration", "data", "eval", "interface", "infra",
}

LLM_BATCH_SIZE = 30

STACK_LAYER_PROMPT = """\
Classify each AI/ML project into exactly one stack layer based on its PRIMARY purpose.

Layers:
- model: Training, architectures, fine-tuning (e.g. PyTorch, TensorFlow)
- inference: Serving, compilation, edge runtime (e.g. vLLM, ONNX Runtime)
- orchestration: Agent frameworks, workflows, chains (e.g. LangChain, CrewAI)
- data: RAG, vector DBs, embeddings, data pipelines (e.g. LanceDB, Kreuzberg)
- eval: Testing, monitoring, observability, benchmarks (e.g. Langfuse, Opik)
- interface: Chat UIs, IDE integrations, CLIs (e.g. big-AGI, Kilocode)
- infra: Compute, deployment, MLOps, orchestration platforms (e.g. SkyPilot, Airflow)

Rules:
- Choose the layer that best matches the PRIMARY purpose.
- Return valid JSON only — an array of objects.

Return format:
[{{"id": <project_id>, "stack_layer": "<layer>"}}, ...]

Projects:
{projects_text}"""


async def classify_stack_layers(limit: int = 1000) -> dict:
    """Use LLM to classify projects by stack layer."""
    if not settings.ANTHROPIC_API_KEY:
        logger.info("No ANTHROPIC_API_KEY — skipping stack layer classification")
        return {"classified": 0, "skipped": "no API key"}

    started_at = datetime.now(timezone.utc)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, name, LEFT(description, 200) AS description, category, topics
            FROM projects
            WHERE stack_layer IS NULL AND is_active = true
            ORDER BY id
            LIMIT :lim
        """), {"lim": limit}).fetchall()

    if not rows:
        logger.info("No unclassified projects for stack layer")
        return {"classified": 0, "batches": 0}

    logger.info(f"Stack layer classification: processing {len(rows)} projects")

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
            lines.append(f'{m["id"]}. {m["name"]} [{m["category"]}] — "{desc}" [topics: {topics_csv}]')
        projects_text = "\n".join(lines)

        predictions = await call_haiku(
            STACK_LAYER_PROMPT.format(projects_text=projects_text)
        )
        if not predictions:
            logger.warning(f"Batch {batch_idx + 1}/{len(batches)}: LLM returned no results")
            errors += 1
            continue

        updates = []
        for pred in predictions:
            if not isinstance(pred, dict):
                continue
            pid = pred.get("id")
            layer = (pred.get("stack_layer") or "").lower().strip()
            if pid not in id_set or layer not in VALID_STACK_LAYERS:
                continue
            updates.append((layer, pid))

        if updates:
            written = _batch_update_stack_layer(updates)
            total_classified += written

        logger.info(
            f"Batch {batch_idx + 1}/{len(batches)}: "
            f"{len(updates)} classified, {total_classified} total"
        )

    # Sync log
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="stack_layer",
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
    logger.info(f"Stack layer classification complete: {result}")
    return result


def _batch_update_stack_layer(updates: list[tuple[str, int]]) -> int:
    """Batch update stack_layer using temp table."""
    if not updates:
        return 0
    from psycopg2.extras import execute_values

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        cur.execute("""
            CREATE TEMP TABLE _stack_batch (
                id INTEGER PRIMARY KEY,
                stack_layer VARCHAR(20) NOT NULL
            ) ON COMMIT DROP
        """)
        execute_values(
            cur,
            "INSERT INTO _stack_batch (id, stack_layer) VALUES %s",
            [(pid, layer) for layer, pid in updates],
            template="(%s, %s)",
            page_size=1000,
        )
        cur.execute("""
            UPDATE projects p
            SET stack_layer = b.stack_layer
            FROM _stack_batch b
            WHERE p.id = b.id
        """)
        count = cur.rowcount
        raw_conn.commit()
        return count
    except Exception as e:
        try:
            raw_conn.rollback()
        except Exception:
            pass
        logger.error(f"Batch stack_layer update failed: {e}")
        return 0
    finally:
        try:
            raw_conn.close()
        except Exception:
            pass


async def main():
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = await classify_stack_layers()
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
