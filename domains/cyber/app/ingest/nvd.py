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

import logging
import re
from datetime import datetime, timezone

import httpx
from psycopg2.extras import execute_values, Json
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

def _upsert_page(
    cve_rows: list[dict],
    all_vendors: dict[str, tuple[str, str]],
    all_software: dict[str, dict],
    all_cwe_ids: set[str],
    cve_cpe_map: dict[str, list[dict]],
    cve_weakness_map: dict[str, list[dict]],
) -> dict:
    """Batch upsert an entire page of CVEs + all associations.

    One connection, one transaction, ~10 SQL round trips, one commit.
    """
    if not cve_rows:
        return {"cves": 0, "software": 0, "vendors": 0, "weaknesses": 0}

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        # Step 1: Batch upsert CVEs
        cve_values = [
            (
                r["cve_id"], r["description"], r["published_date"], r["modified_date"],
                r["cvss_base_score"], r["cvss_vector"], r["cvss_version"],
                r["attack_vector"], r["attack_complexity"], r["privileges_required"],
                r["user_interaction"], r["scope"],
                Json(r["references"]) if r["references"] else None,
            )
            for r in cve_rows
        ]
        execute_values(cur, """
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
        """, cve_values, page_size=BATCH_SIZE)
        cve_count = cur.rowcount

        # Step 2: Batch upsert vendors, resolve cpe_vendor → id
        vendor_id_map = {}
        if all_vendors:
            vendor_values = [
                (name, slug, cpe_vendor)
                for cpe_vendor, (name, slug) in all_vendors.items()
            ]
            execute_values(cur, """
                INSERT INTO vendors (name, slug, cpe_vendor)
                VALUES %s
                ON CONFLICT (cpe_vendor) DO UPDATE SET updated_at = now()
            """, vendor_values, page_size=BATCH_SIZE)

            cur.execute(
                "SELECT cpe_vendor, id FROM vendors WHERE cpe_vendor = ANY(%s)",
                (list(all_vendors.keys()),),
            )
            vendor_id_map = dict(cur.fetchall())

        # Step 3: Batch upsert software (needs vendor_id_map), resolve cpe_id → id
        software_id_map = {}
        if all_software:
            sw_values = [
                (cpe_id, info["name"], info["version"],
                 vendor_id_map[info["vendor_key"]], info["part"])
                for cpe_id, info in all_software.items()
            ]
            execute_values(cur, """
                INSERT INTO software (cpe_id, name, version, vendor_id, part)
                VALUES %s
                ON CONFLICT (cpe_id) DO UPDATE SET
                    vendor_id = EXCLUDED.vendor_id,
                    updated_at = now()
            """, sw_values, page_size=BATCH_SIZE)

            cur.execute(
                "SELECT cpe_id, id FROM software WHERE cpe_id = ANY(%s)",
                (list(all_software.keys()),),
            )
            software_id_map = dict(cur.fetchall())

        # Step 4: Batch upsert weaknesses, resolve cwe_id → id
        weakness_id_map = {}
        if all_cwe_ids:
            weakness_values = [(cwe_id, cwe_id) for cwe_id in all_cwe_ids]
            execute_values(cur, """
                INSERT INTO weaknesses (cwe_id, name)
                VALUES %s
                ON CONFLICT (cwe_id) DO NOTHING
            """, weakness_values, page_size=BATCH_SIZE)

            cur.execute(
                "SELECT cwe_id, id FROM weaknesses WHERE cwe_id = ANY(%s)",
                (list(all_cwe_ids),),
            )
            weakness_id_map = dict(cur.fetchall())

        # Step 5: Resolve CVE string IDs → integer IDs
        cve_id_strs = [r["cve_id"] for r in cve_rows]
        cur.execute(
            "SELECT cve_id, id FROM cves WHERE cve_id = ANY(%s)",
            (cve_id_strs,),
        )
        cve_id_map = dict(cur.fetchall())

        # Step 6: Batch insert all association rows
        # 6a: cve_software + collect cve_vendors pairs
        cs_rows = []
        cv_pairs = set()
        for cve_id_str, matches in cve_cpe_map.items():
            cve_int = cve_id_map.get(cve_id_str)
            if not cve_int:
                continue
            for m in matches:
                sw_int = software_id_map.get(m["cpe_id"])
                if sw_int:
                    cs_rows.append((
                        cve_int, sw_int,
                        m["version_start"], m["version_end"],
                        m["version_start_type"], m["version_end_type"],
                    ))
                v_int = vendor_id_map.get(m["vendor"])
                if v_int:
                    cv_pairs.add((cve_int, v_int))

        if cs_rows:
            execute_values(cur, """
                INSERT INTO cve_software
                    (cve_id, software_id, version_start, version_end,
                     version_start_type, version_end_type)
                VALUES %s
                ON CONFLICT (cve_id, software_id) DO NOTHING
            """, cs_rows, page_size=BATCH_SIZE)

        # 6b: cve_vendors
        if cv_pairs:
            execute_values(cur, """
                INSERT INTO cve_vendors (cve_id, vendor_id)
                VALUES %s
                ON CONFLICT (cve_id, vendor_id) DO NOTHING
            """, list(cv_pairs), page_size=BATCH_SIZE)

        # 6c: cve_weaknesses
        cw_rows = []
        for cve_id_str, weaknesses in cve_weakness_map.items():
            cve_int = cve_id_map.get(cve_id_str)
            if not cve_int:
                continue
            for w in weaknesses:
                w_int = weakness_id_map.get(w["cwe_id"])
                if w_int:
                    cw_rows.append((cve_int, w_int, w["source"][:30]))

        if cw_rows:
            execute_values(cur, """
                INSERT INTO cve_weaknesses (cve_id, weakness_id, source)
                VALUES %s
                ON CONFLICT (cve_id, weakness_id, source) DO NOTHING
            """, cw_rows, page_size=BATCH_SIZE)

        raw.commit()
        return {
            "cves": cve_count,
            "software": len(all_software),
            "vendors": len(all_vendors),
            "weaknesses": len(all_cwe_ids),
        }
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


# ---------------------------------------------------------------------------
# Main ingest
# ---------------------------------------------------------------------------

async def _process_page(data: dict) -> dict:
    """Process one page of NVD results: parse, upsert CVEs + associations.

    Two phases:
    1. Collect — parse all vulns, deduplicate entities (pure Python)
    2. Persist — one connection, ~10 batch SQL ops, one commit
    """
    vulns = data.get("vulnerabilities", [])
    if not vulns:
        return {"cves": 0, "software": 0, "vendors": 0, "weaknesses": 0}

    # --- Phase 1: Collect and deduplicate ---
    cve_rows = []
    cve_cpe_map: dict[str, list[dict]] = {}
    cve_weakness_map: dict[str, list[dict]] = {}
    all_vendors: dict[str, tuple[str, str]] = {}   # cpe_vendor → (name, slug)
    all_software: dict[str, dict] = {}              # cpe_id → {name, version, vendor_key, part}
    all_cwe_ids: set[str] = set()

    for vuln in vulns:
        parsed = _parse_cve(vuln)
        if not parsed["cve_id"]:
            continue
        cve_rows.append(parsed)
        cve_id_str = parsed["cve_id"]
        cve_obj = vuln.get("cve", {})

        # CPE matches → vendors + software
        configurations = cve_obj.get("configurations", [])
        cpe_matches = _parse_cpe_matches(configurations)
        if cpe_matches:
            cve_cpe_map[cve_id_str] = cpe_matches
            for m in cpe_matches:
                vk = m["vendor"]
                if vk not in all_vendors:
                    slug = re.sub(r"[^a-z0-9-]", "-", vk.lower()).strip("-")
                    name = vk.replace("_", " ").title()
                    all_vendors[vk] = (name, slug)
                if m["cpe_id"] not in all_software:
                    all_software[m["cpe_id"]] = {
                        "name": m["product"].replace("_", " ").title(),
                        "version": m["version"],
                        "vendor_key": vk,
                        "part": m["part"],
                    }

        # CWE refs → weaknesses
        weakness_data = cve_obj.get("weaknesses", [])
        weaknesses = _parse_weaknesses(weakness_data)
        if weaknesses:
            cve_weakness_map[cve_id_str] = weaknesses
            for w in weaknesses:
                all_cwe_ids.add(w["cwe_id"])

    # --- Phase 2: Persist (one connection, one commit) ---
    return _upsert_page(
        cve_rows, all_vendors, all_software, all_cwe_ids,
        cve_cpe_map, cve_weakness_map,
    )


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
