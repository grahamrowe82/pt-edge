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
    """MCP tools/list returns core tools (not the full set)."""
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
    assert len(tools) == 13  # core tools only
    names = [t["name"] for t in tools]
    assert "about" in names
    assert "more_tools" in names
    assert "find_ai_tool" in names
    assert "recall" in names
    assert "workspace" in names


def test_mcp_unauthorized():
    """MCP endpoint rejects bad tokens for tool calls."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    # Discovery methods (initialize, tools/list) are public — no auth required.
    # Tool execution still requires a valid token.
    resp = client.post(
        "/mcp?token=wrong",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "about", "arguments": {}}},
    )
    assert resp.status_code == 401


def test_mcp_discovery_no_auth():
    """Discovery methods work without authentication."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    # initialize — no token at all
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["serverInfo"]["name"] == "pt-edge"

    # tools/list — bad token should still work
    resp = client.post(
        "/mcp?token=wrong",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["result"]["tools"]) == 13  # core tools only


def test_hidden_tools_still_callable():
    """Tools not in core list are still callable via JSON-RPC."""
    from app.mcp.server import _TOOLS, _CORE_TOOL_NAMES

    # Verify hidden tools exist in _TOOLS lookup
    assert "describe_schema" not in _CORE_TOOL_NAMES
    assert "describe_schema" in _TOOLS
    assert "hype_check" not in _CORE_TOOL_NAMES
    assert "hype_check" in _TOOLS

    # Verify more_tools is in core
    assert "more_tools" in _CORE_TOOL_NAMES
    assert "more_tools" in _TOOLS


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


# ---------------------------------------------------------------------------
# MCP Resources, Resource Templates, and Prompts
# ---------------------------------------------------------------------------

def test_prompts_list():
    """MCP prompts/list returns 4 prompts."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.settings import settings

    client = TestClient(app)
    resp = client.post(
        f"/mcp?token={settings.API_TOKEN}",
        json={"jsonrpc": "2.0", "id": 10, "method": "prompts/list"},
    )
    assert resp.status_code == 200
    prompts = resp.json()["result"]["prompts"]
    names = [p["name"] for p in prompts]
    assert "evaluate-technology" in names
    assert "build-something" in names
    assert "due-diligence" in names
    assert "weekly-briefing" in names


def test_resources_list():
    """MCP resources/list returns 3 static resources."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.settings import settings

    client = TestClient(app)
    resp = client.post(
        f"/mcp?token={settings.API_TOKEN}",
        json={"jsonrpc": "2.0", "id": 11, "method": "resources/list"},
    )
    assert resp.status_code == 200
    resources = resp.json()["result"]["resources"]
    uris = [r["uri"] for r in resources]
    assert "resource://pt-edge/methodology" in uris
    assert "resource://pt-edge/categories" in uris
    assert "resource://pt-edge/coverage" in uris


def test_resource_templates_list():
    """MCP resources/templates/list returns 3 templates."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.settings import settings

    client = TestClient(app)
    resp = client.post(
        f"/mcp?token={settings.API_TOKEN}",
        json={"jsonrpc": "2.0", "id": 12, "method": "resources/templates/list"},
    )
    assert resp.status_code == 200
    templates = resp.json()["result"]["resourceTemplates"]
    assert len(templates) == 3
    names = [t["name"] for t in templates]
    assert "project" in names
    assert "lab" in names
    assert "category" in names


def test_prompt_content_format():
    """prompts/get returns content as {type, text} object, not a plain string."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.settings import settings

    client = TestClient(app)
    resp = client.post(
        f"/mcp?token={settings.API_TOKEN}",
        json={
            "jsonrpc": "2.0", "id": 14, "method": "prompts/get",
            "params": {"name": "weekly-briefing", "arguments": {}},
        },
    )
    assert resp.status_code == 200
    messages = resp.json()["result"]["messages"]
    assert len(messages) >= 1
    for msg in messages:
        assert "role" in msg
        content = msg["content"]
        # MCP spec: content must be an object with type+text, not a plain string
        assert isinstance(content, dict), f"content must be object, got {type(content)}"
        assert content["type"] == "text"
        assert isinstance(content["text"], str)
        assert len(content["text"]) > 0


def test_resource_read_response_shape():
    """resources/read returns contents with uri + text fields (MCP spec)."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.settings import settings

    client = TestClient(app)
    resp = client.post(
        f"/mcp?token={settings.API_TOKEN}",
        json={
            "jsonrpc": "2.0", "id": 15, "method": "resources/read",
            "params": {"uri": "resource://pt-edge/categories"},
        },
    )
    assert resp.status_code == 200
    contents = resp.json()["result"]["contents"]
    assert len(contents) >= 1
    for item in contents:
        assert "uri" in item, "resources/read contents must include uri"
        assert isinstance(item["uri"], str)
        assert "text" in item, "resources/read contents must include text"
        assert isinstance(item["text"], str)
        assert len(item["text"]) > 0


def test_tool_input_schemas_valid():
    """Every tool inputSchema has type=object and properties (MCP spec)."""
    from app.mcp.server import _tool_definitions
    defs = _tool_definitions()
    for d in defs:
        schema = d["inputSchema"]
        assert schema.get("type") == "object", (
            f"Tool '{d['name']}' inputSchema.type must be 'object', got {schema.get('type')}"
        )
        assert "properties" in schema, (
            f"Tool '{d['name']}' inputSchema must have 'properties'"
        )


def test_resource_template_uri_format():
    """Resource template URIs use RFC 6570 {param} syntax, not :param."""
    import re
    from app.mcp.resources import RESOURCE_TEMPLATES
    for tmpl in RESOURCE_TEMPLATES:
        uri = tmpl["uriTemplate"]
        # Must contain at least one {param}
        assert re.search(r"\{\w+\}", uri), (
            f"Template '{tmpl['name']}' uriTemplate must use {{param}} syntax: {uri}"
        )
        # Must not contain Express-style :param
        assert not re.search(r":\w+", uri), (
            f"Template '{tmpl['name']}' uriTemplate must not use :param syntax: {uri}"
        )


def test_prompt_arguments_match_handlers():
    """PROMPTS argument names match the handler function signatures."""
    import inspect
    from app.mcp.prompts import PROMPTS, _PROMPT_HANDLERS

    for prompt_def in PROMPTS:
        name = prompt_def["name"]
        handler = _PROMPT_HANDLERS.get(name)
        assert handler is not None, f"Prompt '{name}' has no handler in _PROMPT_HANDLERS"

        # Get expected args from PROMPTS registry
        declared_args = {a["name"] for a in prompt_def.get("arguments", [])}
        # Get actual args from handler function signature (skip 'self')
        sig = inspect.signature(handler)
        actual_args = set(sig.parameters.keys())

        assert declared_args == actual_args, (
            f"Prompt '{name}' argument mismatch: "
            f"PROMPTS declares {declared_args}, handler accepts {actual_args}"
        )


def test_initialize_advertises_capabilities():
    """MCP initialize includes resources and prompts capabilities."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.settings import settings

    client = TestClient(app)
    resp = client.post(
        f"/mcp?token={settings.API_TOKEN}",
        json={"jsonrpc": "2.0", "id": 13, "method": "initialize"},
    )
    assert resp.status_code == 200
    caps = resp.json()["result"]["capabilities"]
    assert "resources" in caps
    assert "prompts" in caps


# ---------------------------------------------------------------------------
# Search improvements: name boost, freshness, pagination, npm discovery
# ---------------------------------------------------------------------------

class TestNameBoost:
    """_name_boost helper gives exact and substring bonuses."""

    def test_exact_match(self):
        from app.mcp.server import _name_boost
        score = _name_boost("fastapi", "fastapi")
        assert score == 0.15

    def test_substring(self):
        from app.mcp.server import _name_boost
        score = _name_boost("fast", "fastapi-server")
        assert score == 0.08

    def test_full_name_slash(self):
        from app.mcp.server import _name_boost
        score = _name_boost("langchain", "langchain-ai/langchain")
        assert score == 0.15

    def test_no_match(self):
        from app.mcp.server import _name_boost
        score = _name_boost("pytorch", "tensorflow")
        assert score == 0.0

    def test_none_fields(self):
        from app.mcp.server import _name_boost
        score = _name_boost("test", None, None)
        assert score == 0.0

    def test_empty_query(self):
        from app.mcp.server import _name_boost
        score = _name_boost("", "fastapi")
        assert score == 0.0


class TestFreshnessIndicator:
    """_freshness_indicator returns human-readable freshness strings."""

    def test_none_returns_empty(self):
        from app.mcp.server import _freshness_indicator
        assert _freshness_indicator(None) == ""

    def test_recent_push(self):
        from datetime import datetime, timezone, timedelta
        from app.mcp.server import _freshness_indicator
        recent = datetime.now(timezone.utc) - timedelta(days=10)
        result = _freshness_indicator(recent)
        assert "< 1 month" in result
        assert "[STALE]" not in result

    def test_stale_push(self):
        from datetime import datetime, timezone, timedelta
        from app.mcp.server import _freshness_indicator
        old = datetime.now(timezone.utc) - timedelta(days=400)
        result = _freshness_indicator(old)
        assert "[STALE]" in result
        assert "month" in result

    def test_moderate_age(self):
        from datetime import datetime, timezone, timedelta
        from app.mcp.server import _freshness_indicator
        moderate = datetime.now(timezone.utc) - timedelta(days=90)
        result = _freshness_indicator(moderate)
        assert "month" in result
        assert "[STALE]" not in result


def test_search_tools_have_offset_param():
    """All 5 search wrapper tools accept an offset parameter."""
    import inspect
    from app.mcp.server import (
        find_ai_tool, find_mcp_server, find_public_api,
        find_dataset, find_model, _tool_fn,
    )
    for tool in [find_ai_tool, find_mcp_server, find_public_api,
                 find_dataset, find_model]:
        fn = _tool_fn(tool)
        sig = inspect.signature(fn)
        assert "offset" in sig.parameters, (
            f"{fn.__name__} missing offset parameter"
        )
        assert sig.parameters["offset"].default == 0


def test_npm_mcp_ingest_imports():
    """npm MCP ingest module imports without crashing."""
    from app.ingest.npm_mcp import ingest_npm_mcp, _extract_github_slug
    assert callable(ingest_npm_mcp)
    assert callable(_extract_github_slug)


def test_npm_mcp_in_runner():
    """npm MCP ingest is registered in the runner pipeline."""
    import inspect
    from app.ingest import runner
    source = inspect.getsource(runner.run_all)
    assert "npm_mcp" in source


class TestExtractGithubSlug:
    """_extract_github_slug parses GitHub URLs correctly."""

    def test_https_url(self):
        from app.ingest.npm_mcp import _extract_github_slug
        assert _extract_github_slug("https://github.com/owner/repo") == "owner/repo"

    def test_ssh_url(self):
        from app.ingest.npm_mcp import _extract_github_slug
        assert _extract_github_slug("git@github.com:owner/repo.git") == "owner/repo"

    def test_url_with_hash(self):
        from app.ingest.npm_mcp import _extract_github_slug
        assert _extract_github_slug("https://github.com/owner/repo#readme") == "owner/repo"

    def test_none_input(self):
        from app.ingest.npm_mcp import _extract_github_slug
        assert _extract_github_slug(None) is None

    def test_non_github_url(self):
        from app.ingest.npm_mcp import _extract_github_slug
        assert _extract_github_slug("https://gitlab.com/owner/repo") is None


# ---------------------------------------------------------------------------
# Audit fix tests
# ---------------------------------------------------------------------------


class TestStripSummary:
    """_strip_summary cleans HTML/markdown artifacts from release summaries."""

    def test_removes_html_tags(self):
        from app.mcp.server import _strip_summary
        assert "<details>" not in _strip_summary("<details><summary>Changelog</summary></details>")

    def test_removes_markdown_headers(self):
        from app.mcp.server import _strip_summary
        result = _strip_summary("## Breaking Changes\nSome text")
        assert result.startswith("Breaking Changes")

    def test_removes_github_urls(self):
        from app.mcp.server import _strip_summary
        result = _strip_summary("Fixed bug https://github.com/owner/repo/issues/123 in parser")
        assert "github.com" not in result

    def test_truncates_at_sentence(self):
        from app.mcp.server import _strip_summary
        long_text = "First sentence. Second sentence. " + "x " * 100
        result = _strip_summary(long_text, max_len=120)
        assert len(result) <= 123  # allow for "..."

    def test_truncates_at_word_boundary(self):
        from app.mcp.server import _strip_summary
        long_text = "Word " * 50  # 250 chars
        result = _strip_summary(long_text, max_len=120)
        assert result.endswith("...")
        assert not result.rstrip("...").endswith("Wor")  # no mid-word cut

    def test_empty_input(self):
        from app.mcp.server import _strip_summary
        assert _strip_summary("") == ""
        assert _strip_summary(None) == ""

    def test_short_input_unchanged(self):
        from app.mcp.server import _strip_summary
        assert _strip_summary("Simple release note") == "Simple release note"


class TestFmtDeltaSafe:
    """_fmt_delta_safe shows — for missing baselines."""

    def test_no_baseline_returns_dash(self):
        from app.mcp.server import _fmt_delta_safe
        assert _fmt_delta_safe(100, False) == "—"

    def test_with_baseline_formats_delta(self):
        from app.mcp.server import _fmt_delta_safe
        assert _fmt_delta_safe(100, True) == "+100"

    def test_with_baseline_negative(self):
        from app.mcp.server import _fmt_delta_safe
        assert _fmt_delta_safe(-50, True) == "-50"


def test_describe_schema_has_exclusion_list():
    """describe_schema defines an exclusion list for system tables."""
    import app.mcp.server as srv
    # Read the source file to check for the exclusion list
    import pathlib
    src = pathlib.Path(srv.__file__).read_text()
    assert "pg_stat_statements" in src
    assert "alembic_version" in src
    assert "_exclude_tables" in src


# ---------------------------------------------------------------------------
# Builder tools with MCP status tracking
# ---------------------------------------------------------------------------


def test_builder_tool_model_import():
    """BuilderTool model imports and has correct tablename."""
    from app.models import BuilderTool
    assert BuilderTool.__tablename__ == "builder_tools"


def test_builder_tool_fields():
    """BuilderTool model has all required MCP status fields."""
    from app.models import BuilderTool
    for attr in ["slug", "name", "category", "mcp_status", "mcp_type",
                 "mcp_endpoint", "mcp_repo_slug", "mcp_npm_package",
                 "mcp_checked_at", "source", "source_ref"]:
        assert hasattr(BuilderTool, attr), f"BuilderTool missing {attr}"


def test_builder_tools_ingest_imports():
    """Builder tools ingest module imports without crashing."""
    from app.ingest.builder_tools import ingest_builder_tools, _CURATED_TOOLS
    assert callable(ingest_builder_tools)
    assert len(_CURATED_TOOLS) > 100


def test_builder_tools_in_runner():
    """Builder tools ingest is registered in the runner pipeline."""
    import inspect
    from app.ingest import runner
    source = inspect.getsource(runner.run_all)
    assert "builder_tools" in source


def test_mcp_coverage_registered():
    """mcp_coverage tool is registered in the tool list."""
    from app.mcp.server import _TOOLS
    assert "mcp_coverage" in _TOOLS


class TestCuratedTools:
    """Curated tool list has no duplicates and correct shape."""

    def test_no_duplicate_slugs(self):
        from app.ingest.builder_tools import _CURATED_TOOLS
        slugs = [t[0] for t in _CURATED_TOOLS]
        assert len(slugs) == len(set(slugs)), f"Duplicate slugs: {[s for s in slugs if slugs.count(s) > 1]}"

    def test_all_tuples_have_five_fields(self):
        from app.ingest.builder_tools import _CURATED_TOOLS
        for t in _CURATED_TOOLS:
            assert len(t) == 5, f"Bad tuple: {t}"

    def test_key_tools_present(self):
        from app.ingest.builder_tools import _CURATED_TOOLS
        slugs = {t[0] for t in _CURATED_TOOLS}
        for expected in ["stripe", "github", "aws", "supabase", "sentry", "render", "openai"]:
            assert expected in slugs, f"Missing key tool: {expected}"

    def test_categories_not_empty(self):
        from app.ingest.builder_tools import _CURATED_TOOLS
        for slug, name, cat, url, desc in _CURATED_TOOLS:
            assert cat, f"{slug} has empty category"


# ---------------------------------------------------------------------------
# Compact response + session workspace
# ---------------------------------------------------------------------------

class TestCompactResponse:
    """compact_response decorator truncates and saves to workspace."""

    def test_short_response_unchanged(self):
        import asyncio
        from app.mcp.tracking import compact_response

        @compact_response(100)
        async def short_tool():
            return "short"

        result = asyncio.run(short_tool())
        assert result == "short"

    def test_long_response_truncated(self):
        import asyncio
        from app.mcp.tracking import compact_response, _session_key

        token = _session_key.set("test-compact")
        try:
            @compact_response(100)
            async def long_tool():
                return "x" * 500

            result = asyncio.run(long_tool())
            assert len(result) < 500
            assert "truncated" in result
            assert "recall(" in result
        finally:
            _session_key.reset(token)

    def test_detail_full_bypasses_truncation(self):
        import asyncio
        from app.mcp.tracking import compact_response

        @compact_response(100)
        async def detailed_tool(detail=None):
            return "x" * 500

        result = asyncio.run(detailed_tool(detail="full"))
        assert len(result) == 500


class TestWorkspace:
    """Session workspace store/recall works correctly."""

    def test_store_and_recall(self):
        from app.mcp.tracking import (
            _workspace_store, _workspace_recall,
            _workspace_list, _session_key,
        )

        token = _session_key.set("test-workspace")
        try:
            _workspace_store("test_key", "test_value")
            assert _workspace_recall("test_key") == "test_value"
            keys = _workspace_list()
            assert "test_key" in keys
            assert keys["test_key"] == len("test_value")
        finally:
            _session_key.reset(token)

    def test_recall_without_session_returns_none(self):
        from app.mcp.tracking import _workspace_recall, _session_key

        token = _session_key.set("")
        try:
            assert _workspace_recall("anything") is None
        finally:
            _session_key.reset(token)

    def test_recall_tool_missing_key(self):
        """recall() tool returns helpful message for missing keys."""
        import asyncio
        from app.mcp.server import recall as recall_tool, _tool_fn
        from app.mcp.tracking import _session_key

        token = _session_key.set("test-recall")
        try:
            fn = _tool_fn(recall_tool)
            result = asyncio.run(fn(key="nonexistent"))
            assert "not found" in result.lower()
        finally:
            _session_key.reset(token)


def test_recall_and_workspace_in_core():
    """recall and workspace are in core tool names."""
    from app.mcp.server import _CORE_TOOL_NAMES, _TOOLS
    assert "recall" in _CORE_TOOL_NAMES
    assert "workspace" in _CORE_TOOL_NAMES
    assert "recall" in _TOOLS
    assert "workspace" in _TOOLS


# ---------------------------------------------------------------------------
# Briefings — persistent narrative layer
# ---------------------------------------------------------------------------

def test_briefing_tool_registered():
    """Briefing tool is registered in the tool list."""
    from app.mcp.server import _TOOLS
    assert "briefing" in _TOOLS


def test_briefing_in_core_tools():
    """Briefing tool is in core tools (visible to Claude.ai)."""
    from app.mcp.server import _CORE_TOOL_NAMES
    assert "briefing" in _CORE_TOOL_NAMES


def test_briefing_model_import():
    """Briefing model imports and has correct tablename."""
    from app.models import Briefing
    assert Briefing.__tablename__ == "briefings"


def test_briefing_model_fields():
    """Briefing model has all required fields."""
    from app.models import Briefing
    for attr in ["slug", "domain", "title", "summary", "detail",
                 "evidence", "source_article", "verified_at", "updated_at"]:
        assert hasattr(Briefing, attr), f"Briefing missing {attr}"


def test_core_tool_count():
    """Core tool list has expected count (13 after adding briefing)."""
    from app.mcp.server import _CORE_TOOL_NAMES
    assert len(_CORE_TOOL_NAMES) == 13


def test_briefing_seed_entries():
    """Briefing seed file has entries with required fields."""
    from app.briefings_seed import ENTRIES
    assert len(ENTRIES) >= 10
    for entry in ENTRIES:
        assert "slug" in entry
        assert "domain" in entry
        assert "title" in entry
        assert "summary" in entry
        assert "detail" in entry
        assert len(entry["slug"]) <= 100
        assert len(entry["title"]) <= 300


def test_build_briefing_text():
    """build_briefing_text produces valid embedding input."""
    from app.embeddings import build_briefing_text
    text = build_briefing_text(
        slug="test-slug",
        title="Test Title",
        summary="Test summary",
        domain="mcp",
    )
    assert "Test Title" in text
    assert "Test summary" in text
    assert "mcp" in text


# ---------------------------------------------------------------------------
# PR #60: Rate limiting, subcategory, crates.io, briefing refresh
# ---------------------------------------------------------------------------

class TestRateLimiter:
    """RateLimiter enforces minimum interval between calls."""

    def test_import(self):
        from app.ingest.rate_limit import RateLimiter, ANTHROPIC_LIMITER, OPENAI_LIMITER
        assert isinstance(ANTHROPIC_LIMITER, RateLimiter)
        assert isinstance(OPENAI_LIMITER, RateLimiter)

    def test_rpm_setting(self):
        from app.ingest.rate_limit import ANTHROPIC_LIMITER, OPENAI_LIMITER
        assert ANTHROPIC_LIMITER.rpm == 40
        assert OPENAI_LIMITER.rpm == 400

    def test_interval_calculation(self):
        from app.ingest.rate_limit import RateLimiter
        limiter = RateLimiter(rpm=60)
        assert limiter._interval == 1.0  # 60s / 60 = 1s

    def test_acquire_is_async(self):
        import asyncio
        from app.ingest.rate_limit import RateLimiter
        limiter = RateLimiter(rpm=6000)  # fast for testing
        asyncio.run(limiter.acquire())  # should not raise


class TestCrateDownloads:
    """Crate download helpers work correctly."""

    def test_fetch_crate_downloads_import(self):
        from app.ingest.downloads import fetch_crate_downloads
        assert callable(fetch_crate_downloads)

    def test_crate_candidates(self):
        from app.ingest.ai_repo_downloads import _crate_candidates
        candidates = _crate_candidates("my-tool-rs")
        assert "my-tool-rs" in candidates
        assert "my-tool" in candidates  # strip -rs suffix

    def test_crate_candidates_no_suffix(self):
        from app.ingest.ai_repo_downloads import _crate_candidates
        candidates = _crate_candidates("tokio")
        assert "tokio" in candidates

    def test_is_crate_candidate_rust(self):
        from app.ingest.ai_repo_downloads import _is_crate_candidate
        assert _is_crate_candidate("Rust", None)
        assert _is_crate_candidate("Rust", [])

    def test_is_crate_candidate_topics(self):
        from app.ingest.ai_repo_downloads import _is_crate_candidate
        assert _is_crate_candidate("Go", ["rust", "cli"])
        assert not _is_crate_candidate("Go", ["golang"])

    def test_crate_matches_repo(self):
        from app.ingest.ai_repo_downloads import _crate_matches_repo
        assert _crate_matches_repo(
            {"crate": {"repository": "https://github.com/tokio-rs/tokio"}},
            "tokio-rs", "tokio",
        )
        assert not _crate_matches_repo(
            {"crate": {"repository": "https://github.com/other/repo"}},
            "tokio-rs", "tokio",
        )


class TestSubcategoryClassifier:
    """MCP subcategory classifier assigns correct labels."""

    def test_classify_framework(self):
        from app.ingest.ai_repo_subcategory import _classify_mcp
        assert _classify_mcp("fastmcp", "MCP framework", None) == "framework"

    def test_classify_gateway(self):
        from app.ingest.ai_repo_subcategory import _classify_mcp
        assert _classify_mcp("mcp-gateway", "API gateway for MCP", None) == "gateway"

    def test_classify_transport(self):
        from app.ingest.ai_repo_subcategory import _classify_mcp
        assert _classify_mcp("mcp-sse-transport", "SSE transport layer", None) == "transport"

    def test_classify_ide(self):
        from app.ingest.ai_repo_subcategory import _classify_mcp
        assert _classify_mcp("mcp-vscode", "VSCode extension for MCP", None) == "ide"

    def test_classify_security(self):
        from app.ingest.ai_repo_subcategory import _classify_mcp
        assert _classify_mcp("mcp-auth", "OAuth provider for MCP", None) == "security"

    def test_classify_none_for_generic(self):
        from app.ingest.ai_repo_subcategory import _classify_mcp
        assert _classify_mcp("my-mcp-server", "A server for weather data", None) is None

    def test_topics_contribute(self):
        from app.ingest.ai_repo_subcategory import _classify_mcp
        result = _classify_mcp("my-tool", "generic description", ["testing", "mcp"])
        assert result == "testing"


def test_ai_repo_subcategory_field():
    """AIRepo model has subcategory attribute."""
    from app.models.content import AIRepo
    assert hasattr(AIRepo, "subcategory")


def test_ai_repo_crate_package_field():
    """AIRepo model has crate_package attribute."""
    from app.models.content import AIRepo
    assert hasattr(AIRepo, "crate_package")


def test_project_ai_repo_id_field():
    """Project model has ai_repo_id FK."""
    from app.models.core import Project
    assert hasattr(Project, "ai_repo_id")


def test_mv_ai_repo_ecosystem_in_refresh():
    """mv_ai_repo_ecosystem is in the views refresh list."""
    from app.views.refresh import VIEWS_IN_ORDER
    assert "mv_ai_repo_ecosystem" in VIEWS_IN_ORDER


def test_subcategory_in_runner():
    """Subcategory inference is wired into the runner."""
    import inspect
    from app.ingest import runner
    source = inspect.getsource(runner.run_all)
    assert "subcategory" in source
    assert "ingest_subcategories" in source


def test_briefing_refresh_in_runner():
    """Briefing evidence refresh is wired into the runner."""
    import inspect
    from app.ingest import runner
    source = inspect.getsource(runner.run_all)
    assert "briefing_refresh" in source
    assert "refresh_briefing_evidence" in source


def test_project_linking_in_runner():
    """Project ↔ ai_repos linking is wired into the runner."""
    import inspect
    from app.ingest import runner
    source = inspect.getsource(runner.run_all)
    assert "project_linking" in source
    assert "ai_repo_id" in source


def test_briefing_refresh_import():
    """Briefing refresh module imports without crashing."""
    from app.briefing_refresh import refresh_briefing_evidence
    assert callable(refresh_briefing_evidence)


def test_ai_repo_package_detect_import():
    """LLM package detection module imports without crashing."""
    from app.ingest.ai_repo_package_detect import detect_packages_llm
    assert callable(detect_packages_llm)


def test_ai_repo_package_detect_in_runner():
    """LLM package detection is wired into the runner."""
    import inspect
    from app.ingest import runner
    source = inspect.getsource(runner.run_all)
    assert "ai_repo_package_detect" in source
    assert "detect_packages_llm" in source


def test_rate_limiter_in_package_detect():
    """LLM package detection uses rate limiter."""
    import inspect
    from app.ingest import ai_repo_package_detect
    source = inspect.getsource(ai_repo_package_detect)
    assert "ANTHROPIC_LIMITER" in source


def test_rate_limiter_in_newsletters():
    """Newsletter ingest uses rate limiter."""
    import inspect
    from app.ingest import newsletters
    source = inspect.getsource(newsletters)
    assert "ANTHROPIC_LIMITER" in source


def test_rate_limiter_in_releases():
    """Release ingest uses rate limiter."""
    import inspect
    from app.ingest import releases
    source = inspect.getsource(releases)
    assert "ANTHROPIC_LIMITER" in source


def test_rate_limiter_in_embeddings():
    """Embeddings module uses rate limiter."""
    import inspect
    from app import embeddings
    source = inspect.getsource(embeddings)
    assert "OPENAI_LIMITER" in source


def test_runner_pipeline_order():
    """LLM-dependent jobs (releases, newsletters) come after non-LLM jobs."""
    import inspect
    from app.ingest import runner
    source = inspect.getsource(runner.run_all)
    # ai_repos now runs on its own weekly cron, not in the daily runner
    assert "ai_repos removed" in source, "ai_repos should be removed from daily runner"
    # releases and newsletters should appear after builder_tools in the source
    builder_tools_pos = source.index('"builder_tools"')
    releases_pos = source.index('"releases"')
    newsletters_pos = source.index('"newsletters"')
    assert releases_pos > builder_tools_pos, "releases should run after builder_tools"
    assert newsletters_pos > builder_tools_pos, "newsletters should run after builder_tools"


# ---------------------------------------------------------------------------
# LLM enrichment tasks — shared helper + 7 tasks
# ---------------------------------------------------------------------------

def test_llm_helper_import():
    """Shared LLM helper imports without crashing."""
    from app.ingest.llm import call_haiku, call_haiku_text
    assert callable(call_haiku)
    assert callable(call_haiku_text)


def test_llm_helper_uses_rate_limiter():
    """Shared LLM helper uses ANTHROPIC_LIMITER."""
    import inspect
    from app.ingest import llm
    source = inspect.getsource(llm)
    assert "ANTHROPIC_LIMITER" in source


def test_subcategory_llm_import():
    """LLM subcategory classification function imports."""
    from app.ingest.ai_repo_subcategory import classify_subcategory_llm
    assert callable(classify_subcategory_llm)


def test_subcategory_llm_in_runner():
    """LLM subcategory classification is wired into the runner."""
    import inspect
    from app.ingest import runner
    source = inspect.getsource(runner.run_all)
    assert "subcategory_llm" in source
    assert "classify_subcategory_llm" in source


def test_subcategory_llm_uses_call_haiku():
    """LLM subcategory classification uses shared LLM helper."""
    import inspect
    from app.ingest import ai_repo_subcategory
    source = inspect.getsource(ai_repo_subcategory)
    assert "call_haiku" in source


def test_hn_llm_match_import():
    """HN LLM matching module imports."""
    from app.ingest.hn_llm_match import match_hn_posts_llm
    assert callable(match_hn_posts_llm)


def test_hn_llm_match_in_runner():
    """HN LLM matching is wired into the runner."""
    import inspect
    from app.ingest import runner
    source = inspect.getsource(runner.run_all)
    assert "hn_llm_match" in source
    assert "match_hn_posts_llm" in source


def test_hn_llm_match_uses_call_haiku():
    """HN LLM matching uses shared LLM helper."""
    import inspect
    from app.ingest import hn_llm_match
    source = inspect.getsource(hn_llm_match)
    assert "call_haiku" in source


def test_candidate_category_llm():
    """Candidate auto-promotion uses LLM for category."""
    import inspect
    from app.ingest import candidates
    source = inspect.getsource(candidates)
    assert "call_haiku" in source or "_classify_category_llm" in source


def test_v2ex_llm_filter():
    """V2EX ingest has LLM AI content filter."""
    import inspect
    from app.ingest import v2ex
    source = inspect.getsource(v2ex)
    assert "_llm_ai_filter" in source


def test_builder_tools_llm_match():
    """Builder tools has LLM MCP matching fallback."""
    import inspect
    from app.ingest import builder_tools
    source = inspect.getsource(builder_tools)
    assert "call_haiku" in source or "_llm_match_mcp_repos" in source


def test_newsletter_llm_resolve():
    """Newsletter mention resolution has LLM fallback."""
    import inspect
    from app.ingest import newsletters
    source = inspect.getsource(newsletters)
    assert "_resolve_mentions_llm" in source


def test_hn_llm_match_after_regex_backfill():
    """HN LLM matching runs after regex-based backfill."""
    import inspect
    from app.ingest import runner
    source = inspect.getsource(runner.run_all)
    regex_pos = source.index("hn_lab_backfill")
    llm_pos = source.index("hn_llm_match")
    assert llm_pos > regex_pos, "hn_llm_match must run after regex backfill"


def test_subcategory_llm_after_regex():
    """LLM subcategory runs after regex subcategory."""
    import inspect
    from app.ingest import runner
    source = inspect.getsource(runner.run_all)
    regex_pos = source.index('"subcategory"')
    llm_pos = source.index('"subcategory_llm"')
    assert llm_pos > regex_pos, "subcategory_llm must run after regex pass"


# ---------------------------------------------------------------------------
# Anti-pattern guards — catch common mistakes before they reach production
# ---------------------------------------------------------------------------

def _ingest_modules() -> list[tuple[str, str]]:
    """Return (module_name, source) for all ingest modules."""
    import importlib
    import inspect
    import pkgutil
    import app.ingest as pkg
    results = []
    for info in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"app.ingest.{info.name}")
        results.append((info.name, inspect.getsource(mod)))
    return results


class TestAntiPatterns:
    """Source-level guards against common performance and security mistakes."""

    def test_no_executemany_in_ingest(self):
        """Bulk writes must use execute_values + temp table, not row-by-row.

        SQLAlchemy's conn.execute(text("UPDATE ..."), [list_of_dicts]) issues
        one round-trip per row. At typical remote DB latency that's ~5-10ms
        per row — 11K rows = minutes of wall-clock time. The correct pattern
        is psycopg2.extras.execute_values with a temp table and a single
        UPDATE ... FROM join.
        """
        import re
        pattern = re.compile(
            r'conn\.execute\(\s*text\(\s*["\']'          # conn.execute(text("
            r'(?:UPDATE|INSERT)\b'                        # UPDATE or INSERT
            r'[^)]*\)\s*,\s*\[',                          # ..."), [
            re.IGNORECASE | re.DOTALL,
        )
        for name, source in _ingest_modules():
            assert not pattern.search(source), (
                f"app/ingest/{name}.py uses row-by-row executemany "
                f"(conn.execute + list-of-dicts). Use execute_values + "
                f"temp table pattern instead."
            )

    def test_no_fstring_sql_writes(self):
        """Write queries must never use f-strings — SQL injection risk.

        text(f"SELECT ... {domain_filter}") is OK for read-only queries that
        interpolate trusted constants (e.g. WHERE clauses from code).
        But UPDATE/INSERT/DELETE with f-strings is never acceptable.
        """
        import re
        pattern = re.compile(
            r'text\(f["\']'                  # text(f" or text(f'
            r'[^"\']*'                        # any content
            r'(?:UPDATE|INSERT|DELETE)\b',    # contains a write keyword
            re.IGNORECASE,
        )
        for name, source in _ingest_modules():
            assert not pattern.search(source), (
                f"app/ingest/{name}.py uses f-string SQL with a write "
                f"statement (UPDATE/INSERT/DELETE). Use bind parameters."
            )

    def test_anthropic_calls_use_rate_limiter(self):
        """Any module calling the Anthropic API must use the rate limiter."""
        for name, source in _ingest_modules():
            if name in ("rate_limit", "llm"):
                continue
            uses_anthropic = (
                ("messages.create" in source and "anthropic" in source.lower())
                or "api.anthropic.com" in source
            )
            if uses_anthropic:
                has_limiter = (
                    "ANTHROPIC_LIMITER" in source
                    or "call_haiku" in source
                    or "call_haiku_text" in source
                )
                assert has_limiter, (
                    f"app/ingest/{name}.py calls the Anthropic API "
                    f"without ANTHROPIC_LIMITER or call_haiku helper."
                )

    def test_openai_calls_use_rate_limiter(self):
        """Any module calling the OpenAI API must import the rate limiter."""
        import inspect
        # Also check app/embeddings.py since it lives outside app/ingest/
        from app import embeddings
        source = inspect.getsource(embeddings)
        if "embeddings.create" in source:
            assert "OPENAI_LIMITER" in source, (
                "app/embeddings.py calls the OpenAI API "
                "without OPENAI_LIMITER. Import and await it."
            )

    def test_no_sleep_as_rate_limit(self):
        """Don't use bare asyncio.sleep() as a rate limiter substitute.

        sleep(60) or sleep(30) as a rate-limiting strategy is brittle and
        wasteful. Use the RateLimiter class instead. Short sleeps (< 5s)
        for API politeness between requests are fine. Sleeps near a 429
        check are also fine (backoff on rate-limit response).
        """
        import re
        pattern = re.compile(r'asyncio\.sleep\((\d+)\)')
        for name, source in _ingest_modules():
            if name == "rate_limit":
                continue
            for match in pattern.finditer(source):
                val = int(match.group(1))
                if val < 10:
                    continue
                # Check surrounding context (5 lines above and below)
                # to allow 429-backoff patterns
                ctx_start = max(0, source.rfind('\n', 0, max(0, match.start() - 300)))
                ctx_end = min(len(source), source.find('\n', match.end() + 300))
                context = source[ctx_start:ctx_end].lower()
                if "429" in context or "rate limit" in context or "rate-limit" in context or "backing off" in context:
                    continue
                line_start = source.rfind('\n', 0, match.start()) + 1
                line_end = source.find('\n', match.end())
                line = source[line_start:line_end].strip()
                assert False, (
                    f"app/ingest/{name}.py has asyncio.sleep({val}) that "
                    f"looks like a homebrew rate limiter. Use RateLimiter "
                    f"class instead. Line: {line}"
                )
