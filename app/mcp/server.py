"""PT-Edge MCP server — 8 tools (5 core + 3 domain-specific).

Core tools (schema discovery, SQL, feedback) come from app.core.mcp.server.
Domain tools (get_status, find_ai_tool, list_workflows) are registered here.
"""

import hmac
import json
import logging
from datetime import datetime, timezone

from app.api import core as _core
from app.core.api.core import _serialize
from app.core.mcp.server import (
    create_mcp_server,
    mount_mcp_transports,
    _tool_name,
    _tool_fn,
    _tool_definitions,
)
from app.core.mcp.tracking import track_usage
from app.settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Create MCP server with core tools
# ---------------------------------------------------------------------------

mcp = create_mcp_server("pt-edge", MCP_INSTRUCTIONS)

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_downloads(n: int) -> str:
    """Format download count: 1234567 -> '1.2M', 45000 -> '45K'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _freshness_indicator(dt) -> str:
    """Return freshness string like 'last push 3 months ago' with stale warning."""
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    try:
        delta = now - dt
    except TypeError:
        return ""
    months = delta.days // 30
    if months < 1:
        return "last push < 1 month ago"
    label = f"last push {months} month{'s' if months != 1 else ''} ago"
    return f"{label} [STALE]" if months > 12 else label


def _format_search_results(query: str, domain: str, results: list[dict], offset: int) -> str:
    """Format core.search_similar results as text for MCP output."""
    lines = []
    if domain:
        lines.append(f'AI REPO SEARCH: "{query}" (domain: {domain})')
    else:
        lines.append(f'AI REPO SEARCH: "{query}"')
    lines.append("=" * 50)

    for i, r in enumerate(results, offset + 1):
        dl = r.get("downloads_monthly") or 0
        dl_str = f" | {_fmt_downloads(dl)}/mo" if dl > 0 else ""
        lang = f" · {r['language']}" if r.get("language") else ""
        lic = f" · {r['license']}" if r.get("license") else ""
        sub = r.get("subcategory")
        if not domain:
            dom = f" [{r.get('domain')}/{sub}]" if sub else f" [{r.get('domain')}]"
        else:
            dom = f" [{sub}]" if sub else ""
        lines.append("")
        lines.append(
            f"{i}. {r['full_name']}{dom}  "
            f"(\u2b50 {r['stars']:,}{dl_str}{lang}{lic})"
        )
        if r.get("description"):
            lines.append(f"   {r['description'][:200]}")
        if r.get("topics"):
            lines.append(f"   Topics: {', '.join(r['topics'][:8])}")
        freshness = _freshness_indicator(
            datetime.fromisoformat(r["last_pushed_at"]) if r.get("last_pushed_at") else None
        )
        if freshness:
            lines.append(f"   {freshness}")
        lines.append(f"   https://github.com/{r['full_name']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Domain-specific tools (3)
# ---------------------------------------------------------------------------


@mcp.tool()
@track_usage
async def get_status() -> str:
    """Start here. Returns orientation: how many tables, repos, domains, and last sync time. Shows what data is available and how to explore it."""
    data = await _core.get_status()
    lines = [
        "PT-EDGE \u2014 AI Ecosystem Intelligence",
        "=" * 50,
        "",
        f"Tables: {data['tables']}",
        f"AI repos indexed: {data['ai_repos']:,}",
        "",
        "DOMAINS (repo count):",
    ]
    for d in data["domains"]:
        lines.append(f"  {d['name']:<30} {d['count']:,}")
    if data.get("last_sync"):
        lines.append(f"\nLast sync: {data['last_sync']['type']} at {data['last_sync']['at']}")
    lines.append("")
    lines.append(data["guidance"])
    return "\n".join(lines)


@mcp.tool()
@track_usage
async def find_ai_tool(query: str, domain: str = "", limit: int = 5, offset: int = 0) -> str:
    """Find AI/ML tools and libraries by describing what you need in plain English.
    Searches 220K+ indexed AI repos via semantic + keyword search.

    Optional domain filter: mcp, agents, ai-coding, rag, llm-tools, generative-ai,
    diffusion, voice-ai, nlp, computer-vision, embeddings, vector-db,
    prompt-engineering, transformers, mlops, data-engineering, ml-frameworks

    Examples:
      find_ai_tool("database query tool for postgres", domain="mcp")
      find_ai_tool("autonomous coding agent")
      find_ai_tool("PDF document chunking for RAG pipeline")
    """
    data = await _core.search_similar(query=query, domain=domain, limit=limit, offset=offset)
    if "error" in data:
        return data["error"]
    results = data.get("results", [])
    if not results:
        return data.get("message", f"No results for '{query}'.")
    return _format_search_results(query, domain, results, offset)


@mcp.tool()
@track_usage
async def list_workflows() -> str:
    """Show available SQL recipe workflows -- pre-built query templates for common questions. Adapt these to your needs or use query() for custom SQL."""
    workflows = await _core.list_workflows()
    if not workflows:
        return "No workflows available yet."
    lines = ["SQL RECIPE WORKFLOWS", "=" * 50, ""]
    current_cat = None
    for w in workflows:
        cat = (w.get("category") or "general").upper()
        if cat != current_cat:
            current_cat = cat
            lines.append(f"\u2500\u2500 {cat} \u2500\u2500")
        lines.append(f"  {w['name']}")
        lines.append(f"    {w['description']}")
        if w.get("parameters"):
            params = w["parameters"] if isinstance(w["parameters"], dict) else {}
            param_names = ", ".join(params.keys()) if params else ""
            if param_names:
                lines.append(f"    Parameters: {param_names}")
        lines.append(f"    SQL: {w['sql_template'][:120]}...")
        lines.append("")
    lines.append("Adapt these templates for query(). Example:")
    lines.append("  query(\"SELECT full_name, stars FROM ai_repos WHERE domain = 'mcp' ORDER BY stars DESC LIMIT 10\")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool registry — 8 tools total (5 core + 3 domain)
# ---------------------------------------------------------------------------

def _build_tool_registry():
    """Build tool list and lookup from the mcp instance.

    FastMCP >=2.x stores tools in _local_provider._components with keys
    like 'tool:<name>@'. We extract them into a flat name->tool dict.
    """
    tool_list = []
    tool_map = {}
    for key, component in mcp._local_provider._components.items():
        if key.startswith("tool:"):
            tool_list.append(component)
            tool_map[component.name] = component
    return tool_list, tool_map


_TOOL_LIST, _TOOLS = _build_tool_registry()

_CORE_TOOL_NAMES = {
    "get_status",
    "list_tables",
    "describe_table",
    "search_tables",
    "query",
    "list_workflows",
    "find_ai_tool",
    "submit_feedback",
}

# Public tools shown in tools/list (all 8)
_TOOL_LIST_PUBLIC = [t for t in _TOOL_LIST if _tool_name(t) in _CORE_TOOL_NAMES]

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _validate_mcp_token(token: str) -> bool:
    """Check if a token is valid for MCP access."""
    if not token:
        return False
    if hmac.compare_digest(token, settings.API_TOKEN):
        return True
    if token.startswith("pte_"):
        from app.api.auth import validate_api_key
        return validate_api_key(token) is not None
    return False


# ---------------------------------------------------------------------------
# Mount
# ---------------------------------------------------------------------------


def mount_mcp(app):
    """Mount the MCP server on a FastAPI app."""
    mount_mcp_transports(
        app=app,
        mcp=mcp,
        instructions=MCP_INSTRUCTIONS,
        validate_token_fn=_validate_mcp_token,
        tool_list_public=_TOOL_LIST_PUBLIC,
        tools_lookup=_TOOLS,
    )
