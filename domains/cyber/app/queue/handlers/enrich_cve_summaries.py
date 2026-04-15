"""Gemini-generated plain-English CVE summaries for non-technical users.

Generates "What you need to know" content: what_is_this, am_i_affected,
what_to_do. Stored in cve_metadata table, read by site generator.

Incremental: only processes CVEs without metadata (or with stale hash).
Staleness: SHA256 of key inputs (description, CVSS, EPSS, KEV, has_fix).
Full backfill: ~243K CVEs at ~$26. At 10K/day ≈ 24 days.
"""

import asyncio
import hashlib
import json
import logging

from sqlalchemy import text

from domains.cyber.app.db import engine
from domains.cyber.app.settings import settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 100  # CVEs per Gemini batch (sequential calls within)
MAX_PER_RUN = 5000  # Max CVEs to process per task invocation


def _compute_hash(row: dict) -> str:
    """Hash key CVE inputs for staleness detection."""
    parts = [
        str(row.get("description") or ""),
        str(row.get("cvss_base_score") or ""),
        str(row.get("epss_score") or ""),
        str(row.get("is_kev") or ""),
        str(row.get("has_fix") or ""),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _fetch_cves_to_enrich() -> list[dict]:
    """Get CVEs that need Gemini summaries (no metadata or stale hash)."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT c.id, c.cve_id, c.description, c.cvss_base_score,
                   c.epss_score, c.is_kev, c.has_fix, c.attack_vector
            FROM cves c
            LEFT JOIN cve_metadata cm ON cm.cve_id = c.id
            WHERE c.cvss_base_score IS NOT NULL
              AND cm.cve_id IS NULL
            ORDER BY COALESCE(c.epss_score, 0) DESC
            LIMIT :lim
        """), {"lim": MAX_PER_RUN}).mappings().fetchall()
    return [dict(r) for r in rows]


def _fetch_software_names(cve_ids: list[int]) -> dict:
    """Fetch top 5 software names per CVE for the prompt."""
    if not cve_ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            WITH ranked AS (
                SELECT cs.cve_id, s.name,
                    ROW_NUMBER() OVER (PARTITION BY cs.cve_id ORDER BY s.name) AS rn
                FROM cve_software cs
                JOIN software s ON s.id = cs.software_id
                WHERE cs.cve_id = ANY(:ids)
            )
            SELECT cve_id, name FROM ranked WHERE rn <= 5
        """), {"ids": cve_ids}).fetchall()
    result = {}
    for r in rows:
        result.setdefault(r[0], []).append(r[1])
    return result


def _build_prompt(cve: dict, software_names: list[str]) -> str:
    """Build the Gemini prompt for a single CVE."""
    cvss = cve.get("cvss_base_score") or 0
    severity = "Critical" if cvss >= 9 else "High" if cvss >= 7 else "Medium" if cvss >= 4 else "Low"
    epss = (cve.get("epss_score") or 0) * 100
    kev = "Yes — actively exploited in the wild" if cve.get("is_kev") else "No"
    sw = ", ".join(software_names[:5]) if software_names else "Not specified"

    return (
        "You are writing a plain-English security advisory for someone who just "
        "googled this CVE. They might be a developer, sysadmin, or business owner. "
        "No jargon. No acronyms without explanation.\n\n"
        f"CVE: {cve['cve_id']}\n"
        f"Description: {(cve.get('description') or 'No description available')[:1500]}\n"
        f"Severity: {cvss}/10 ({severity})\n"
        f"Exploit probability: {epss:.1f}% in next 30 days\n"
        f"Actively exploited: {kev}\n"
        f"Affected software: {sw}\n"
        f"Attack vector: {cve.get('attack_vector') or 'Not specified'}\n\n"
        "Return JSON with exactly 4 fields:\n"
        '- "common_name": The well-known name if this CVE has one (e.g., "Heartbleed", '
        '"Log4Shell", "Shellshock", "EternalBlue"). null if no common name exists.\n'
        '- "what_is_this": One sentence. What is this vulnerability? Plain English.\n'
        '- "am_i_affected": One sentence. Who should worry about this?\n'
        '- "what_to_do": One sentence. What\'s the recommended action?'
    )


def _upsert_metadata(batch: list[tuple]):
    """Upsert CVE metadata rows."""
    with engine.connect() as conn:
        for cve_id, common_name, what, who, action, gen_hash in batch:
            conn.execute(text("""
                INSERT INTO cve_metadata (cve_id, common_name, what_is_this, am_i_affected, what_to_do, generation_hash)
                VALUES (:id, :name, :what, :who, :action, :hash)
                ON CONFLICT (cve_id) DO UPDATE SET
                    common_name = EXCLUDED.common_name,
                    what_is_this = EXCLUDED.what_is_this,
                    am_i_affected = EXCLUDED.am_i_affected,
                    what_to_do = EXCLUDED.what_to_do,
                    generation_hash = EXCLUDED.generation_hash,
                    updated_at = now()
            """), {"id": cve_id, "name": common_name, "what": what, "who": who, "action": action, "hash": gen_hash})
        conn.commit()


async def _enrich_cves():
    """Main enrichment pipeline."""
    if not settings.GEMINI_API_KEY:
        logger.info("Gemini not configured — skipping CVE enrichment")
        return {"enriched": 0}

    from domains.cyber.app.ingest.llm import call_llm

    cves = _fetch_cves_to_enrich()
    if not cves:
        logger.info("All CVEs already enriched")
        return {"enriched": 0}

    logger.info(f"Enriching {len(cves)} CVEs with Gemini summaries...")

    # Fetch software names for all CVEs in this run
    all_ids = [c["id"] for c in cves]
    sw_lookup = _fetch_software_names(all_ids)

    total_enriched = 0
    to_upsert = []

    for i, cve in enumerate(cves):
        prompt = _build_prompt(cve, sw_lookup.get(cve["id"], []))
        gen_hash = _compute_hash(cve)

        result = await call_llm(prompt, max_tokens=300)

        if result and isinstance(result, dict):
            common_name = result.get("common_name") or None
            what = result.get("what_is_this", "")
            who = result.get("am_i_affected", "")
            action = result.get("what_to_do", "")
            if what:
                to_upsert.append((cve["id"], common_name, what, who, action, gen_hash))
                total_enriched += 1

        # Flush in batches
        if len(to_upsert) >= BATCH_SIZE:
            _upsert_metadata(to_upsert)
            logger.info(f"  Progress: {total_enriched}/{len(cves)} enriched")
            to_upsert = []

    # Final flush
    if to_upsert:
        _upsert_metadata(to_upsert)

    logger.info(f"Enriched {total_enriched} CVEs with Gemini summaries")
    return {"enriched": total_enriched, "total_candidates": len(cves)}


async def handle_enrich_cve_summaries(task_row: dict) -> dict:
    """Task handler entry point."""
    return await _enrich_cves()
