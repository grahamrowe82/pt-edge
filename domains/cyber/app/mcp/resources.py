"""MCP static resources for CyberEdge."""

from sqlalchemy import text

from domains.cyber.app.db import readonly_engine
from domains.cyber.app.mcp.instance import mcp

RESOURCES = [
    {
        "uri": "resource://cyber-edge/methodology",
        "name": "Scoring Methodology",
        "description": "How CyberEdge scores vulnerabilities across 4 dimensions.",
    },
    {
        "uri": "resource://cyber-edge/coverage",
        "name": "Data Coverage",
        "description": "Current entity counts and data freshness.",
    },
]


@mcp.resource("resource://cyber-edge/methodology")
async def methodology() -> str:
    return """CyberEdge Scoring Methodology

Four dimensions, 25 points each, 0-100 composite. Higher score = higher risk.

Severity (0-25):
  CVSS base score mapped to 0-20, plus attack complexity and vector bonuses.
  Aggregated entities use max/top-5 of associated CVE severity scores, log-scaled.

Exploitability (0-25):
  EPSS probability (0-15, log-scaled) + CISA KEV flag (+5) + public exploit (+5).
  For aggregated entities, combined across associated CVEs.

Exposure (0-25):
  Affected product count (0-10, log-scaled) + vendor spread (0-10, log-scaled)
  + internet-facing heuristic (0-5).

Patch Availability (0-25, inverse — higher = worse):
  Starts at 25 (no patch = max risk). Fix exists: -15. Time since fix: -5.
  Vendor responsiveness: -5.

Quality tiers:
  critical-risk (70-100), high-risk (50-69), moderate-risk (30-49), low-risk (0-29)

Kill chain: CVE → CWE → CAPEC → ATT&CK
  Every CVE traces through weakness types to attack patterns to adversary techniques."""


@mcp.resource("resource://cyber-edge/coverage")
async def coverage() -> str:
    lines = ["CyberEdge Data Coverage\n"]
    with readonly_engine.connect() as conn:
        for table, label in [
            ("cves", "CVEs"), ("software", "Software Products"), ("vendors", "Vendors"),
            ("weaknesses", "Weaknesses (CWE)"), ("techniques", "Techniques (ATT&CK)"),
            ("attack_patterns", "Attack Patterns (CAPEC)"),
        ]:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            lines.append(f"  {label}: {count:,}")

        # Freshness
        latest = conn.execute(text("""
            SELECT sync_type, MAX(finished_at) AS last_sync
            FROM sync_log WHERE status = 'success'
            GROUP BY sync_type ORDER BY last_sync DESC
        """)).fetchall()
        if latest:
            lines.append("\nLast successful syncs:")
            for r in latest:
                lines.append(f"  {r[0]}: {r[1]}")
    return "\n".join(lines)
