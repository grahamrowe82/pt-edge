"""GitHub Security Advisories ingest — package-level CVEs with fix versions.

Data source: https://github.com/advisories
API: GitHub GraphQL (requires GITHUB_TOKEN)
License: Public

Paginates GitHub Security Advisories, matches CVE IDs, and updates
has_fix on the cves table when firstPatchedVersion exists.
"""

import logging
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.models import SyncLog

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.github.com/graphql"
TIMEOUT = 30
PAGE_SIZE = 100

QUERY = """
query($cursor: String) {
  securityAdvisories(first: %d, after: $cursor,
    orderBy: {field: UPDATED_AT, direction: DESC}) {
    edges {
      node {
        ghsaId
        severity
        identifiers { type value }
        vulnerabilities(first: 10) {
          edges {
            node {
              firstPatchedVersion { identifier }
              vulnerableVersionRange
              package { ecosystem name }
            }
          }
        }
      }
      cursor
    }
    pageInfo { hasNextPage endCursor }
  }
}
""" % PAGE_SIZE


def _log_sync(started: datetime, records: int, status: str = "success", error: str | None = None):
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="ghsa",
            status=status,
            records_written=records,
            error_message=error[:2000] if error else None,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()


def _extract_cve_fixes(advisories: list[dict]) -> dict[str, list[str]]:
    """Extract CVE ID → fix versions from advisory data."""
    fixes = {}
    for adv in advisories:
        cve_id = None
        for ident in adv.get("identifiers", []):
            if ident.get("type") == "CVE":
                cve_id = ident.get("value")
                break
        if not cve_id:
            continue

        fix_versions = []
        for vuln_edge in adv.get("vulnerabilities", {}).get("edges", []):
            vuln = vuln_edge.get("node", {})
            patched = vuln.get("firstPatchedVersion")
            if patched and patched.get("identifier"):
                fix_versions.append(patched["identifier"])

        if fix_versions:
            fixes[cve_id] = fix_versions

    return fixes


def _update_fix_status(fixes: dict[str, list[str]]) -> int:
    """Bulk update has_fix on cves table."""
    if not fixes:
        return 0

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        import json
        from psycopg2.extras import execute_values

        values = [(json.dumps(versions), cve_id) for cve_id, versions in fixes.items()]
        execute_values(cur, """
            UPDATE cves AS c SET
                has_fix = true,
                fix_versions = COALESCE(c.fix_versions, '[]'::jsonb) || v.versions::jsonb,
                updated_at = now()
            FROM (VALUES %s) AS v(versions, cve_id)
            WHERE c.cve_id = v.cve_id
        """, values, page_size=500)
        count = cur.rowcount
        raw.commit()
        return count
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


async def ingest_ghsa() -> dict:
    """Paginate GitHub Security Advisories and update fix status."""
    started = datetime.now(timezone.utc)

    github_token = os.environ.get("GITHUB_TOKEN", "")
    if not github_token:
        logger.info("GHSA: no GITHUB_TOKEN set — skipping")
        _log_sync(started, 0, "success")
        return {"pages": 0, "advisories": 0, "fixes": 0, "skipped": True}

    try:
        all_fixes = {}
        cursor = None
        total_advisories = 0
        pages = 0

        async with httpx.AsyncClient() as client:
            while True:
                variables = {"cursor": cursor}
                resp = await client.post(
                    GRAPHQL_URL,
                    json={"query": QUERY, "variables": variables},
                    headers={"Authorization": f"Bearer {github_token}"},
                    timeout=TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()

                edges = data.get("data", {}).get("securityAdvisories", {}).get("edges", [])
                if not edges:
                    break

                advisories = [e["node"] for e in edges]
                total_advisories += len(advisories)
                pages += 1

                fixes = _extract_cve_fixes(advisories)
                all_fixes.update(fixes)

                page_info = data.get("data", {}).get("securityAdvisories", {}).get("pageInfo", {})
                if not page_info.get("hasNextPage"):
                    break
                cursor = page_info.get("endCursor")

                if pages % 10 == 0:
                    logger.info(f"  GHSA page {pages}: {total_advisories} advisories, {len(all_fixes)} fixes")

                # Cap at 500 pages (~50K advisories) for incremental runs
                if pages >= 500:
                    break

        updated = _update_fix_status(all_fixes)
        logger.info(f"GHSA ingest complete: {pages} pages, {total_advisories} advisories, {updated} fixes")

        _log_sync(started, updated, "success")
        return {"pages": pages, "advisories": total_advisories, "fixes": len(all_fixes), "updated": updated}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.exception(f"GHSA ingest failed: {error_msg}")
        _log_sync(started, 0, "failed", error_msg)
        raise
