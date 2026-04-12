"""NVD CVE ingest — CVEs, software products, vendors, and weakness links.

Data source: https://nvd.nist.gov/
API: REST at https://services.nvd.nist.gov/rest/json/cves/2.0
License: Public domain (US Government)

This module provides the highest-value data for CyberEdge: CVEs with CVSS
scores, CPE matches (linking to software/vendors), and CWE references
(linking to the weakness taxonomy).

Bootstrap mode: Paginate all ~250K CVEs from the NVD API 2.0.
Incremental mode: Fetch CVEs modified since last successful sync.
"""

import json
import logging
import re
from datetime import datetime, timezone

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from domains.cyber.app.db import engine, SessionLocal
from domains.cyber.app.ingest.rate_limit import NVD_LIMITER
from domains.cyber.app.models import SyncLog
from domains.cyber.app.settings import settings

logger = logging.getLogger(__name__)

API_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"
RESULTS_PER_PAGE = 2000
BATCH_SIZE = 500
TIMEOUT = 60  # seconds per API request


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_bootstrap() -> bool:
    """Check if we've ever completed a successful NVD ingest."""
    with engine.connect() as conn:
        count = conn.execute(text("""
            SELECT COUNT(*) FROM sync_log
            WHERE sync_type = 'nvd'
              AND status IN ('success', 'partial')
        """)).scalar()
    return count == 0


def _last_sync_time() -> datetime | None:
    """Get the finished_at of the most recent successful NVD sync."""
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT finished_at FROM sync_log
            WHERE sync_type = 'nvd'
              AND status IN ('success', 'partial')
            ORDER BY finished_at DESC
            LIMIT 1
        """)).fetchone()
    return row[0] if row else None


def _log_sync(started: datetime, records: int, status: str = "success", error: str | None = None):
    """Write a sync_log entry for this ingest run."""
    session = SessionLocal()
    try:
        session.add(SyncLog(
            sync_type="nvd",
            status=status,
            records_written=records,
            error_message=error[:2000] if error else None,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        ))
        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# NVD API
# ---------------------------------------------------------------------------

async def _fetch_page(client: httpx.AsyncClient, params: dict) -> dict:
    """Fetch one page from NVD API 2.0 with rate limiting."""
    await NVD_LIMITER.acquire()

    headers = {}
    if settings.NVD_API_KEY:
        headers["apiKey"] = settings.NVD_API_KEY

    resp = await client.get(API_BASE, params=params, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_cve(vuln: dict) -> dict:
    """Parse a single NVD API vulnerability object into our CVE fields."""
    cve = vuln.get("cve", {})

    # Description (prefer English)
    description = None
    for desc in cve.get("descriptions", []):
        if desc.get("lang") == "en":
            description = desc.get("value")
            break

    # CVSS: prefer v3.1, fall back to v3.0, then v2
    cvss_data = None
    for key in ("cvssMetricV31", "cvssMetricV30"):
        metrics = cve.get("metrics", {}).get(key, [])
        if metrics:
            cvss_data = metrics[0].get("cvssData", {})
            break

    return {
        "cve_id": cve.get("id"),
        "description": description,
        "published_date": cve.get("published"),
        "modified_date": cve.get("lastModified"),
        "cvss_base_score": cvss_data.get("baseScore") if cvss_data else None,
        "cvss_vector": cvss_data.get("vectorString") if cvss_data else None,
        "cvss_version": cvss_data.get("version") if cvss_data else None,
        "attack_vector": cvss_data.get("attackVector") if cvss_data else None,
        "attack_complexity": cvss_data.get("attackComplexity") if cvss_data else None,
        "privileges_required": cvss_data.get("privilegesRequired") if cvss_data else None,
        "user_interaction": cvss_data.get("userInteraction") if cvss_data else None,
        "scope": cvss_data.get("scope") if cvss_data else None,
        "references": [
            {"url": ref.get("url"), "source": ref.get("source"), "tags": ref.get("tags", [])}
            for ref in cve.get("references", [])
        ],
    }


def _parse_cpe_uri(cpe23: str) -> dict | None:
    """Parse CPE 2.3 URI string into components.

    Format: cpe:2.3:part:vendor:product:version:update:edition:language:sw_edition:target_sw:target_hw:other
    """
    parts = cpe23.split(":")
    if len(parts) < 6:
        return None
    vendor = parts[3]
    product = parts[4]
    version = parts[5] if parts[5] != "*" else None
    if vendor == "*" or product == "*":
        return None
    return {
        "part": parts[2],
        "vendor": vendor,
        "product": product,
        "version": version,
        "cpe_id": cpe23,
    }


def _parse_cpe_matches(configurations: list[dict]) -> list[dict]:
    """Extract CPE match records from CVE configurations/nodes tree."""
    matches = []
    for config in configurations:
        for node in config.get("nodes", []):
            for match in node.get("cpeMatch", []):
                if not match.get("vulnerable", True):
                    continue
                criteria = match.get("criteria", "")
                parsed = _parse_cpe_uri(criteria)
                if parsed:
                    parsed["version_start"] = (
                        match.get("versionStartIncluding") or match.get("versionStartExcluding")
                    )
                    parsed["version_end"] = (
                        match.get("versionEndIncluding") or match.get("versionEndExcluding")
                    )
                    parsed["version_start_type"] = (
                        "including" if match.get("versionStartIncluding") else
                        "excluding" if match.get("versionStartExcluding") else None
                    )
                    parsed["version_end_type"] = (
                        "including" if match.get("versionEndIncluding") else
                        "excluding" if match.get("versionEndExcluding") else None
                    )
                    matches.append(parsed)
    return matches


def _parse_weaknesses(weaknesses: list[dict]) -> list[dict]:
    """Extract CWE IDs from CVE weakness data."""
    results = []
    for w in weaknesses:
        source = w.get("source", "nvd")
        for desc in w.get("description", []):
            cwe_id = desc.get("value", "")
            if re.match(r"^CWE-\d+$", cwe_id):
                results.append({"cwe_id": cwe_id, "source": source})
    return results


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

def _upsert_cves(rows: list[dict]) -> int:
    """Batch upsert CVEs. Returns count of rows affected."""
    if not rows:
        return 0
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        values = [
            (
                r["cve_id"], r["description"], r["published_date"], r["modified_date"],
                r["cvss_base_score"], r["cvss_vector"], r["cvss_version"],
                r["attack_vector"], r["attack_complexity"], r["privileges_required"],
                r["user_interaction"], r["scope"],
                json.dumps(r["references"]) if r["references"] else None,
            )
            for r in rows
        ]
        sql = """
            INSERT INTO cves (
                cve_id, description, published_date, modified_date,
                cvss_base_score, cvss_vector, cvss_version,
                attack_vector, attack_complexity, privileges_required,
                user_interaction, scope, "references"
            ) VALUES %s
            ON CONFLICT (cve_id) DO UPDATE SET
                description = EXCLUDED.description,
                modified_date = EXCLUDED.modified_date,
                cvss_base_score = EXCLUDED.cvss_base_score,
                cvss_vector = EXCLUDED.cvss_vector,
                cvss_version = EXCLUDED.cvss_version,
                attack_vector = EXCLUDED.attack_vector,
                attack_complexity = EXCLUDED.attack_complexity,
                privileges_required = EXCLUDED.privileges_required,
                user_interaction = EXCLUDED.user_interaction,
                scope = EXCLUDED.scope,
                "references" = EXCLUDED."references",
                updated_at = now()
        """
        execute_values(cur, sql, values, page_size=BATCH_SIZE)
        count = cur.rowcount
        raw.commit()
        return count
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _upsert_software_and_vendors(cve_id_str: str, cpe_matches: list[dict]) -> tuple[int, int]:
    """Upsert software products + vendors from CPE matches, create links."""
    if not cpe_matches:
        return 0, 0

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        sw_count = 0
        vendor_count = 0

        # Deduplicate vendors and software within this batch
        vendors_seen = {}
        software_seen = {}

        for m in cpe_matches:
            vendor_key = m["vendor"]
            if vendor_key not in vendors_seen:
                slug = re.sub(r"[^a-z0-9-]", "-", vendor_key.lower()).strip("-")
                name = vendor_key.replace("_", " ").title()
                execute_values(cur, """
                    INSERT INTO vendors (name, slug, cpe_vendor)
                    VALUES %s
                    ON CONFLICT (cpe_vendor) DO UPDATE SET
                        updated_at = now()
                    RETURNING id
                """, [(name, slug, vendor_key)], page_size=1)
                row = cur.fetchone()
                vendors_seen[vendor_key] = row[0]
                vendor_count += 1

            vendor_id = vendors_seen[vendor_key]

            cpe_id = m["cpe_id"]
            if cpe_id not in software_seen:
                name = m["product"].replace("_", " ").title()
                execute_values(cur, """
                    INSERT INTO software (cpe_id, name, version, vendor_id, part)
                    VALUES %s
                    ON CONFLICT (cpe_id) DO UPDATE SET
                        vendor_id = EXCLUDED.vendor_id,
                        updated_at = now()
                    RETURNING id
                """, [(cpe_id, name, m["version"], vendor_id, m["part"])], page_size=1)
                row = cur.fetchone()
                software_seen[cpe_id] = row[0]
                sw_count += 1

            software_id = software_seen[cpe_id]

            # Link CVE → software
            cur.execute("""
                INSERT INTO cve_software (cve_id, software_id, version_start, version_end,
                                          version_start_type, version_end_type)
                SELECT c.id, %s, %s, %s, %s, %s
                FROM cves c WHERE c.cve_id = %s
                ON CONFLICT (cve_id, software_id) DO NOTHING
            """, (software_id, m["version_start"], m["version_end"],
                  m["version_start_type"], m["version_end_type"], cve_id_str))

            # Link CVE → vendor
            cur.execute("""
                INSERT INTO cve_vendors (cve_id, vendor_id)
                SELECT c.id, %s
                FROM cves c WHERE c.cve_id = %s
                ON CONFLICT (cve_id, vendor_id) DO NOTHING
            """, (vendor_id, cve_id_str))

        raw.commit()
        return sw_count, vendor_count
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _upsert_cve_weaknesses(cve_id_str: str, weaknesses: list[dict]) -> int:
    """Upsert CWE weakness records and link to CVE."""
    if not weaknesses:
        return 0

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        count = 0
        for w in weaknesses:
            # Upsert weakness
            execute_values(cur, """
                INSERT INTO weaknesses (cwe_id, name)
                VALUES %s
                ON CONFLICT (cwe_id) DO NOTHING
                RETURNING id
            """, [(w["cwe_id"], w["cwe_id"])], page_size=1)
            row = cur.fetchone()
            if row:
                weakness_id = row[0]
            else:
                cur.execute("SELECT id FROM weaknesses WHERE cwe_id = %s", (w["cwe_id"],))
                weakness_id = cur.fetchone()[0]

            # Link CVE → weakness
            cur.execute("""
                INSERT INTO cve_weaknesses (cve_id, weakness_id, source)
                SELECT c.id, %s, %s
                FROM cves c WHERE c.cve_id = %s
                ON CONFLICT (cve_id, weakness_id, source) DO NOTHING
            """, (weakness_id, w["source"][:30], cve_id_str))
            count += 1

        raw.commit()
        return count
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


# ---------------------------------------------------------------------------
# Main ingest
# ---------------------------------------------------------------------------

async def _process_page(data: dict) -> dict:
    """Process one page of NVD results: parse, upsert CVEs + associations."""
    vulns = data.get("vulnerabilities", [])
    if not vulns:
        return {"cves": 0, "software": 0, "vendors": 0, "weaknesses": 0}

    cve_rows = []
    total_sw = 0
    total_vendors = 0
    total_weaknesses = 0

    for vuln in vulns:
        parsed = _parse_cve(vuln)
        if not parsed["cve_id"]:
            continue
        cve_rows.append(parsed)

    # Batch upsert CVEs first
    cve_count = _upsert_cves(cve_rows)

    # Then process CPE matches and CWE refs per CVE
    for vuln in vulns:
        cve_obj = vuln.get("cve", {})
        cve_id_str = cve_obj.get("id")
        if not cve_id_str:
            continue

        # CPE matches → software + vendors + links
        configurations = cve_obj.get("configurations", [])
        cpe_matches = _parse_cpe_matches(configurations)
        sw, ven = _upsert_software_and_vendors(cve_id_str, cpe_matches)
        total_sw += sw
        total_vendors += ven

        # CWE refs → weaknesses + links
        weakness_data = cve_obj.get("weaknesses", [])
        weaknesses = _parse_weaknesses(weakness_data)
        total_weaknesses += _upsert_cve_weaknesses(cve_id_str, weaknesses)

    return {
        "cves": cve_count,
        "software": total_sw,
        "vendors": total_vendors,
        "weaknesses": total_weaknesses,
    }


async def _bootstrap(client: httpx.AsyncClient) -> dict:
    """Paginate all CVEs from NVD API 2.0."""
    logger.info("NVD bootstrap: fetching all CVEs")
    start_index = 0
    total_results = None
    totals = {"cves": 0, "software": 0, "vendors": 0, "weaknesses": 0, "pages": 0}

    while True:
        params = {"startIndex": start_index, "resultsPerPage": RESULTS_PER_PAGE}
        data = await _fetch_page(client, params)

        if total_results is None:
            total_results = data.get("totalResults", 0)
            logger.info(f"NVD reports {total_results:,} total CVEs")

        page_counts = await _process_page(data)
        totals["pages"] += 1
        for k in ("cves", "software", "vendors", "weaknesses"):
            totals[k] += page_counts[k]

        if totals["pages"] % 10 == 0:
            logger.info(
                f"  Page {totals['pages']}: {totals['cves']:,} CVEs, "
                f"{totals['software']:,} software, {totals['vendors']:,} vendors"
            )

        start_index += RESULTS_PER_PAGE
        if start_index >= total_results:
            break

    totals["mode"] = "bootstrap"
    logger.info(f"NVD bootstrap complete: {totals}")
    return totals


async def _incremental(client: httpx.AsyncClient) -> dict:
    """Fetch CVEs modified since last successful sync."""
    last_sync = _last_sync_time()
    if not last_sync:
        return await _bootstrap(client)

    now = datetime.now(timezone.utc)
    last_mod_start = last_sync.strftime("%Y-%m-%dT%H:%M:%S.000+00:00")
    last_mod_end = now.strftime("%Y-%m-%dT%H:%M:%S.000+00:00")

    logger.info(f"NVD incremental: {last_mod_start} → {last_mod_end}")

    start_index = 0
    total_results = None
    totals = {"cves": 0, "software": 0, "vendors": 0, "weaknesses": 0, "pages": 0}

    while True:
        params = {
            "startIndex": start_index,
            "resultsPerPage": RESULTS_PER_PAGE,
            "lastModStartDate": last_mod_start,
            "lastModEndDate": last_mod_end,
        }
        data = await _fetch_page(client, params)

        if total_results is None:
            total_results = data.get("totalResults", 0)
            logger.info(f"NVD incremental: {total_results:,} modified CVEs")
            if total_results == 0:
                return {"mode": "incremental", "skipped": True, **totals}

        page_counts = await _process_page(data)
        totals["pages"] += 1
        for k in ("cves", "software", "vendors", "weaknesses"):
            totals[k] += page_counts[k]

        start_index += RESULTS_PER_PAGE
        if start_index >= total_results:
            break

    totals["mode"] = "incremental"
    logger.info(f"NVD incremental complete: {totals}")
    return totals


async def ingest_nvd() -> dict:
    """Main entry point. Detects bootstrap vs incremental, runs appropriate mode."""
    started = datetime.now(timezone.utc)
    bootstrap = _is_bootstrap()

    try:
        async with httpx.AsyncClient() as client:
            if bootstrap:
                result = await _bootstrap(client)
            else:
                result = await _incremental(client)

        _log_sync(started, result.get("cves", 0), "success")
        return result

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.exception(f"NVD ingest failed: {error_msg}")
        _log_sync(started, 0, "failed", error_msg)
        raise
