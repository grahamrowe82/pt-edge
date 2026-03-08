"""Smoke tests — catch import errors and basic endpoint issues before deploy."""
import json
import pytest


def test_app_imports():
    """App module imports without crashing."""
    from app.main import app
    assert app is not None


def test_mcp_server_imports():
    """MCP server module imports without crashing."""
    from app.mcp.server import mount_mcp, _TOOLS, _tool_definitions
    assert len(_TOOLS) > 0


def test_hn_pulse_registered():
    """hn_pulse tool is registered in the tool list."""
    from app.mcp.server import _TOOLS
    assert "hn_pulse" in _TOOLS


def test_pitch_tools_registered():
    """Article pitch tools are registered."""
    from app.mcp.server import _TOOLS
    assert "propose_article" in _TOOLS
    assert "list_pitches" in _TOOLS
    assert "upvote_pitch" in _TOOLS


def test_amend_tools_registered():
    """Amendment tools are registered."""
    from app.mcp.server import _TOOLS
    assert "amend_correction" in _TOOLS
    assert "amend_pitch" in _TOOLS


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


# ---------------------------------------------------------------------------
# Query safety tests — validate SQL injection defenses
# ---------------------------------------------------------------------------

def _call_query(sql: str) -> dict:
    """Helper: call query() synchronously and parse the JSON result."""
    import asyncio
    from app.mcp.server import query, _tool_fn
    fn = _tool_fn(query)
    result = asyncio.run(fn(sql=sql))
    return json.loads(result)


class TestQuerySafety:
    """SQL validation blocks dangerous queries before they reach the DB."""

    def test_select_allowed(self):
        result = _call_query("SELECT 1 AS n")
        # May fail if no DB, but should NOT return a validation error
        if "error" in result:
            assert "forbidden" not in result["error"].lower()
            assert "only SELECT" not in result["error"]

    def test_drop_blocked(self):
        result = _call_query("SELECT 1; DROP TABLE projects")
        assert "error" in result

    def test_delete_blocked(self):
        result = _call_query("DELETE FROM projects")
        assert "error" in result

    def test_insert_blocked(self):
        result = _call_query("INSERT INTO projects (slug) VALUES ('evil')")
        assert "error" in result

    def test_update_blocked(self):
        result = _call_query("UPDATE projects SET slug = 'evil'")
        assert "error" in result

    def test_semicolon_stacked_blocked(self):
        result = _call_query("SELECT 1; SELECT 2")
        assert "error" in result
        assert "Multiple" in result["error"]

    def test_pg_read_file_blocked(self):
        result = _call_query("SELECT pg_read_file('/etc/passwd')")
        assert "error" in result

    def test_set_config_blocked(self):
        result = _call_query("SELECT set_config('log_statement', 'none', false)")
        assert "error" in result

    def test_copy_blocked(self):
        result = _call_query("COPY projects TO '/tmp/evil.csv'")
        assert "error" in result

    def test_trailing_semicolon_allowed(self):
        """A single trailing semicolon is fine — common in SQL editors."""
        result = _call_query("SELECT 1 AS n;")
        if "error" in result:
            assert "Multiple" not in result["error"]

    def test_cte_allowed(self):
        """WITH (CTEs) should be allowed — they're useful for analytics."""
        result = _call_query("WITH t AS (SELECT 1 AS n) SELECT * FROM t")
        if "error" in result:
            assert "only SELECT" not in result["error"]

    def test_comment_obfuscation_blocked(self):
        """Forbidden keywords hidden inside comments should still be caught."""
        result = _call_query("SELECT /* hello */ 1; DROP TABLE projects")
        assert "error" in result


class TestInputLimits:
    """Write tools enforce input length limits."""

    def test_correction_topic_limit(self):
        import asyncio
        from app.mcp.server import submit_correction, _tool_fn
        fn = _tool_fn(submit_correction)
        result = asyncio.run(fn(topic="x" * 301, correction="test"))
        assert "300" in result

    def test_correction_body_limit(self):
        import asyncio
        from app.mcp.server import submit_correction, _tool_fn
        fn = _tool_fn(submit_correction)
        result = asyncio.run(fn(topic="test", correction="x" * 5001))
        assert "5,000" in result

    def test_invalid_category_blocked(self):
        import asyncio
        from app.mcp.server import accept_candidate, _tool_fn
        fn = _tool_fn(accept_candidate)
        result = asyncio.run(fn(candidate_id=99999, category="evil_category"))
        assert "Invalid category" in result


# ---------------------------------------------------------------------------
# PR #25: Feedback rename + lab intelligence
# ---------------------------------------------------------------------------

def test_feedback_tools_registered():
    """New feedback tool names are registered."""
    from app.mcp.server import _TOOLS
    assert "submit_feedback" in _TOOLS
    assert "upvote_feedback" in _TOOLS
    assert "list_feedback" in _TOOLS
    assert "amend_feedback" in _TOOLS


def test_feedback_aliases_registered():
    """Old correction tool names still work as aliases."""
    from app.mcp.server import _TOOLS
    assert "submit_correction" in _TOOLS
    assert "upvote_correction" in _TOOLS
    assert "list_corrections" in _TOOLS
    assert "amend_correction" in _TOOLS


def test_lab_intelligence_tools_registered():
    """Lab intelligence tools are registered."""
    from app.mcp.server import _TOOLS
    assert "lab_models" in _TOOLS
    assert "submit_lab_event" in _TOOLS
    assert "list_lab_events" in _TOOLS


def test_new_models_import():
    """FrontierModel and LabEvent import without error."""
    from app.models import FrontierModel, LabEvent
    assert FrontierModel.__tablename__ == "frontier_models"
    assert LabEvent.__tablename__ == "lab_events"


# ---------------------------------------------------------------------------
# Docker Hub ingest
# ---------------------------------------------------------------------------

def test_dockerhub_ingest_imports():
    """Docker Hub ingest module imports without crashing."""
    from app.ingest.dockerhub import ingest_dockerhub, fetch_dockerhub_pulls
    assert callable(ingest_dockerhub)
    assert callable(fetch_dockerhub_pulls)


def test_docker_image_field():
    """Project model has docker_image attribute."""
    from app.models import Project
    assert hasattr(Project, "docker_image")


def test_dockerhub_in_runner():
    """Docker Hub ingest is registered in the runner pipeline."""
    import inspect
    from app.ingest import runner
    source = inspect.getsource(runner.run_all)
    assert "dockerhub" in source


# ---------------------------------------------------------------------------
# PR #26: V2EX ingest + Chinese lab coverage
# ---------------------------------------------------------------------------

def test_v2ex_post_import():
    """V2EXPost model imports and has correct tablename."""
    from app.models import V2EXPost
    assert V2EXPost.__tablename__ == "v2ex_posts"


def test_chinese_labs_in_aliases():
    """LAB_ALIASES includes Chinese lab entries."""
    from app.ingest.hn import LAB_ALIASES
    assert "deepseek" in LAB_ALIASES
    assert "qwen" in LAB_ALIASES
    assert "zhipu" in LAB_ALIASES
    assert LAB_ALIASES["deepseek"] == "deepseek"
    assert LAB_ALIASES["qwen"] == "qwen"
    assert LAB_ALIASES["zhipu"] == "zhipu-ai"


def test_chinese_labs_in_provider_map():
    """PROVIDER_TO_LAB includes Chinese lab OpenRouter prefixes."""
    from app.ingest.models import PROVIDER_TO_LAB
    assert "deepseek" in PROVIDER_TO_LAB
    assert "qwen" in PROVIDER_TO_LAB
    assert PROVIDER_TO_LAB["deepseek"] == "deepseek"
    assert PROVIDER_TO_LAB["qwen"] == "qwen"
