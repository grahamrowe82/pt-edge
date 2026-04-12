"""MCP tools for CyberEdge — cybersecurity vulnerability intelligence.

10 tools covering CVE lookup, software risk, vendor profiles, kill chain
traversal, exploit discovery, trending, and raw SQL queries.
"""

import re
import logging

from sqlalchemy import text

from domains.cyber.app.db import readonly_engine
from domains.cyber.app.mcp.instance import mcp
from domains.cyber.app.mcp.tracking import track_usage

logger = logging.getLogger(__name__)

# SQL injection blocklist for the query() tool
_BLOCKED_PATTERNS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|GRANT|REVOKE|COPY|CREATE|pg_read_file)\b",
    re.IGNORECASE,
)


def mount_mcp(app):
    """Mount MCP server on the FastAPI app."""
    mcp_app = mcp.http_app()
    app.mount("/mcp", mcp_app)


@mcp.tool()
@track_usage
async def about() -> str:
    """Overview of CyberEdge data coverage and freshness."""
    with readonly_engine.connect() as conn:
        counts = {}
        for table, label in [
            ("cves", "CVEs"), ("software", "Software"), ("vendors", "Vendors"),
            ("weaknesses", "Weaknesses"), ("techniques", "Techniques"),
            ("attack_patterns", "Attack Patterns"),
        ]:
            counts[label] = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()

    lines = ["CyberEdge — Cybersecurity Vulnerability Intelligence", ""]
    for label, count in counts.items():
        lines.append(f"  {label}: {count:,}")
    lines.append("")
    lines.append("Scoring: 4 dimensions x 25 points = 0-100 composite")
    lines.append("Dimensions: severity, exploitability, exposure, patch_availability")
    lines.append("Kill chain: CVE → CWE → CAPEC → ATT&CK")
    return "\n".join(lines)


@mcp.tool()
@track_usage
async def cve_lookup(cve_id: str) -> str:
    """Full CVE profile with scores, CVSS, EPSS, KEV status, and kill chain."""
    with readonly_engine.connect() as conn:
        row = conn.execute(text("""
            SELECT c.cve_id, c.description, c.cvss_base_score, c.cvss_vector,
                   c.epss_score, c.is_kev, c.attack_vector, c.attack_complexity,
                   cs.composite_score, cs.quality_tier, cs.severity, cs.exploitability,
                   cs.exposure, cs.patch_availability
            FROM cves c LEFT JOIN mv_cve_scores cs ON cs.id = c.id
            WHERE c.cve_id = :cid
        """), {"cid": cve_id}).mappings().fetchone()

    if not row:
        return f"CVE {cve_id} not found."

    lines = [f"{row['cve_id']} — {row['composite_score'] or 0}/100 ({row['quality_tier'] or 'unscored'})"]
    if row["description"]:
        lines.append(row["description"][:300])
    lines.append(f"\nCVSS: {row['cvss_base_score']}  EPSS: {row['epss_score']}  KEV: {row['is_kev']}")
    lines.append(f"Severity: {row['severity']}/25  Exploitability: {row['exploitability']}/25")
    lines.append(f"Exposure: {row['exposure']}/25  Patch: {row['patch_availability']}/25")

    # Kill chain
    with readonly_engine.connect() as conn:
        chain = conn.execute(text("""
            SELECT DISTINCT w.cwe_id, ap.capec_id, t.technique_id, t.name
            FROM cves c
            JOIN cve_weaknesses cw ON cw.cve_id = c.id
            JOIN weaknesses w ON w.id = cw.weakness_id
            LEFT JOIN weakness_patterns wp ON wp.weakness_id = w.id
            LEFT JOIN attack_patterns ap ON ap.id = wp.pattern_id
            LEFT JOIN pattern_techniques pt ON pt.pattern_id = ap.id
            LEFT JOIN techniques t ON t.id = pt.technique_id
            WHERE c.cve_id = :cid
        """), {"cid": cve_id}).fetchall()

    if chain:
        lines.append("\nKill chain:")
        for r in chain[:10]:
            parts = [r[0]]
            if r[1]:
                parts.append(r[1])
            if r[2]:
                parts.append(f"{r[2]} ({r[3]})")
            lines.append("  " + " → ".join(parts))

    return "\n".join(lines)


@mcp.tool()
@track_usage
async def software_risk(name: str) -> str:
    """Software vulnerability risk profile."""
    with readonly_engine.connect() as conn:
        row = conn.execute(text("""
            SELECT s.name, s.cpe_id, ss.composite_score, ss.quality_tier,
                   ss.severity, ss.exploitability, ss.exposure, ss.patch_availability
            FROM software s LEFT JOIN mv_software_scores ss ON ss.id = s.id
            WHERE s.name ILIKE :q
            ORDER BY ss.composite_score DESC NULLS LAST LIMIT 1
        """), {"q": f"%{name}%"}).mappings().fetchone()
    if not row:
        return f"Software '{name}' not found."
    return (f"{row['name']} — {row['composite_score'] or 0}/100 ({row['quality_tier'] or 'unscored'})\n"
            f"Severity: {row['severity']}/25  Exploitability: {row['exploitability']}/25\n"
            f"Exposure: {row['exposure']}/25  Patch: {row['patch_availability']}/25")


@mcp.tool()
@track_usage
async def vendor_profile(name: str) -> str:
    """Vendor vulnerability risk assessment."""
    with readonly_engine.connect() as conn:
        row = conn.execute(text("""
            SELECT v.name, v.slug, vs.composite_score, vs.quality_tier,
                   vs.severity, vs.exploitability, vs.exposure, vs.patch_availability
            FROM vendors v LEFT JOIN mv_vendor_scores vs ON vs.id = v.id
            WHERE v.name ILIKE :q
            ORDER BY vs.composite_score DESC NULLS LAST LIMIT 1
        """), {"q": f"%{name}%"}).mappings().fetchone()
    if not row:
        return f"Vendor '{name}' not found."
    return (f"{row['name']} — {row['composite_score'] or 0}/100 ({row['quality_tier'] or 'unscored'})\n"
            f"Severity: {row['severity']}/25  Exploitability: {row['exploitability']}/25\n"
            f"Exposure: {row['exposure']}/25  Patch: {row['patch_availability']}/25")


@mcp.tool()
@track_usage
async def find_exploited(min_epss: float = 0.5, kev_only: bool = False, limit: int = 20) -> str:
    """Find actively exploited CVEs by EPSS score and/or KEV status."""
    conditions = ["c.epss_score >= :epss"]
    params = {"epss": min_epss, "lim": min(limit, 100)}
    if kev_only:
        conditions.append("c.is_kev = true")
    where = " AND ".join(conditions)

    with readonly_engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT c.cve_id, c.cvss_base_score, c.epss_score, c.is_kev,
                   cs.composite_score, cs.quality_tier
            FROM cves c LEFT JOIN mv_cve_scores cs ON cs.id = c.id
            WHERE {where}
            ORDER BY c.epss_score DESC LIMIT :lim
        """), params).fetchall()

    if not rows:
        return "No CVEs found matching criteria."
    lines = [f"Found {len(rows)} exploited CVEs (EPSS >= {min_epss}):\n"]
    for r in rows:
        lines.append(f"  {r[0]}  CVSS:{r[1]}  EPSS:{r[2]:.3f}  KEV:{r[3]}  Score:{r[4]}/100")
    return "\n".join(lines)


@mcp.tool()
@track_usage
async def weakness_analysis(cwe_id: str) -> str:
    """CWE weakness analysis with linked attack patterns and techniques."""
    with readonly_engine.connect() as conn:
        row = conn.execute(text("""
            SELECT w.cwe_id, w.name, w.description, ws.composite_score, ws.quality_tier
            FROM weaknesses w LEFT JOIN mv_weakness_scores ws ON ws.id = w.id
            WHERE w.cwe_id = :cid
        """), {"cid": cwe_id}).mappings().fetchone()
    if not row:
        return f"Weakness {cwe_id} not found."
    lines = [f"{row['cwe_id']}: {row['name']} — {row['composite_score'] or 0}/100"]
    if row["description"]:
        lines.append(row["description"][:300])
    return "\n".join(lines)


@mcp.tool()
@track_usage
async def attack_chain(technique_id: str) -> str:
    """Trace ATT&CK technique back through CAPEC and CWE to CVEs."""
    with readonly_engine.connect() as conn:
        row = conn.execute(text("""
            SELECT t.technique_id, t.name, ts.composite_score, ts.quality_tier
            FROM techniques t LEFT JOIN mv_technique_scores ts ON ts.id = t.id
            WHERE t.technique_id = :tid
        """), {"tid": technique_id}).mappings().fetchone()

    if not row:
        return f"Technique {technique_id} not found."

    lines = [f"{row['technique_id']}: {row['name']} — {row['composite_score'] or 0}/100\n"]

    with readonly_engine.connect() as conn:
        chain = conn.execute(text("""
            SELECT DISTINCT ap.capec_id, ap.name AS pattern_name,
                   w.cwe_id, w.name AS weakness_name,
                   c.cve_id, cs.composite_score AS cve_score
            FROM techniques t
            JOIN pattern_techniques pt ON pt.technique_id = t.id
            JOIN attack_patterns ap ON ap.id = pt.pattern_id
            JOIN weakness_patterns wp ON wp.pattern_id = ap.id
            JOIN weaknesses w ON w.id = wp.weakness_id
            JOIN cve_weaknesses cw ON cw.weakness_id = w.id
            JOIN cves c ON c.id = cw.cve_id
            LEFT JOIN mv_cve_scores cs ON cs.id = c.id
            WHERE t.technique_id = :tid
            ORDER BY cs.composite_score DESC NULLS LAST
            LIMIT 20
        """), {"tid": technique_id}).fetchall()

    if chain:
        lines.append("CVEs reachable via kill chain:")
        for r in chain:
            lines.append(f"  {r[4]} (score:{r[5] or 0}) via {r[2]} → {r[0]}")
    else:
        lines.append("No CVEs linked via the kill chain.")
    return "\n".join(lines)


@mcp.tool()
@track_usage
async def trending(entity_type: str = "cve", days: int = 7) -> str:
    """Entities with the biggest score changes in the given time window."""
    return f"Trending for {entity_type} (last {days} days) — use query() tool with snapshot tables for custom analysis."


@mcp.tool()
@track_usage
async def whats_new(days: int = 1) -> str:
    """Recent data updates from sync_log."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT sync_type, status, records_written, started_at, finished_at
            FROM sync_log
            WHERE started_at > now() - make_interval(days => :d)
            ORDER BY started_at DESC LIMIT 20
        """), {"d": days}).fetchall()
    if not rows:
        return f"No data updates in the last {days} day(s)."
    lines = [f"Recent updates (last {days} day(s)):\n"]
    for r in rows:
        lines.append(f"  {r[0]}: {r[1]} ({r[2]} records) at {r[3]}")
    return "\n".join(lines)


@mcp.tool()
@track_usage
async def query(sql: str) -> str:
    """Execute a read-only SQL query. Max 1000 rows, 5s timeout.

    Blocks INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER, GRANT, COPY,
    and other DDL/DML statements. Use for custom analysis.
    """
    if _BLOCKED_PATTERNS.search(sql):
        return "Error: query contains blocked SQL keywords. Read-only queries only."

    try:
        with readonly_engine.connect() as conn:
            result = conn.execution_options(timeout=5).execute(text(sql))
            rows = result.fetchmany(1000)
            columns = list(result.keys())

        if not rows:
            return "No results."

        lines = [" | ".join(columns)]
        lines.append("-" * len(lines[0]))
        for row in rows:
            lines.append(" | ".join(str(v) for v in row))
        lines.append(f"\n({len(rows)} rows)")
        return "\n".join(lines)
    except Exception as e:
        return f"Query error: {e}"
