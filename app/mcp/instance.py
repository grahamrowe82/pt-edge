from fastmcp import FastMCP

MCP_INSTRUCTIONS = """\
PT-Edge provides live intelligence on the AI open-source ecosystem — \
tracking 220,000+ repos across GitHub, PyPI, npm, Docker Hub, HuggingFace, \
and Hacker News.

Start with get_status() to see what data is available. Then explore:

1. get_status()          — orientation: tables, domains, freshness
2. list_tables()         — see all tables and row counts
3. describe_table(name)  — columns and types for a table
4. search_tables(keyword)— find tables by topic
5. query(sql)            — run any SELECT query (read-only, 5s timeout)
6. list_workflows()      — pre-built SQL recipes for common questions
7. find_ai_tool(query)   — semantic search across 220K+ AI repos
8. submit_feedback(...)  — report bugs, request features, share observations

Workflow: get_status → list_tables → describe_table → query. \
Use list_workflows() for ready-made query templates you can adapt. \
Use find_ai_tool() when you need semantic similarity search. \
Everything else is answerable via query() — compose SQL against the schema.\
"""

mcp = FastMCP("pt-edge", instructions=MCP_INSTRUCTIONS)
