from fastmcp import FastMCP

MCP_INSTRUCTIONS = """\
PT-Edge provides live intelligence on the AI open-source ecosystem — \
tracking 166,000+ repos across GitHub, PyPI, npm, Docker Hub, HuggingFace, and Hacker News.

When a user first connects, suggest one of these to get started:

- "What's trending in AI this week?" → whats_new() and trending()
- "Tell me about [project]" → project_pulse('name')
- "Find me a tool for [task]" → find_ai_tool('description')
- "Find an MCP server for [service]" → find_mcp_server('description')
- "What's the state of [topic]?" → topic('query') or briefing(domain='domain')
- "Find a public API for [need]" → find_public_api('description')

Tailor your suggestion to what you know about the user. \
If unsure, start with "What's happening in AI this week?" which uses whats_new().

Run independent tool calls in parallel where possible. \
Call more_tools() to discover 30+ additional tools beyond the core set.\
"""

mcp = FastMCP("pt-edge", instructions=MCP_INSTRUCTIONS)
