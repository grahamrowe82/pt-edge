"""MCP compound workflow prompts for CyberEdge."""

from domains.cyber.app.mcp.instance import mcp

PROMPTS = [
    {
        "name": "vulnerability-triage",
        "description": "Assess a CVE: severity, exploitability, exposure, patch status, and kill chain.",
        "arguments": [{"name": "cve_id", "description": "CVE identifier (e.g. CVE-2021-44228)", "required": True}],
    },
    {
        "name": "vendor-risk-assessment",
        "description": "Assess a vendor's vulnerability portfolio and patch responsiveness.",
        "arguments": [{"name": "vendor", "description": "Vendor name", "required": True}],
    },
    {
        "name": "attack-surface-analysis",
        "description": "Map a software product's attack surface through the kill chain.",
        "arguments": [{"name": "software", "description": "Software product name", "required": True}],
    },
]


@mcp.prompt()
async def vulnerability_triage(cve_id: str) -> str:
    return (
        f"Triage {cve_id} using these steps:\n\n"
        f"1. Use cve_lookup('{cve_id}') to get the full profile\n"
        f"2. Check the kill chain — which ATT&CK techniques does this enable?\n"
        f"3. Use find_exploited(kev_only=True) to see if it's in the CISA KEV catalog\n"
        f"4. Assess the scoring dimensions (severity, exploitability, exposure) and identify the biggest risk factor\n"
        f"5. Recommend immediate actions based on the triage results"
    )


@mcp.prompt()
async def vendor_risk_assessment(vendor: str) -> str:
    return (
        f"Assess vendor '{vendor}' using these steps:\n\n"
        f"1. Use vendor_profile('{vendor}') for the overall risk score\n"
        f"2. Use query() to find their top 10 CVEs by composite_score\n"
        f"3. Check which weakness types (CWEs) recur across their products\n"
        f"4. Compare active threat proportion vs exploit availability across their products\n"
        f"5. Summarize the vendor's risk profile with specific recommendations"
    )


@mcp.prompt()
async def attack_surface_analysis(software: str) -> str:
    return (
        f"Analyze the attack surface of '{software}' using these steps:\n\n"
        f"1. Use software_risk('{software}') for the overall risk score\n"
        f"2. Use query() to find CVEs affecting this software with their CWE classifications\n"
        f"3. Trace the kill chain: which CAPEC patterns and ATT&CK techniques apply?\n"
        f"4. Identify the most critical unpatched vulnerabilities\n"
        f"5. Recommend defensive actions based on the attack surface"
    )
