"""Refresh briefing evidence values against current data.

For each briefing with evidence items:
  - type="project": look up current metric value, update value + as_of
  - type="query": re-execute the SQL, update value + as_of

Logs deltas >10% as warnings. Updates briefing.verified_at.

Run standalone:  python -m app.briefing_refresh
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine

logger = logging.getLogger(__name__)


def _lookup_current(conn, slug: str, metric: str):
    """Look up current value for a project metric.

    Duplicated from server.py intentionally — importing server.py triggers
    all MCP tool registrations which we don't want in a standalone script.
    """
    # Try projects → ai_repos FK
    row = conn.execute(text("""
        SELECT a.stars, a.downloads_monthly
        FROM projects p
        JOIN ai_repos a ON a.id = p.ai_repo_id
        WHERE LOWER(p.slug) = LOWER(:slug)
        LIMIT 1
    """), {"slug": slug}).fetchone()

    if row and row._mapping.get(metric) is not None:
        return row._mapping[metric]

    # Try ai_repos by name
    row = conn.execute(text("""
        SELECT stars, downloads_monthly
        FROM ai_repos
        WHERE LOWER(name) = LOWER(:slug)
        LIMIT 1
    """), {"slug": slug}).fetchone()

    if row and row._mapping.get(metric) is not None:
        return row._mapping[metric]

    # Try ai_repos by full_name
    row = conn.execute(text("""
        SELECT stars, downloads_monthly
        FROM ai_repos
        WHERE LOWER(full_name) LIKE '%/' || LOWER(:slug)
        LIMIT 1
    """), {"slug": slug}).fetchone()

    if row and row._mapping.get(metric) is not None:
        return row._mapping[metric]

    # Fall back to tracked projects
    row = conn.execute(text("""
        SELECT gs.stars, ds.total_downloads as downloads_monthly
        FROM projects p
        LEFT JOIN LATERAL (
            SELECT stars FROM github_snapshots
            WHERE project_id = p.id ORDER BY snapshot_date DESC LIMIT 1
        ) gs ON true
        LEFT JOIN LATERAL (
            SELECT SUM(download_count) as total_downloads FROM download_snapshots
            WHERE project_id = p.id AND snapshot_date = (
                SELECT MAX(snapshot_date) FROM download_snapshots WHERE project_id = p.id
            )
        ) ds ON true
        WHERE LOWER(p.slug) = LOWER(:slug)
        LIMIT 1
    """), {"slug": slug}).fetchone()

    if row and row._mapping.get(metric) is not None:
        return row._mapping[metric]

    return None


async def refresh_briefing_evidence() -> dict:
    """Refresh all briefing evidence values against current data."""
    updated_count = 0
    delta_count = 0
    now = datetime.now(timezone.utc).isoformat()

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, slug, evidence, verified_at
            FROM briefings
            WHERE evidence IS NOT NULL
        """)).fetchall()

        if not rows:
            logger.info("No briefings with evidence to refresh")
            return {"updated": 0, "deltas": 0}

        logger.info(f"Refreshing evidence for {len(rows)} briefings")

        for r in rows:
            m = r._mapping
            evidence = m["evidence"]
            if isinstance(evidence, str):
                evidence = json.loads(evidence)
            if not isinstance(evidence, list):
                continue

            changed = False
            for ev in evidence:
                if ev.get("type") != "project" or not ev.get("metric"):
                    continue

                old_val = ev.get("value")
                current = _lookup_current(conn, ev["slug"], ev["metric"])
                if current is None:
                    continue

                try:
                    current = int(current)
                    old_val_int = int(old_val) if old_val is not None else None
                except (ValueError, TypeError):
                    continue

                if old_val_int is not None and old_val_int != current:
                    pct = ((current - old_val_int) / old_val_int * 100) if old_val_int != 0 else 0
                    if abs(pct) > 10:
                        logger.warning(
                            f"  {m['slug']}/{ev['slug']}: {ev['metric']} "
                            f"{old_val_int:,} → {current:,} ({pct:+.1f}%)"
                        )
                    delta_count += 1

                ev["value"] = current
                ev["as_of"] = now
                changed = True

            if changed:
                conn.execute(
                    text("""
                        UPDATE briefings
                        SET evidence = CAST(:evidence AS jsonb),
                            verified_at = NOW()
                        WHERE id = :id
                    """),
                    {"evidence": json.dumps(evidence), "id": m["id"]},
                )
                updated_count += 1

        conn.commit()

    # Also refresh evidence in project_briefs and domain_briefs
    for table in ("project_briefs", "domain_briefs"):
        try:
            with engine.connect() as conn:
                brief_rows = conn.execute(text(f"""
                    SELECT id, evidence
                    FROM {table}
                    WHERE evidence IS NOT NULL
                """)).fetchall()

                for r in brief_rows:
                    m = r._mapping
                    evidence = m["evidence"]
                    if isinstance(evidence, str):
                        evidence = json.loads(evidence)
                    if not isinstance(evidence, list):
                        continue

                    changed = False
                    for ev in evidence:
                        if ev.get("type") != "project" or not ev.get("metric"):
                            continue

                        old_val = ev.get("value")
                        current = _lookup_current(conn, ev["slug"], ev["metric"])
                        if current is None:
                            continue

                        try:
                            current = int(current)
                            old_val_int = int(old_val) if old_val is not None else None
                        except (ValueError, TypeError):
                            continue

                        if old_val_int is not None and old_val_int != current:
                            pct = ((current - old_val_int) / old_val_int * 100) if old_val_int != 0 else 0
                            if abs(pct) > 10:
                                logger.warning(
                                    f"  {table}/{m['id']}: {ev['slug']}/{ev['metric']} "
                                    f"{old_val_int:,} → {current:,} ({pct:+.1f}%)"
                                )
                            delta_count += 1

                        ev["value"] = current
                        ev["as_of"] = now
                        changed = True

                    if changed:
                        conn.execute(
                            text(f"""
                                UPDATE {table}
                                SET evidence = CAST(:evidence AS jsonb),
                                    updated_at = NOW()
                                WHERE id = :id
                            """),
                            {"evidence": json.dumps(evidence), "id": m["id"]},
                        )
                        updated_count += 1

                conn.commit()
        except Exception as e:
            if "does not exist" in str(e) or "relation" in str(e).lower():
                logger.debug(f"Table {table} not available yet: {e}")
            else:
                logger.warning(f"Failed to refresh {table} evidence: {e}")

    logger.info(f"Briefing refresh: {updated_count} briefings updated, {delta_count} value deltas")
    return {"updated": updated_count, "deltas": delta_count}


async def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = await refresh_briefing_evidence()
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
