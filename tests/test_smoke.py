"""Smoke tests — catch import errors and basic endpoint issues before deploy."""
import pytest


def test_app_imports():
    """App module imports without crashing."""
    from app.main import app
    assert app is not None


def test_mcp_server_imports():
    """MCP server module imports without crashing."""
    from app.mcp.server import mount_mcp, _TOOLS, _tool_definitions
    assert len(_TOOLS) > 0


def test_tool_definitions_build():
    """Tool definitions build correctly for JSON-RPC endpoint."""
    from app.mcp.server import _tool_definitions
    defs = _tool_definitions()
    assert len(defs) >= 20  # we have ~25 tools

    for d in defs:
        assert "name" in d
        assert "description" in d
        assert "inputSchema" in d
        assert isinstance(d["name"], str)
        assert len(d["name"]) > 0
        assert isinstance(d["inputSchema"], dict)


def test_tool_handlers_callable():
    """Every registered tool has a callable handler."""
    from app.mcp.server import _TOOLS, _tool_fn
    for name, tool in _TOOLS.items():
        fn = _tool_fn(tool)
        assert callable(fn), f"Tool {name} handler is not callable"


def test_healthz():
    """Health check endpoint returns 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_mcp_initialize():
    """MCP initialize returns valid JSON-RPC response."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.settings import settings

    client = TestClient(app)
    resp = client.post(
        f"/mcp?token={settings.API_TOKEN}",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["serverInfo"]["name"] == "pt-edge"


def test_mcp_tools_list():
    """MCP tools/list returns all tools."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.settings import settings

    client = TestClient(app)
    resp = client.post(
        f"/mcp?token={settings.API_TOKEN}",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert resp.status_code == 200
    tools = resp.json()["result"]["tools"]
    assert len(tools) >= 20
    names = [t["name"] for t in tools]
    assert "scout" in names
    assert "deep_dive" in names


def test_mcp_unauthorized():
    """MCP endpoint rejects bad tokens."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/mcp?token=wrong",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert resp.status_code == 401
