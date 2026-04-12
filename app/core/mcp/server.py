"""Shared MCP scaffold: 5 core tools + transport mounting.

Domain code (app.mcp.server) adds domain-specific tools on top.
"""

import hashlib
import inspect
import json
import logging
import time
from collections import defaultdict

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastmcp import FastMCP
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.api.core import (
    run_query, list_tables, describe_table, search_tables,
    submit_feedback, _serialize,
)
from app.core.mcp.tracking import track_usage, set_request_context
from app.db import SessionLocal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter (per-IP, 60 requests/minute)
# ---------------------------------------------------------------------------

_RATE_LIMIT = 60
_RATE_WINDOW = 60
_rate_buckets: dict[str, list[float]] = defaultdict(list)

# ---------------------------------------------------------------------------
# JSON-RPC tool registry helpers
# ---------------------------------------------------------------------------

_PY_TO_JSON = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _tool_name(t) -> str:
    return getattr(t, "name", None) or t.__name__


def _tool_fn(t):
    return getattr(t, "fn", t)


def _tool_definitions(tools) -> list[dict]:
    """Build JSON-RPC tool definitions, using inspect as fallback for schemas."""
    defs = []
    for t in tools:
        name = _tool_name(t)
        fn = _tool_fn(t)

        schema = getattr(t, "parameters", None)
        if schema is None:
            sig = inspect.signature(fn)
            props = {}
            required = []
            for pname, param in sig.parameters.items():
                ann = param.annotation if param.annotation is not inspect.Parameter.empty else str
                prop = {"type": _PY_TO_JSON.get(ann, "string")}
                if param.default is inspect.Parameter.empty:
                    required.append(pname)
                elif param.default is not None:
                    prop["default"] = param.default
                props[pname] = prop
            schema = {"type": "object", "properties": props}
            if required:
                schema["required"] = required

        desc = getattr(t, "description", None) or (fn.__doc__ or "").strip()
        defs.append({"name": name, "description": desc, "inputSchema": schema})
    return defs


# ---------------------------------------------------------------------------
# Factory: create MCP server with 5 core tools
# ---------------------------------------------------------------------------

def create_mcp_server(name: str, instructions: str) -> FastMCP:
    """Create a FastMCP server with 5 generic tools pre-registered."""
    mcp = FastMCP(name, instructions=instructions)

    @mcp.tool(name="list_tables")
    @track_usage
    async def list_tables_tool() -> str:
        """List all database tables with row counts. Use before describe_table() or query()."""
        tables = await list_tables()
        lines = ["TABLES", "=" * 50, ""]
        for t in tables:
            lines.append(f"  {t['table_name']:<40} ~{t['row_estimate']:,} rows ({t['column_count']} cols)")
        lines.append(f"\n{len(tables)} tables. Use describe_table('name') for column details.")
        return "\n".join(lines)

    @mcp.tool(name="describe_table")
    @track_usage
    async def describe_table_tool(table_name: str) -> str:
        """Show columns, types, and row count for a specific table. Call before writing a query."""
        data = await describe_table(table_name)
        if data is None:
            return f"Table '{table_name}' not found. Use list_tables() to see available tables."
        lines = [
            f"TABLE: {data['table_name']}  (~{data['row_estimate']:,} rows)",
            "=" * 50,
            "",
        ]
        for c in data["columns"]:
            nullable = " (nullable)" if c["nullable"] else ""
            lines.append(f"  {c['name']:<30} {c['type']}{nullable}")
        return "\n".join(lines)

    @mcp.tool(name="search_tables")
    @track_usage
    async def search_tables_tool(keyword: str) -> str:
        """Find tables by keyword in table or column names. Use when you're not sure which table has the data you need."""
        tables = await search_tables(keyword)
        if not tables:
            return f"No tables matching '{keyword}'. Use list_tables() to see all tables."
        lines = [f"Tables matching '{keyword}':", ""]
        for t in tables:
            lines.append(f"  {t['table_name']}")
        lines.append(f"\nUse describe_table('name') for column details.")
        return "\n".join(lines)

    @mcp.tool(name="query")
    @track_usage
    async def query(sql: str) -> str:
        """Run a read-only SQL query against the database. Call list_tables() and describe_table() first to see available tables and columns. SELECT only, 5s timeout, 1000 row limit, JSON results.

        Examples:
          query("SELECT full_name, stars FROM ai_repos ORDER BY stars DESC LIMIT 10")
          query("SELECT domain, COUNT(*) FROM ai_repos GROUP BY domain ORDER BY 2 DESC")
        """
        result = await run_query(sql)
        if "error" in result:
            return json.dumps({"error": result["error"]})
        return json.dumps(result["rows"], default=_serialize)

    @mcp.tool(name="submit_feedback")
    @track_usage
    async def submit_feedback_tool(
        topic: str, correction: str, context: str = None, category: str = "observation"
    ) -> str:
        """Submit feedback about an AI topic or project.

        Categories: bug (broken/wrong data), feature (buildable thing), observation (strategic context), insight (analytical finding).
        Default 'observation' when unsure. All submissions are PUBLIC -- do not include sensitive data.
        """
        result = await submit_feedback(
            topic=topic.strip(),
            text_body=correction.strip(),
            context=context.strip() if context else None,
            category=category,
        )
        if "error" in result:
            return result["error"]
        return (
            f"Feedback submitted successfully.\n"
            f"  ID:       {result['id']}\n"
            f"  Topic:    {topic}\n"
            f"  Category: {category}\n"
            f"  Text:     {correction[:200]}\n\n"
            f"Others can upvote this with upvote_feedback({result['id']})."
        )

    return mcp


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Auth + rate limiting middleware for Streamable HTTP transport."""

    def __init__(self, app, validate_token_fn=None):
        super().__init__(app)
        self._validate = validate_token_fn or (lambda t: False)

    async def dispatch(self, request: Request, call_next):
        # Rate limit
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        bucket = _rate_buckets[ip]
        _rate_buckets[ip] = bucket = [t for t in bucket if now - t < _RATE_WINDOW]
        if len(bucket) >= _RATE_LIMIT:
            return Response(status_code=429, content="Rate limit exceeded")
        bucket.append(now)
        # Auth
        token = request.query_params.get("token", "")
        if not token:
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ") if auth.startswith("Bearer ") else ""
        if not self._validate(token):
            return Response(status_code=401, content="Unauthorized")
        # Set request context for tracking
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or ip
        user_agent = request.headers.get("User-Agent", "")
        session_key = hashlib.sha256(f"{client_ip}:{user_agent}".encode()).hexdigest()[:16]
        set_request_context(client_ip, user_agent, session_key)
        return await call_next(request)


# ---------------------------------------------------------------------------
# Protocol event logger
# ---------------------------------------------------------------------------

def _log_protocol_event(event_name: str, client_ip: str, user_agent: str):
    """Log MCP protocol events to tool_usage + api_usage."""
    try:
        from app.models import ToolUsage
        session = SessionLocal()
        ua = user_agent[:500] if user_agent and len(user_agent) > 500 else (user_agent or None)
        usage = ToolUsage(
            tool_name=event_name,
            params={},
            duration_ms=0,
            success=True,
            error_message=None,
            result_size=0,
            client_ip=client_ip or None,
            user_agent=ua,
        )
        session.add(usage)
        session.execute(text("""
            INSERT INTO api_usage
                (endpoint, params, duration_ms, status_code, transport, client_ip, user_agent)
            VALUES
                (:ep, CAST(:params AS jsonb), 0, 200, 'mcp', :ip, :ua)
        """), {
            "ep": f"mcp/{event_name}",
            "params": "{}",
            "ip": client_ip or None,
            "ua": ua,
        })
        session.commit()
        session.close()
    except Exception:
        logger.debug(f"Failed to log protocol event {event_name}", exc_info=True)


# ---------------------------------------------------------------------------
# Mount transports on a FastAPI app
# ---------------------------------------------------------------------------

def mount_mcp_transports(
    app,
    mcp: FastMCP,
    instructions: str,
    validate_token_fn,
    tool_list_public: list,
    tools_lookup: dict,
):
    """Mount JSON-RPC POST + Streamable HTTP transports on a FastAPI app.

    Parameters:
        app: FastAPI application
        mcp: FastMCP instance (for Streamable HTTP)
        instructions: MCP server instructions string
        validate_token_fn: callable(token: str) -> bool
        tool_list_public: tools to show in tools/list
        tools_lookup: all callable tools by name
    """

    def _check_token(request: Request):
        token = request.query_params.get("token", "")
        if not token:
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ") if auth.startswith("Bearer ") else ""
        if not validate_token_fn(token):
            return None
        return token

    # ---- JSON-RPC POST transport ----
    @app.post("/mcp")
    async def mcp_json_rpc(request: Request):
        """Simple JSON-RPC endpoint for Claude.ai web connector."""
        raw_ip = request.client.host if request.client else "unknown"
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or raw_ip
        user_agent = request.headers.get("User-Agent", "")
        session_key = hashlib.sha256(f"{client_ip}:{user_agent}".encode()).hexdigest()[:16]
        set_request_context(client_ip, user_agent, session_key)

        body = await request.json()
        method = body.get("method")
        params = body.get("params", {})
        req_id = body.get("id", 0)

        _PUBLIC_METHODS = {
            "initialize", "notifications/initialized",
            "tools/list",
        }

        if method not in _PUBLIC_METHODS:
            token = _check_token(request)
            if not token:
                return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        if method == "initialize":
            _log_protocol_event("mcp.initialize", client_ip, user_agent)
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "pt-edge", "version": "1.0.0"},
                    "instructions": instructions,
                },
            })

        if method == "tools/list":
            _log_protocol_event("mcp.tools_list", client_ip, user_agent)
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": _tool_definitions(tool_list_public)},
            })

        if method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            tool = tools_lookup.get(tool_name)
            if not tool:
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                        "isError": True,
                    },
                })
            try:
                result = await _tool_fn(tool)(**tool_args)
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": result}],
                        "isError": False,
                    },
                })
            except Exception as e:
                logger.exception(f"MCP tool {tool_name} failed: {e}")
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": "Internal error"}],
                        "isError": True,
                    },
                })

        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        })

    # ---- Streamable HTTP transport ----
    mcp_app = mcp.http_app(path="/stream")
    mcp_app.add_middleware(TokenAuthMiddleware, validate_token_fn=validate_token_fn)
    app.mount("/mcp", mcp_app)
    app.router.lifespan_context = mcp_app.router.lifespan_context
