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
    assert len(resp.json()["result"]["tools"]) >= 20


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
