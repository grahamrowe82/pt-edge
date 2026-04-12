"""MCP server instance for CyberEdge."""

from fastmcp import FastMCP

MCP_INSTRUCTIONS = """CyberEdge provides live intelligence on cybersecurity vulnerabilities — tracking 250,000+ CVEs, 50,000+ software products, 15,000+ vendors, 900+ weakness types, and 700+ attack techniques.

Start with about() for an overview, then use specific tools:
- cve_lookup(cve_id) for full CVE details with kill chain
- software_risk(name) for software vulnerability profiles
- vendor_profile(name) for vendor risk assessment
- find_exploited() for actively exploited CVEs
- weakness_analysis(cwe_id) for weakness profiles with attack patterns
- attack_chain(technique_id) for technique-to-CVE chain
- trending() for score movers
- query(sql) for custom read-only SQL queries

Use tools in parallel where possible for faster results."""

mcp = FastMCP("cyber-edge", instructions=MCP_INSTRUCTIONS)
