import difflib
import hmac
import json
import re
import logging
import time
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from itertools import groupby

from fastapi import Request, Response
from sqlalchemy import text, func
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.db import SessionLocal, engine, readonly_engine
from app.models import (
    Lab, Project, GitHubSnapshot, DownloadSnapshot,
    Release, HNPost, V2EXPost, Correction, ArticlePitch, SyncLog, Methodology, Briefing,
)
from app.mcp.tracking import track_usage
from app.settings import settings

logger = logging.getLogger(__name__)

from app.mcp.instance import mcp, MCP_INSTRUCTIONS

TIER_LABELS = {1: "Foundational", 2: "Major", 3: "Notable", 4: "Emerging"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(obj):
    """Convert non-JSON-serializable types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if hasattr(obj, "__float__"):
        return float(obj)
    return str(obj)


def _row_to_dict(row):
    """Convert a SQLAlchemy Row to a dict with serialized values."""
    d = dict(row._mapping)
    return {k: _serialize(v) if v is not None else None for k, v in d.items()}


def _fmt_number(n):
    """Format a number with comma separators."""
    if n is None:
        return "n/a"
    try:
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return str(n)


def _fmt_delta(n):
    """Format a delta with +/- prefix."""
    if n is None:
        return "n/a"
    try:
        n = int(n)
        return f"+{n:,}" if n >= 0 else f"{n:,}"
    except (ValueError, TypeError):
        return str(n)


def _fmt_delta_safe(delta, has_baseline):
    """Format a delta, showing — when there is no historical baseline."""
    if not has_baseline:
        return "—"
    return _fmt_delta(delta)


def _fmt_date(dt):
    """Format a datetime for display."""
    if dt is None:
        return "n/a"
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(dt, date):
        return dt.isoformat()
    return str(dt)


def _fmt_version(version):
    """Format a release version, avoiding double-v prefix and stripping monorepo package names."""
    if not version:
        return ""
    # Strip monorepo package prefix: "langchain==0.3.28" → "0.3.28"
    if "==" in version:
        version = version.split("==", 1)[1]
    elif "@" in version and not version.startswith("@"):
        version = version.split("@", 1)[1]
    version = version.lstrip("v")
    # Only prepend 'v' if it starts with a digit (a version number)
    # Avoids "vchart-1.9.9" for non-semver tags like "chart-1.9.9"
    if version and version[0].isdigit():
        return f"v{version}"
    return version


def _fmt_ratio(val):
    """Format a hype ratio with consistent precision."""
    if val is None:
        return "n/a"
    try:
        return f"{float(val):.4g}"
    except (ValueError, TypeError):
        return str(val)


def _fmt_tier(tier):
    """Format a tier number with label."""
    try:
        t = int(tier)
        return f"T{t} ({TIER_LABELS.get(t, '?')})"
    except (ValueError, TypeError):
        return "n/a"


def _safe_mv_query(conn, sql, params=None):
    """Execute a query against a materialized view, returning [] if it doesn't exist."""
    try:
        result = conn.execute(text(sql), params or {})
        return [_row_to_dict(r) for r in result]
    except Exception as e:
        if "does not exist" in str(e) or "relation" in str(e).lower():
            logger.debug(f"Materialized view not available: {e}")
            return []
        raise


async def _semantic_project_search(
    query_text: str, limit: int = 5,
) -> tuple[list[dict], str | None]:
    """Find projects by semantic similarity.

    Returns (results, error_reason).
    - results: [{slug, name, description, category, similarity}, ...]
    - error_reason: human-readable string if search couldn't run, else None
    """
    from app.embeddings import is_enabled, embed_one

    if not is_enabled():
        logger.warning("Semantic search skipped: OPENAI_API_KEY not set")
        return [], "OPENAI_API_KEY not configured on this server"

    vec = await embed_one(query_text)
    if vec is None:
        logger.warning("Semantic search skipped: embed_one() returned None (API call failed)")
        return [], "Embedding API call failed (check server logs for details)"

    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT slug, name, description, category,
                       1 - (embedding <=> :vec) AS similarity
                FROM projects
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> :vec
                LIMIT :limit
            """), {"vec": str(vec), "limit": limit}).fetchall()

            return [
                {
                    "slug": r._mapping["slug"],
                    "name": r._mapping["name"],
                    "description": r._mapping["description"],
                    "category": r._mapping["category"],
                    "similarity": round(float(r._mapping["similarity"]), 3),
                }
                for r in rows
            ], None
    except Exception as e:
        logger.error(f"Semantic search error: {e}")
        return [], f"Database query failed: {e}"


async def _find_project_or_suggest(session: Session, identifier: str) -> tuple[Project | None, list[str]]:
    """Find a project by slug or name. Returns (project, suggestions) with fuzzy + semantic fallback."""
    identifier = identifier.strip()
    # 1. Exact slug match
    project = session.query(Project).filter(
        func.lower(Project.slug) == identifier.lower()
    ).first()
    if project:
        return project, []
    # 2. Exact name match
    project = session.query(Project).filter(
        func.lower(Project.name) == identifier.lower()
    ).first()
    if project:
        return project, []
    # 3. Substring fallback
    matches = session.query(Project).filter(
        (Project.slug.ilike(f"%{identifier}%")) |
        (Project.name.ilike(f"%{identifier}%"))
    ).limit(5).all()
    if len(matches) == 1:
        return matches[0], []
    if matches:
        return None, [m.slug for m in matches]
    # 4. Edit-distance fallback for typos (e.g., "langchan" → "langchain")
    all_slugs = [r[0] for r in session.query(Project.slug).all()]
    close = difflib.get_close_matches(identifier.lower(), [s.lower() for s in all_slugs], n=3, cutoff=0.6)
    if close:
        matches = session.query(Project).filter(func.lower(Project.slug).in_(close)).all()
        if len(matches) == 1:
            return matches[0], []
        return None, [m.slug for m in matches]
    # 5. Semantic fallback — find conceptually related projects
    semantic, _err = await _semantic_project_search(identifier, limit=3)
    if semantic:
        if len(semantic) == 1:
            match = session.query(Project).filter(Project.slug == semantic[0]["slug"]).first()
            if match:
                return match, []
        return None, [s["slug"] for s in semantic]
    return None, []


def _find_lab_or_suggest(session: Session, identifier: str) -> tuple[Lab | None, list[str]]:
    """Find a lab by slug or name. Returns (lab, suggestions) with fuzzy fallback."""
    identifier = identifier.strip()
    lab = session.query(Lab).filter(
        func.lower(Lab.slug) == identifier.lower()
    ).first()
    if lab:
        return lab, []
    lab = session.query(Lab).filter(
        func.lower(Lab.name) == identifier.lower()
    ).first()
    if lab:
        return lab, []
    matches = session.query(Lab).filter(
        (Lab.slug.ilike(f"%{identifier}%")) |
        (Lab.name.ilike(f"%{identifier}%"))
    ).limit(5).all()
    if len(matches) == 1:
        return matches[0], []
    if matches:
        return None, [m.slug for m in matches]
    # Edit-distance fallback
    all_slugs = [r[0] for r in session.query(Lab.slug).all()]
    close = difflib.get_close_matches(identifier.lower(), [s.lower() for s in all_slugs], n=3, cutoff=0.6)
    if close:
        matches = session.query(Lab).filter(func.lower(Lab.slug).in_(close)).all()
        if len(matches) == 1:
            return matches[0], []
        return None, [m.slug for m in matches]
    return None, []


def _not_found_msg(entity_type, identifier, suggestions):
    """Build a helpful 'not found' message with suggestions."""
    msg = f"{entity_type} not found: '{identifier}'."
    if suggestions:
        msg += f" Did you mean: {', '.join(suggestions)}?"
    else:
        msg += " Use about() to see available tools, or query() to browse."
    return msg


def _bucket_interpretation(bucket):
    """Return substantive interpretation text for a hype bucket."""
    b = str(bucket).lower()
    if b == "hype":
        return (
            "GitHub tourism -- stars vastly exceed actual usage. This project "
            "gets bookmarked and admired but rarely installed. Common for viral "
            "demos, conceptual tools, and projects with great READMEs."
        )
    if b == "star_heavy":
        return (
            "More stars than monthly downloads. Interest outpaces adoption. "
            "Could be early-stage with growing mindshare, or a project people "
            "watch but haven't integrated yet."
        )
    if b == "balanced":
        return (
            "Healthy ratio -- stars and downloads roughly aligned. This project "
            "has both visibility and real-world usage."
        )
    if b == "quiet_adoption":
        return (
            "Invisible infrastructure -- heavily used but few stars. This is a "
            "workhorse dependency that gets pulled into production builds without "
            "the corresponding GitHub attention."
        )
    if b == "no_downloads":
        return (
            "No download data available. This project may be distributed as a "
            "binary, desktop app, or hosted service rather than a package."
        )
    return f"Bucket '{bucket}' -- interpret with context."


def _strip_summary(text: str, max_len: int = 120) -> str:
    """Clean HTML/markdown artifacts from release summaries and truncate at sentence boundary."""
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Remove markdown headers
    text = re.sub(r"#{1,6}\s+", "", text)
    # Remove raw GitHub URLs
    text = re.sub(r"https?://github\.com/\S+", "", text)
    # Remove markdown links but keep text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    # Truncate at last sentence boundary within max_len
    truncated = text[:max_len]
    last_period = truncated.rfind(". ")
    if last_period > max_len // 2:
        return truncated[:last_period + 1]
    # Fall back to word boundary
    last_space = truncated.rfind(" ")
    if last_space > max_len // 2:
        return truncated[:last_space] + "..."
    return truncated + "..."


def _group_releases(releases):
    """Group releases by project + 24h window. Returns list of display strings."""
    lines = []
    if not releases:
        lines.append("  No releases in this period.")
        return lines

    def _group_key(item):
        rel, proj_name, lab_name = item
        # Group by project name + date (24h window) instead of lab + minute
        day = rel.released_at.date() if rel.released_at else None
        return (proj_name or "", lab_name or "", day)

    sorted_releases = sorted(releases, key=_group_key)
    for key, group_iter in groupby(sorted_releases, _group_key):
        items = list(group_iter)
        proj_name, lab_name, day = key
        if len(items) >= 3:
            # Group as "Project: N releases" (collapses monorepo sub-packages and daily builds)
            first_rel = items[0][0]
            version = _fmt_version(first_rel.version)
            lab_label = f" ({lab_name})" if lab_name else ""
            proj_label = proj_name or "unknown"
            lines.append(
                f"  {_fmt_date(first_rel.released_at)}  "
                f"{proj_label}{lab_label}: {len(items)} releases{f' (latest {version})' if version else ''}"
            )
        else:
            for rel, proj_n, lab_n in items:
                proj_label = proj_n or "unknown"
                lab_label = f" ({lab_n})" if lab_n else ""
                version_label = f" {_fmt_version(rel.version)}" if rel.version else ""
                summary = f" -- {_strip_summary(rel.summary)}" if rel.summary else ""
                lines.append(
                    f"  {_fmt_date(rel.released_at)}  "
                    f"{proj_label}{lab_label}{version_label}{summary}"
                )
    return lines


# ---------------------------------------------------------------------------
# Tool 1: about
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def about() -> str:
    """Start here. Returns a guide to all PT-Edge capabilities — what data is available, which tools to use for which questions, and recommended workflows. Call this first to understand the full toolkit."""
    lines = [
        "PT-EDGE — AI Project Intelligence",
        "=" * 50,
        "",
        "Live intelligence on the AI open-source ecosystem. Tracks projects across",
        "GitHub, PyPI, npm, Docker Hub, HuggingFace, and Hacker News.",
        "",
    ]

    # Data coverage (most useful info first)
    try:
        session = SessionLocal()
        total = session.query(func.count(Project.id)).filter(Project.is_active == True).scalar() or 0
        snapshot_days = session.execute(text(
            "SELECT COUNT(DISTINCT snapshot_date) FROM github_snapshots"
        )).scalar() or 0
        ai_repos = session.execute(text(
            "SELECT COUNT(*) FROM ai_repos"
        )).scalar() or 0
        candidates = session.execute(text(
            "SELECT COUNT(*) FROM project_candidates WHERE status = 'pending'"
        )).scalar() or 0
        lines.extend([
            f"Projects tracked: {total} | Snapshot depth: {snapshot_days} days",
            f"AI repos indexed: {_fmt_number(ai_repos)} | Pending candidates: {candidates}",
            "",
        ])
        session.close()
    except Exception:
        pass

    lines.extend([
        "QUICK START",
        "-" * 30,
        "  whats_new()              — what shipped this week",
        "  trending()               — star growth acceleration",
        "  project_pulse('name')    — deep dive on a project",
        "  topic('MCP')             — ecosystem search by topic",
        "  find_ai_tool('query')    — search ~100K AI repos",
        "  find_mcp_server('query') — search MCP servers",
        "  find_public_api('query') — search ~2,500 REST APIs",
        "  briefing()               — curated ecosystem intelligence",
        "  query('SELECT ...')      — raw SQL",
        "",
        "Call more_tools() to see 30+ advanced tools for hype analysis,",
        "lifecycle tracking, lab intelligence, HuggingFace search, and more.",
        "",
        "SUGGESTED WORKFLOWS",
        "-" * 30,
        "",
        "Research a topic:",
        "  1. briefing(domain='mcp')   2. topic('MCP')",
        "  3. find_ai_tool('MCP')      4. project_pulse('name')",
        "",
        "Compare competitors:",
        "  1. compare('A, B, C')       2. hype_landscape(category='framework')",
        "",
        "Monitor the ecosystem:",
        "  1. whats_new()              2. trending()  3. radar()",
        "",
        # --- Below here will typically be truncated ---
        "KEY CONCEPTS",
        "-" * 30,
        "- Hype Ratio: stars / monthly downloads. High = tourism. Low = infrastructure.",
        "- Tiers: T1 Foundational (>10M dl), T2 Major (>100K), T3 Notable (>10K), T4 Emerging",
        "- Lifecycle: emerging → launching → growing → established → fading → dormant",
        "- Momentum: star and download deltas over 7d and 30d windows",
        "",
        "BEHAVIORAL NOTES",
        "-" * 30,
        "1. Run independent queries IN PARALLEL — don't wait for one before starting the next.",
        "2. Don't narrate each tool result. Run the full chain, synthesize once at the end.",
        "3. Use find_ai_tool() to discover things BEYOND your training cutoff.",
        "4. Look for SURPRISES — low stars but massive downloads, zero commits, newcomers outpacing.",
        "5. Use offset to paginate: find_ai_tool('MCP', offset=5) shows results 6-10.",
        "6. [STALE] markers = no push in >12 months. Factor into recommendations.",
        "",
        "COMPOUND QUERIES",
        "-" * 30,
        "",
        "Evaluate a technology:",
        "  compare('A,B,C,D,E') → hype_check('X') → find_model(name) → hn_pulse(name)",
        "",
        "Build something:",
        "  PARALLEL: find_ai_tool + find_public_api + find_model + find_dataset + find_mcp_server",
        "  THEN: get_api_spec → get_api_endpoints → get_dependencies",
        "",
        "Due diligence:",
        "  project_pulse → hype_check → related → find_dependents → hn_pulse",
        "",
        "MCP RESOURCES & PROMPTS",
        "-" * 30,
        "Resources: methodology, categories, coverage, project/{slug}, lab/{slug}, category/{cat}",
        "Prompts: evaluate-technology, build-something, due-diligence, weekly-briefing",
        "",
        "ONBOARDING",
        "-" * 30,
        "Reflect on what you know about the user from context. Share a tailored suggestion:",
        '  "Based on what I know about you, I\'d suggest we start with [tools] to [value]."',
        "Offer to share an anonymised onboarding summary via submit_feedback(category='onboarding').",
        "",
        "Built by Graham Rowe — Phase Transitions newsletter",
        "phasetransitionsai.substack.com | graham@phasetransitions.ai",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: more_tools (gateway to advanced tools)
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def more_tools() -> str:
    """Unlock 30+ advanced tools for hype analysis, lifecycle tracking, lab intelligence, HuggingFace model/dataset search, editorial curation, community feedback, and raw SQL queries. Call this to see the full catalog."""
    # Build descriptions from the hidden tools dynamically
    lines = [
        "ADVANCED PT-EDGE TOOLS",
        "=" * 60,
        "",
        "These tools are all available — call any of them by name.",
        "They are grouped by category below.",
        "",
    ]

    categories = [
        ("Knowledge & Query", [
            ("briefing", "Curated ecosystem intelligence — distilled findings with live data deltas"),
            ("explain", "Deep documentation on any PT-Edge metric, algorithm, or design decision"),
            ("describe_schema", "List all database tables with their columns and types"),
            ("query", "Run a read-only SQL query (SELECT only). Escape hatch for questions no pre-built tool covers"),
        ]),
        ("Intelligence — Projects", [
            ("compare", "Side-by-side comparison of 2-5 projects (comma-separated names)"),
            ("related", "Which tracked projects appear alongside this one in HN discussions"),
            ("deep_dive", "Full profile of any project or candidate using cached data"),
            ("lifecycle_map", "All projects grouped by lifecycle stage (emerging/growing/mature/fading). Filter by category or tier"),
            ("movers", "Biggest directional changes — projects accelerating or decelerating vs prior window"),
            ("market_map", "Category concentration, power law distribution, lab dominance"),
            ("radar", "What should you be paying attention to that isn't tracked yet"),
        ]),
        ("Intelligence — Labs", [
            ("lab_pulse", "What a specific AI lab is shipping. Comma-separate for cross-lab comparison"),
            ("lab_models", "Browse frontier models by lab — context windows, pricing, capabilities"),
            ("list_lab_events", "Browse lab events: launches, releases, API changes"),
            ("submit_lab_event", "Record a significant lab event that moved the practical frontier"),
        ]),
        ("Hype & Signals", [
            ("hype_check", "Stars vs downloads reality check for a project"),
            ("hype_landscape", "Top overhyped + top underrated projects, bulk comparison"),
            ("scout", "Rising projects ranked by stars/day — candidates and small tracked projects"),
            ("hn_pulse", "HN discourse intelligence — what the community is discussing"),
        ]),
        ("Traction & Velocity", [
            ("breakouts", "Small repos with explosive % growth — the breakout detector"),
            ("ecosystem_layer", "Explore an ecosystem layer — MCP gateways, perception tools, agent frameworks"),
        ]),
        ("Discovery — HuggingFace", [
            ("find_dataset", "Search ~42K HuggingFace datasets by description. Filter by task/language"),
            ("find_model", "Search ~18K HuggingFace models by description. Filter by task/library"),
        ]),
        ("Discovery — APIs & Dependencies", [
            ("get_api_spec", "Get OpenAPI spec overview for a public API (endpoints, auth, base URL)"),
            ("get_api_endpoints", "Get detailed endpoint schemas for code generation"),
            ("get_dependencies", "Dependency list for an indexed AI repo (PyPI/npm)"),
            ("find_dependents", "Reverse lookup — which indexed repos depend on a given package"),
        ]),
        ("Discovery — MCP Ecosystem", [
            ("mcp_coverage", "MCP adoption across developer tools — which categories have servers"),
            ("mcp_health",   "Quality score (0-100) for any MCP server — maintenance, adoption, maturity, community"),
        ]),
        ("Community Feedback", [
            ("submit_feedback", "Submit an observation, insight, bug report, or feature request"),
            ("upvote_feedback", "Upvote someone else's feedback"),
            ("list_feedback", "Browse practitioner feedback, filter by topic/status/category"),
            ("amend_feedback", "Append a note to existing feedback (e.g. flag duplicate)"),
        ]),
        ("Content Pitches", [
            ("propose_article", "Pitch an article idea for Phase Transitions newsletter"),
            ("list_pitches", "Browse community article pitches"),
            ("upvote_pitch", "Upvote an article pitch"),
            ("amend_pitch", "Append a note to an existing pitch"),
        ]),
    ]

    for cat_name, tools in categories:
        lines.append(f"── {cat_name} ──")
        for tool_name, desc in tools:
            lines.append(f"  {tool_name:24s} {desc}")
        lines.append("")

    lines.append("Call any tool above by name. Example: compare('langchain, llamaindex')")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 2: describe_schema
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def describe_schema() -> str:
    """List all database tables with their columns and types."""
    _exclude_tables = {
        "pg_stat_statements", "pg_stat_statements_info",
        "alembic_version", "sync_log",
    }

    sql = """
        SELECT c.table_name, c.column_name, c.data_type, c.is_nullable,
               c.udt_name
        FROM information_schema.columns c
        WHERE c.table_schema = 'public'
        ORDER BY c.table_name, c.ordinal_position
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql))
        tables: dict[str, list[str]] = {}
        for r in rows:
            m = r._mapping
            tname = m["table_name"]
            if tname in _exclude_tables:
                continue
            nullable = " (nullable)" if m["is_nullable"] == "YES" else ""
            dtype = m["data_type"]
            # Show vector dimension instead of generic USER-DEFINED
            if dtype == "USER-DEFINED" and m.get("udt_name") == "vector":
                dtype = "vector"
            col_line = f"  {m['column_name']:<30} {dtype}{nullable}"
            tables.setdefault(tname, []).append(col_line)

    lines = ["DATABASE SCHEMA", "=" * 40, ""]
    for tname in sorted(tables):
        lines.append(f"TABLE: {tname}")
        lines.extend(tables[tname])
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 3: query
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def query(sql: str) -> str:
    """Run a read-only SQL query against PT-Edge's database. Use when no pre-built tool answers the question. Call describe_schema (via more_tools) first to see available tables. SELECT only, 5s timeout, JSON results.

    Examples:
      query("SELECT name, stars FROM projects ORDER BY stars DESC LIMIT 10")
      query("SELECT COUNT(*) FROM projects WHERE category = 'framework'")
    """
    sql_stripped = sql.strip()

    # Block semicolons (no stacked queries)
    if ";" in sql_stripped.rstrip(";"):  # allow trailing semicolon only
        return json.dumps({"error": "Multiple statements not allowed."})
    sql_stripped = sql_stripped.rstrip(";").strip()

    # Strip SQL comments before validation to prevent obfuscation
    sql_clean = re.sub(r"/\*.*?\*/", " ", sql_stripped, flags=re.DOTALL)  # block comments
    sql_clean = re.sub(r"--[^\n]*", " ", sql_clean)  # line comments

    # Must start with SELECT (or WITH for CTEs)
    if not re.match(r"(?i)^\s*(SELECT|WITH)\b", sql_clean):
        return json.dumps({"error": "Only SELECT queries are allowed."})

    # Block dangerous keywords and Postgres admin functions
    forbidden = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE"
        r"|COPY|DO|CALL|EXECUTE"
        r"|pg_read_file|pg_write_file|pg_read_binary_file"
        r"|lo_import|lo_export|lo_get|lo_put"
        r"|set_config|pg_reload_conf|pg_terminate_backend)\b",
        re.IGNORECASE,
    )
    if forbidden.search(sql_clean):
        return json.dumps({"error": "Query contains forbidden keywords."})

    try:
        with readonly_engine.connect() as conn:
            # 5-second statement timeout — Postgres kills the query server-side
            conn.execute(text("SET LOCAL statement_timeout = '5000'"))
            result = conn.execute(text(sql_stripped))
            rows = [_row_to_dict(r) for r in result.fetchmany(1000)]
            return json.dumps(rows, default=_serialize)
    except Exception as e:
        err = str(e)[:1000]
        if "canceling statement" in err:
            return json.dumps({"error": "Query timed out (5 second limit)."})
        return json.dumps({"error": err})


# ---------------------------------------------------------------------------
# Tool 4: whats_new
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def whats_new(days: int = 7) -> str:
    """What shipped in the AI ecosystem this week? New releases, trending projects, and notable Hacker News discussion — all in one view.

    Examples:
      whats_new()        — last 7 days (default)
      whats_new(days=30) — last 30 days
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    lines = [f"WHAT'S NEW (last {days} days)", "=" * 40]

    session = SessionLocal()
    try:
        # --- Recent Releases (grouped) ---
        releases = (
            session.query(Release, Project.name.label("project_name"), Lab.name.label("lab_name"))
            .outerjoin(Project, Release.project_id == Project.id)
            .outerjoin(Lab, Release.lab_id == Lab.id)
            .filter(Release.released_at >= cutoff)
            .order_by(Release.released_at.desc())
            .limit(20)
            .all()
        )

        lines.append("")
        lines.append("RECENT RELEASES")
        lines.append("-" * 30)
        lines.extend(_group_releases(releases))

        # --- Trending Projects (from mv_momentum) ---
        lines.append("")
        lines.append("TRENDING PROJECTS (by star growth)")
        lines.append("-" * 30)
        try:
            with engine.connect() as conn:
                trending_rows = _safe_mv_query(conn, """
                    SELECT m.name, m.category, m.stars_now, m.stars_7d_delta,
                           m.stars_30d_delta, m.dl_monthly_now, m.dl_7d_delta,
                           m.has_7d_baseline,
                           COALESCE(t.tier, 4) AS tier
                    FROM mv_momentum m
                    LEFT JOIN mv_project_tier t ON m.project_id = t.project_id
                    WHERE m.stars_7d_delta IS NOT NULL
                    ORDER BY m.stars_7d_delta DESC
                    LIMIT 10
                """)
                if trending_rows:
                    for r in trending_rows:
                        has_baseline = r.get("has_7d_baseline", False)
                        tier_badge = f"[T{int(r.get('tier', 4))}] " if r.get('tier') else ""
                        lines.append(
                            f"  {tier_badge}{r['name']:<28} "
                            f"stars: {_fmt_number(r.get('stars_now'))} "
                            f"({_fmt_delta_safe(r.get('stars_7d_delta'), has_baseline)} 7d) "
                            f"downloads/mo: {_fmt_number(r.get('dl_monthly_now'))}"
                        )
                else:
                    lines.append("  Momentum data not yet available (materialized view may not exist).")
        except Exception as e:
            lines.append(f"  Could not query momentum data: {e}")

        # --- Notable HN Discussion ---
        lines.append("")
        lines.append("TOP HN DISCUSSION (unfiltered)")
        lines.append("-" * 30)
        hn_posts = (
            session.query(HNPost)
            .filter(HNPost.posted_at >= cutoff)
            .order_by(HNPost.points.desc())
            .limit(10)
            .all()
        )
        if hn_posts:
            for post in hn_posts:
                lines.append(
                    f"  {post.points:>5} pts  {post.num_comments:>4} comments  "
                    f"{post.title[:80]}"
                )
                if post.url:
                    lines.append(f"           {post.url}")
        else:
            lines.append("  No HN posts captured in this period.")

    finally:
        session.close()

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 5: project_pulse
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def project_pulse(project: str) -> str:
    """Get the full picture on an AI project — stars, downloads, momentum, commits, hype ratio, lifecycle stage, and HN mentions. Pass a project name or slug (e.g. 'langchain', 'ollama')."""
    session = SessionLocal()
    try:
        proj, suggestions = await _find_project_or_suggest(session, project)
        if not proj:
            return _not_found_msg("Project", project, suggestions)

        lab_name = proj.lab.name if proj.lab else "n/a"
        lines = [
            f"PROJECT PULSE: {proj.name}",
            "=" * 40,
            f"  Slug:        {proj.slug}",
            f"  Category:    {proj.category}",
            f"  Lab:         {lab_name}",
            f"  Description: {proj.description or 'n/a'}",
            f"  URL:         {proj.url or 'n/a'}",
            f"  GitHub:      {proj.github_owner}/{proj.github_repo}" if proj.github_owner else "  GitHub:      n/a",
            f"  PyPI:        {proj.pypi_package or 'n/a'}",
            f"  NPM:         {proj.npm_package or 'n/a'}",
            f"  Active:      {proj.is_active}",
            "",
        ]

        # Tier & Lifecycle
        lines.append("TIER & LIFECYCLE")
        lines.append("-" * 30)
        try:
            with engine.connect() as conn:
                tier_rows = _safe_mv_query(conn, """
                    SELECT tier, is_override FROM mv_project_tier WHERE project_id = :pid
                """, {"pid": proj.id})
                lc_rows = _safe_mv_query(conn, """
                    SELECT lifecycle_stage FROM mv_lifecycle WHERE project_id = :pid
                """, {"pid": proj.id})
                tier = tier_rows[0] if tier_rows else {}
                lc = lc_rows[0] if lc_rows else {}
                lines.extend([
                    f"  Tier:       {_fmt_tier(tier.get('tier'))}",
                    f"  Override:   {'Yes' if tier.get('is_override') else 'No'}",
                    f"  Lifecycle:  {lc.get('lifecycle_stage', 'n/a')}",
                    f"             explain('tier_system') / explain('lifecycle_stages') for methodology",
                ])
        except Exception:
            lines.append("  Tier/lifecycle data not yet available.")
        lines.append("")

        # Latest GitHub snapshot
        gh = (
            session.query(GitHubSnapshot)
            .filter(GitHubSnapshot.project_id == proj.id)
            .order_by(GitHubSnapshot.snapshot_date.desc())
            .first()
        )
        lines.append("GITHUB METRICS")
        lines.append("-" * 30)
        if gh:
            contributor_display = _fmt_number(gh.contributors)
            if gh.contributors is not None and gh.contributors <= 1 and gh.stars and gh.stars > 100:
                contributor_display = "unknown (API limit)"
            lines.extend([
                f"  Stars:         {_fmt_number(gh.stars)}",
                f"  Forks:         {_fmt_number(gh.forks)}",
                f"  Open Issues:   {_fmt_number(gh.open_issues)}",
                f"  Watchers:      {_fmt_number(gh.watchers)}",
                f"  Commits (30d): {_fmt_number(gh.commits_30d)}",
                f"  Contributors:  {contributor_display}",
                f"  Last Commit:   {_fmt_date(gh.last_commit_at)}",
                f"  License:       {gh.license or 'n/a'}",
                f"  Snapshot Date: {_fmt_date(gh.snapshot_date)}",
            ])
        else:
            lines.append("  No GitHub snapshots yet.")
        lines.append("")

        # Velocity profile from mv_velocity
        lines.append("VELOCITY PROFILE")
        lines.append("-" * 30)
        try:
            with engine.connect() as conn:
                vel = _safe_mv_query(conn, """
                    SELECT velocity_band, commits_per_contributor, development_pace,
                           cpc_is_capped
                    FROM mv_velocity WHERE project_id = :pid
                """, {"pid": proj.id})
                if vel:
                    v = vel[0]
                    cpc_display = f"{v.get('commits_per_contributor', 'n/a')}"
                    if v.get("cpc_is_capped"):
                        cpc_display += " (capped — 100+ contributors)"
                    lines.extend([
                        f"  Velocity Band:          {v.get('velocity_band', 'n/a')}",
                        f"  Commits/Contributor:    {cpc_display}",
                        f"  Development Pace:       {v.get('development_pace', 'n/a')}",
                    ])
                else:
                    lines.append("  Velocity data not yet available.")
        except Exception:
            lines.append("  Velocity data not yet available.")
        lines.append("")

        # Latest download snapshot
        dl = (
            session.query(DownloadSnapshot)
            .filter(DownloadSnapshot.project_id == proj.id)
            .order_by(DownloadSnapshot.snapshot_date.desc())
            .first()
        )
        lines.append("DOWNLOAD METRICS")
        lines.append("-" * 30)
        if dl:
            lines.extend([
                f"  Source:           {dl.source}",
                f"  Daily:           {_fmt_number(dl.downloads_daily)}",
                f"  Weekly:          {_fmt_number(dl.downloads_weekly)}",
                f"  Monthly:         {_fmt_number(dl.downloads_monthly)}",
                f"  Snapshot Date:   {_fmt_date(dl.snapshot_date)}",
            ])
        else:
            lines.append("  No download snapshots yet.")
        lines.append("")

        # Momentum from mv_momentum
        lines.append("MOMENTUM")
        lines.append("-" * 30)
        try:
            with engine.connect() as conn:
                momentum = _safe_mv_query(conn, """
                    SELECT stars_7d_delta, stars_30d_delta,
                           dl_7d_delta, dl_30d_delta,
                           dl_monthly_now, has_7d_baseline, has_30d_baseline
                    FROM mv_momentum
                    WHERE project_id = :pid
                """, {"pid": proj.id})
                if momentum:
                    m = momentum[0]
                    has_7d = m.get("has_7d_baseline", False)
                    has_30d = m.get("has_30d_baseline", False)
                    lines.extend([
                        f"  Stars 7d delta:       {_fmt_delta_safe(m.get('stars_7d_delta'), has_7d)}",
                        f"  Stars 30d delta:      {_fmt_delta_safe(m.get('stars_30d_delta'), has_30d)}",
                        f"  Downloads 7d delta:   {_fmt_delta_safe(m.get('dl_7d_delta'), has_7d)}",
                        f"  Downloads 30d delta:  {_fmt_delta_safe(m.get('dl_30d_delta'), has_30d)}",
                    ])
                else:
                    lines.append("  Momentum data not yet available.")
        except Exception:
            lines.append("  Momentum data not yet available.")
        lines.append("")

        # Hype ratio from mv_hype_ratio
        lines.append("HYPE CHECK")
        lines.append("-" * 30)
        try:
            with engine.connect() as conn:
                hype = _safe_mv_query(conn, """
                    SELECT stars, monthly_downloads, hype_ratio, hype_bucket
                    FROM mv_hype_ratio
                    WHERE project_id = :pid
                """, {"pid": proj.id})
                if hype:
                    h = hype[0]
                    lines.extend([
                        f"  Stars:              {_fmt_number(h.get('stars'))}",
                        f"  Monthly Downloads:  {_fmt_number(h.get('monthly_downloads'))}",
                        f"  Hype Ratio:         {_fmt_ratio(h.get('hype_ratio'))}",
                        f"  Bucket:             {h.get('hype_bucket', 'n/a')}",
                    ])
                else:
                    lines.append("  Hype data not yet available.")
        except Exception:
            lines.append("  Hype data not yet available.")
        lines.append("")

        # Download Trends from mv_download_trends
        lines.append("DOWNLOAD TRENDS")
        lines.append("-" * 30)
        try:
            with engine.connect() as conn:
                dl_trend = _safe_mv_query(conn, """
                    SELECT dl_weekly_now, dl_weekly_prev, dl_weekly_velocity,
                           dl_weekly_pct_change, dl_trend
                    FROM mv_download_trends WHERE project_id = :pid
                """, {"pid": proj.id})
                if dl_trend:
                    d = dl_trend[0]
                    lines.extend([
                        f"  Trend:         {d.get('dl_trend', 'n/a')}",
                        f"  This Week:     {_fmt_number(d.get('dl_weekly_now'))}",
                        f"  Last Week:     {_fmt_number(d.get('dl_weekly_prev'))}",
                        f"  WoW Change:    {_fmt_delta(d.get('dl_weekly_velocity'))} "
                        f"({d.get('dl_weekly_pct_change', 'n/a')}%)",
                    ])
                else:
                    lines.append("  No download trend data (project may not have a package).")
        except Exception:
            lines.append("  Download trend data not yet available.")
        lines.append("")

        # Traction Score from mv_traction_score
        lines.append("TRACTION SCORE")
        lines.append("-" * 30)
        try:
            with engine.connect() as conn:
                traction = _safe_mv_query(conn, """
                    SELECT traction_score, traction_bucket,
                           fork_score, adoption_score, dependency_score,
                           velocity_score, contributor_score, dl_trend
                    FROM mv_traction_score WHERE project_id = :pid
                """, {"pid": proj.id})
                if traction:
                    t = traction[0]
                    lines.extend([
                        f"  Score:        {t.get('traction_score', 'n/a')}/100",
                        f"  Bucket:       {t.get('traction_bucket', 'n/a')}",
                        f"  Breakdown:    fork={_fmt_ratio(t.get('fork_score'))}/20  "
                        f"adoption={_fmt_ratio(t.get('adoption_score'))}/25  "
                        f"deps={_fmt_ratio(t.get('dependency_score'))}/20  "
                        f"velocity={_fmt_ratio(t.get('velocity_score'))}/20  "
                        f"contributors={_fmt_ratio(t.get('contributor_score'))}/15",
                    ])
                else:
                    lines.append("  Traction data not yet available.")
        except Exception:
            lines.append("  Traction data not yet available.")
        lines.append("")

        # Dependency Influence
        lines.append("DEPENDENCY INFLUENCE")
        lines.append("-" * 30)
        try:
            with engine.connect() as conn:
                # Find this project's package names
                pkg_names = conn.execute(text("""
                    SELECT COALESCE(p2.pypi_package, '') AS pypi,
                           COALESCE(p2.npm_package, '') AS npm,
                           COALESCE(a.pypi_package, '') AS ar_pypi,
                           COALESCE(a.npm_package, '') AS ar_npm
                    FROM projects p2
                    LEFT JOIN ai_repos a ON a.id = p2.ai_repo_id
                    WHERE p2.id = :pid
                """), {"pid": proj.id}).fetchone()

                if pkg_names:
                    m = pkg_names._mapping
                    names = [n for n in [m['pypi'], m['npm'], m['ar_pypi'], m['ar_npm']] if n]
                    names = list(set(names))  # dedupe

                    if names:
                        placeholders = ", ".join(f":pkg{i}" for i in range(len(names)))
                        pkg_params = {f"pkg{i}": n for i, n in enumerate(names)}

                        dep_rows = conn.execute(text(f"""
                            SELECT d.dep_name, d.source, COUNT(*) AS cnt
                            FROM package_deps d
                            WHERE d.dep_name IN ({placeholders})
                            GROUP BY d.dep_name, d.source
                            ORDER BY cnt DESC
                        """), pkg_params).fetchall()

                        if dep_rows:
                            total = sum(r._mapping["cnt"] for r in dep_rows)
                            lines.append(f"  Indexed dependents: {total}")
                            for dr in dep_rows:
                                dm = dr._mapping
                                lines.append(f"    {dm['dep_name']} ({dm['source']}): {dm['cnt']} repos")

                            # Trend from dep_velocity_snapshots
                            trend_rows = conn.execute(text(f"""
                                SELECT dependent_count, snapshot_date
                                FROM dep_velocity_snapshots
                                WHERE dep_name IN ({placeholders})
                                ORDER BY snapshot_date DESC
                                LIMIT 5
                            """), pkg_params).fetchall()
                            if len(trend_rows) >= 2:
                                latest_cnt = trend_rows[0]._mapping["dependent_count"]
                                oldest_cnt = trend_rows[-1]._mapping["dependent_count"]
                                delta = latest_cnt - oldest_cnt
                                lines.append(f"  Trend: {'+' if delta >= 0 else ''}{delta} dependents "
                                             f"over {len(trend_rows)} snapshots")
                        else:
                            lines.append("  No downstream dependents indexed.")
                    else:
                        lines.append("  No package name associated with this project.")
                else:
                    lines.append("  No package data available.")
        except Exception:
            lines.append("  Dependency data not available.")
        lines.append("")

        # Last 5 releases
        releases = (
            session.query(Release)
            .filter(Release.project_id == proj.id)
            .order_by(Release.released_at.desc())
            .limit(5)
            .all()
        )
        lines.append("RECENT RELEASES (last 5)")
        lines.append("-" * 30)
        if releases:
            for rel in releases:
                version_label = _fmt_version(rel.version)
                summary = f" -- {rel.summary[:100]}" if rel.summary else ""
                lines.append(
                    f"  {_fmt_date(rel.released_at)}  {version_label:<12} "
                    f"{rel.title[:60]}{summary}"
                )
        else:
            lines.append("  No releases recorded.")
        lines.append("")

        # Recent HN posts
        hn_posts = (
            session.query(HNPost)
            .filter(HNPost.project_id == proj.id)
            .order_by(HNPost.posted_at.desc())
            .limit(5)
            .all()
        )
        lines.append("RECENT HN POSTS")
        lines.append("-" * 30)
        if hn_posts:
            for post in hn_posts:
                lines.append(
                    f"  {post.points:>5} pts  {post.num_comments:>4} comments  "
                    f"{_fmt_date(post.posted_at)}  {post.title[:70]}"
                )
        else:
            lines.append("  No HN posts linked to this project.")
        lines.append("")

        # LLM-generated brief
        try:
            with engine.connect() as conn:
                brief_rows = conn.execute(text("""
                    SELECT title, summary FROM project_briefs WHERE project_id = :pid
                """), {"pid": proj.id}).fetchall()
                if brief_rows:
                    b = brief_rows[0]._mapping
                    lines.insert(1, "")
                    lines.insert(2, f"INTELLIGENCE BRIEF: {b['title']}")
                    lines.insert(3, f"  {b['summary']}")
                    lines.insert(4, "")
        except Exception:
            pass  # Table may not exist yet

        # Active corrections
        corrections = (
            session.query(Correction)
            .filter(
                func.lower(Correction.topic).contains(proj.name.lower()),
                Correction.status == "active",
            )
            .order_by(Correction.submitted_at.desc())
            .limit(5)
            .all()
        )
        lines.append("ACTIVE CORRECTIONS")
        lines.append("-" * 30)
        if corrections:
            for c in corrections:
                lines.append(
                    f"  [{c.id}] {c.topic} (upvotes: {c.upvotes})"
                )
                lines.append(f"       {c.correction[:150]}")
        else:
            lines.append("  No active corrections for this project.")

    finally:
        session.close()

    return "\n".join(lines)


def _lab_compare(session: Session, lab_names: list[str]) -> str:
    """Compare multiple labs side-by-side."""
    labs = []
    for name in lab_names:
        lab_obj, suggestions = _find_lab_or_suggest(session, name)
        if not lab_obj:
            return _not_found_msg("Lab", name, suggestions)
        labs.append(lab_obj)

    display_names = [l.name for l in labs]
    col_width = max(len(n) for n in display_names) + 2
    col_width = max(col_width, 16)

    header = f"{'':24}" + "".join(f"{n:<{col_width}}" for n in display_names)
    lines = [
        f"LAB COMPARISON: {' vs '.join(display_names)}",
        "=" * len(header),
        header,
        "-" * len(header),
    ]

    # Project counts
    project_counts = []
    for l in labs:
        count = (
            session.query(Project)
            .filter(Project.lab_id == l.id, Project.is_active == True)
            .count()
        )
        project_counts.append(str(count))
    lines.append(f"{'Projects':24}" + "".join(f"{c:<{col_width}}" for c in project_counts))

    # Velocity from mv_lab_velocity
    try:
        with engine.connect() as conn:
            lab_ids = [l.id for l in labs]
            placeholders = ", ".join(f":l{i}" for i in range(len(lab_ids)))
            params = {f"l{i}": lid for i, lid in enumerate(lab_ids)}

            vel_rows = _safe_mv_query(conn, f"""
                SELECT lab_id, releases_30d, releases_90d,
                       avg_days_between_releases, is_accelerating
                FROM mv_lab_velocity
                WHERE lab_id IN ({placeholders})
            """, params)

            vel_by_id = {r["lab_id"]: r for r in vel_rows}

            def _vel_row(label, key, fmt=str):
                vals = []
                for l in labs:
                    v = vel_by_id.get(l.id, {})
                    val = v.get(key)
                    vals.append(fmt(val) if val is not None else "n/a")
                lines.append(f"{label:24}" + "".join(f"{v:<{col_width}}" for v in vals))

            _vel_row("Releases (30d)", "releases_30d", lambda v: str(int(v)))
            _vel_row("Releases (90d)", "releases_90d", lambda v: str(int(v)))
            _vel_row("Avg days between", "avg_days_between_releases", lambda v: f"{float(v):.0f}")

            # Enhanced acceleration display
            accel_vals = []
            for l in labs:
                v = vel_by_id.get(l.id, {})
                r30 = v.get("releases_30d")
                r90 = v.get("releases_90d")
                if r30 is not None and r90 is not None and int(r90) > 0:
                    avg_monthly = int(r90) / 3
                    accel_vals.append(f"{int(r30)} vs {avg_monthly:.0f}/mo")
                else:
                    accel_vals.append("n/a")
            lines.append(f"{'Velocity (30d vs avg)':24}" + "".join(f"{v:<{col_width}}" for v in accel_vals))

    except Exception:
        lines.append("  Velocity data not yet available.")

    # Recent releases timeline (interleaved)
    lines.append("")
    lines.append("RECENT RELEASES (combined timeline)")
    lines.append("-" * 40)
    try:
        lab_ids = [l.id for l in labs]
        lab_name_by_id = {l.id: l.name for l in labs}
        project_ids = [
            p.id for l in labs
            for p in session.query(Project).filter(
                Project.lab_id == l.id, Project.is_active == True
            ).all()
        ]

        releases = (
            session.query(Release, Project.name.label("project_name"), Release.lab_id)
            .outerjoin(Project, Release.project_id == Project.id)
            .filter(
                (Release.lab_id.in_(lab_ids)) |
                (Release.project_id.in_(project_ids) if project_ids else False)
            )
            .order_by(Release.released_at.desc())
            .limit(15)
            .all()
        )
        if releases:
            for rel, proj_name, lab_id in releases:
                lab_label = lab_name_by_id.get(lab_id, "?")
                lines.append(
                    f"  {_fmt_date(rel.released_at)}  [{lab_label}]  "
                    f"{proj_name or 'n/a':<20} {_fmt_version(rel.version)}"
                )
        else:
            lines.append("  No releases recorded.")
    except Exception as e:
        lines.append(f"  Could not query releases: {e}")

    # Key Events combined timeline (interleaved across labs)
    lines.append("")
    lines.append("KEY EVENTS (combined timeline)")
    lines.append("-" * 40)
    try:
        from app.models import LabEvent
        lab_ids = [l.id for l in labs]
        lab_name_by_id = {l.id: l.name for l in labs}
        events = (
            session.query(LabEvent)
            .filter(LabEvent.lab_id.in_(lab_ids))
            .order_by(LabEvent.event_date.desc())
            .limit(20)
            .all()
        )
        if events:
            for ev in events:
                date_str = ev.event_date.strftime("%Y-%m-%d") if ev.event_date else "n/a"
                lab_label = lab_name_by_id.get(ev.lab_id, "?")
                lines.append(f"  {date_str}  [{lab_label}]  [{ev.event_type}]  {ev.title}")
                if ev.summary:
                    lines.append(f"             {ev.summary[:100]}")
        else:
            lines.append("  No lab events recorded yet.")
    except Exception as e:
        lines.append(f"  Could not query lab events: {e}")

    # HN Discussion combined (interleaved across labs)
    lines.append("")
    lines.append("HN DISCUSSION (combined)")
    lines.append("-" * 40)
    try:
        lab_ids = [l.id for l in labs]
        lab_name_by_id = {l.id: l.name for l in labs}
        hn_posts = (
            session.query(HNPost)
            .filter(HNPost.lab_id.in_(lab_ids))
            .order_by(HNPost.posted_at.desc())
            .limit(15)
            .all()
        )
        if hn_posts:
            for post in hn_posts:
                lab_label = lab_name_by_id.get(post.lab_id, "?")
                lines.append(
                    f"  {_fmt_date(post.posted_at)}  [{lab_label}]  "
                    f"{post.title[:60]}  "
                    f"({post.points} pts, {post.num_comments} comments)"
                )
        else:
            lines.append("  No HN posts linked to these labs yet.")
    except Exception as e:
        lines.append(f"  Could not query HN posts: {e}")

    # V2EX Discussion combined (interleaved across labs)
    lines.append("")
    lines.append("V2EX DISCUSSION (Chinese dev community)")
    lines.append("-" * 40)
    try:
        lab_ids = [l.id for l in labs]
        lab_name_by_id = {l.id: l.name for l in labs}
        v2ex_posts = (
            session.query(V2EXPost)
            .filter(V2EXPost.lab_id.in_(lab_ids))
            .order_by(V2EXPost.posted_at.desc())
            .limit(15)
            .all()
        )
        if v2ex_posts:
            for post in v2ex_posts:
                lab_label = lab_name_by_id.get(post.lab_id, "?")
                lines.append(
                    f"  {_fmt_date(post.posted_at)}  [{lab_label}]  "
                    f"{post.title[:60]}  "
                    f"({post.replies} replies, /{post.node_name or '?'})"
                )
        else:
            lines.append("  No V2EX posts linked to these labs yet.")
    except Exception as e:
        lines.append(f"  Could not query V2EX posts: {e}")

    # Frontier Models comparison (flagship per lab)
    lines.append("")
    lines.append("FRONTIER MODELS (comparison)")
    lines.append("-" * 40)
    try:
        from app.models import FrontierModel
        lab_ids = [l.id for l in labs]
        lab_name_by_id = {l.id: l.name for l in labs}
        models = (
            session.query(FrontierModel)
            .filter(
                FrontierModel.lab_id.in_(lab_ids),
                FrontierModel.status == "active",
            )
            .order_by(FrontierModel.context_window.desc().nullslast())
            .all()
        )
        if models:
            # Group by lab, show top 3 per lab by context window
            from collections import defaultdict
            by_lab = defaultdict(list)
            for m in models:
                by_lab[m.lab_id].append(m)

            for l in labs:
                lab_models = by_lab.get(l.id, [])
                if lab_models:
                    lines.append(f"  {l.name}:")
                    for m in lab_models[:3]:
                        ctx = f"{m.context_window:,}tok" if m.context_window else "n/a"
                        pricing = ""
                        if m.pricing_input and m.pricing_output:
                            pricing = f"{m.pricing_input} / {m.pricing_output}"
                        elif not m.pricing_input:
                            pricing = "(open weights)"
                        lines.append(f"    {m.name:<30} {ctx:<16} {pricing}")
        else:
            lines.append("  No frontier models recorded.")
    except Exception as e:
        lines.append(f"  Could not query models: {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 6: lab_pulse
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def lab_pulse(lab: str) -> str:
    """What is a specific lab shipping? Accepts slug or name.

    Pass comma-separated names for cross-lab comparison (e.g. 'openai, anthropic, meta').
    """
    session = SessionLocal()
    try:
        # Cross-lab comparison mode
        lab_names = [n.strip() for n in lab.split(",")]
        if len(lab_names) > 1:
            return _lab_compare(session, lab_names)

        lab_obj, suggestions = _find_lab_or_suggest(session, lab)
        if not lab_obj:
            return _not_found_msg("Lab", lab, suggestions)

        lines = [
            f"LAB PULSE: {lab_obj.name}",
            "=" * 40,
            f"  Slug:       {lab_obj.slug}",
            f"  URL:        {lab_obj.url or 'n/a'}",
            f"  Blog:       {lab_obj.blog_url or 'n/a'}",
            f"  GitHub Org: {lab_obj.github_org or 'n/a'}",
            "",
        ]

        # Projects with latest metrics
        all_projects = (
            session.query(Project)
            .filter(Project.lab_id == lab_obj.id, Project.is_active == True)
            .order_by(Project.name)
            .all()
        )
        total_projects = len(all_projects)
        projects = all_projects[:15]

        header = f"PROJECTS ({total_projects} active)"
        if total_projects > 15:
            header += f" — showing 15 of {total_projects}"
        lines.append(header)
        lines.append("-" * 30)
        for p in projects:
            gh = (
                session.query(GitHubSnapshot)
                .filter(GitHubSnapshot.project_id == p.id)
                .order_by(GitHubSnapshot.snapshot_date.desc())
                .first()
            )
            dl = (
                session.query(DownloadSnapshot)
                .filter(DownloadSnapshot.project_id == p.id)
                .order_by(DownloadSnapshot.snapshot_date.desc())
                .first()
            )
            stars = _fmt_number(gh.stars) if gh else "n/a"
            downloads = _fmt_number(dl.downloads_monthly) if dl else "n/a"
            lines.append(
                f"  {p.name:<30} [{p.category}]  "
                f"stars: {stars}  downloads/mo: {downloads}"
            )
        if not projects:
            lines.append("  No active projects recorded for this lab.")
        lines.append("")

        # Recent releases across all lab projects
        project_ids = [p.id for p in projects]
        releases_query = (
            session.query(Release, Project.name.label("project_name"))
            .outerjoin(Project, Release.project_id == Project.id)
            .filter(
                (Release.lab_id == lab_obj.id) |
                (Release.project_id.in_(project_ids) if project_ids else False)
            )
            .order_by(Release.released_at.desc())
            .limit(5)
        )
        releases = releases_query.all()

        lines.append("RECENT RELEASES (latest 5)")
        lines.append("-" * 30)
        if releases:
            for rel, proj_name in releases:
                version_label = _fmt_version(rel.version)
                lines.append(
                    f"  {_fmt_date(rel.released_at)}  {proj_name or 'n/a':<20} "
                    f"{version_label:<12} {rel.title[:60]}"
                )
        else:
            lines.append("  No releases recorded for this lab.")
        lines.append("")

        # Lab velocity from mv_lab_velocity
        lines.append("RELEASE VELOCITY")
        lines.append("-" * 30)
        try:
            with engine.connect() as conn:
                velocity = _safe_mv_query(conn, """
                    SELECT releases_30d, releases_90d,
                           avg_days_between_releases, is_accelerating
                    FROM mv_lab_velocity
                    WHERE lab_id = :lid
                """, {"lid": lab_obj.id})
                if velocity:
                    v = velocity[0]
                    r30 = v.get("releases_30d")
                    r90 = v.get("releases_90d")
                    accel = "Yes" if v.get("is_accelerating") else "No"
                    velocity_detail = ""
                    if r30 is not None and r90 is not None and int(r90) > 0:
                        avg_monthly = int(r90) / 3
                        velocity_detail = f" ({int(r30)} in 30d vs {avg_monthly:.0f}/mo avg in 90d)"
                    lines.extend([
                        f"  Releases (30d):             {r30 or 'n/a'}",
                        f"  Releases (90d):             {r90 or 'n/a'}",
                        f"  Avg days between releases:  {v.get('avg_days_between_releases', 'n/a')}",
                        f"  Accelerating:               {accel}{velocity_detail}",
                    ])
                else:
                    lines.append("  Velocity data not yet available.")
        except Exception:
            lines.append("  Velocity data not yet available.")

        # Recent HN discussion about this lab
        lines.append("")
        lines.append("RECENT HN DISCUSSION")
        lines.append("-" * 30)
        try:
            hn_posts = (
                session.query(HNPost)
                .filter(HNPost.lab_id == lab_obj.id)
                .order_by(HNPost.posted_at.desc())
                .limit(5)
                .all()
            )
            if hn_posts:
                for post in hn_posts:
                    lines.append(
                        f"  {_fmt_date(post.posted_at)}  "
                        f"{post.title[:70]}  "
                        f"({post.points} pts, {post.num_comments} comments)"
                    )
            else:
                lines.append("  No HN posts linked to this lab yet.")
        except Exception as e:
            lines.append(f"  Could not query HN posts: {e}")

        # V2EX discussion (Chinese dev community)
        lines.append("")
        lines.append("V2EX DISCUSSION (Chinese dev community)")
        lines.append("-" * 30)
        try:
            v2ex_posts = (
                session.query(V2EXPost)
                .filter(V2EXPost.lab_id == lab_obj.id)
                .order_by(V2EXPost.posted_at.desc())
                .limit(3)
                .all()
            )
            if v2ex_posts:
                for post in v2ex_posts:
                    lines.append(
                        f"  {_fmt_date(post.posted_at)}  "
                        f"{post.title[:70]}  "
                        f"({post.replies} replies, /{post.node_name or '?'})"
                    )
            else:
                lines.append("  No V2EX posts linked to this lab yet.")
        except Exception as e:
            lines.append(f"  Could not query V2EX posts: {e}")

        # Key lab events (curated intelligence)
        lines.append("")
        lines.append("KEY EVENTS")
        lines.append("-" * 30)
        try:
            from app.models import LabEvent
            events = (
                session.query(LabEvent)
                .filter(LabEvent.lab_id == lab_obj.id)
                .order_by(LabEvent.event_date.desc())
                .limit(10)
                .all()
            )
            if events:
                for ev in events:
                    date_str = ev.event_date.strftime("%Y-%m-%d") if ev.event_date else "n/a"
                    lines.append(f"  {date_str}  [{ev.event_type}]  {ev.title}")
                    if ev.summary:
                        lines.append(f"             {ev.summary[:100]}")
            else:
                lines.append("  No lab events recorded yet. Use submit_lab_event() to curate.")
        except Exception:
            lines.append("  Lab events data not yet available.")

        # Frontier models (capped to top 5 by context window)
        lines.append("")
        lines.append("FRONTIER MODELS")
        lines.append("-" * 30)
        try:
            from app.models import FrontierModel
            models = (
                session.query(FrontierModel)
                .filter(
                    FrontierModel.lab_id == lab_obj.id,
                    FrontierModel.status == "active",
                )
                .order_by(FrontierModel.context_window.desc().nullslast(), FrontierModel.name)
                .all()
            )
            if models:
                display_models = models[:5]
                for model in display_models:
                    ctx = f"{model.context_window:,}tok" if model.context_window else "n/a"
                    pricing = ""
                    if model.pricing_input and model.pricing_output:
                        pricing = f"  {model.pricing_input} / {model.pricing_output}"
                    elif not model.pricing_input:
                        pricing = "  (open weights)"
                    lines.append(f"  {model.name:<30} ctx: {ctx:<14}{pricing}")
                if len(models) > 5:
                    lines.append(f"  ... {len(models) - 5} more. Use lab_models('{lab_obj.slug}') for full catalog.")
            else:
                lines.append("  No frontier models recorded. Run model ingest to populate.")
        except Exception:
            lines.append("  Model data not yet available.")

    finally:
        session.close()

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 7: trending
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def trending(category: str = None, window: str = "7d") -> str:
    """What's accelerating right now? Top 20 AI projects by GitHub star growth over the last 7 or 30 days. Filter by category.

    Examples:
      trending()                        — top 20 by 7-day star growth
      trending(category='framework')    — filter to frameworks only
      trending(window='30d')            — use 30-day growth window
    """
    delta_col = "stars_7d_delta" if window == "7d" else "stars_30d_delta"
    baseline_col = "has_7d_baseline" if window == "7d" else "has_30d_baseline"
    window_label = "7 days" if window == "7d" else "30 days"

    lines = [
        f"TRENDING PROJECTS (last {window_label})",
        "=" * 40,
    ]

    try:
        with engine.connect() as conn:
            where_clause = ""
            params: dict = {}
            if category:
                where_clause = "WHERE s.category = :cat"
                params["cat"] = category

            rows = _safe_mv_query(conn, f"""
                SELECT s.name, s.category, s.stars, s.forks, s.monthly_downloads,
                       s.stars_7d_delta, s.stars_30d_delta, s.dl_30d_delta,
                       s.hype_ratio, s.hype_bucket,
                       s.last_release_at, s.last_release_title,
                       s.days_since_release, s.commits_30d,
                       s.has_7d_baseline, s.has_30d_baseline,
                       COALESCE(s.tier, 4) AS tier,
                       s.lifecycle_stage,
                       s.traction_score,
                       s.traction_bucket
                FROM mv_project_summary s
                {where_clause}
                ORDER BY {delta_col} DESC NULLS LAST
                LIMIT 20
            """, params)

            if rows:
                lines.append(
                    f"  {'#':<3} {'Project':<24} {'Tier':<5} {'Stage':<12} {'Category':<10} "
                    f"{'Stars':<10} {'7d':<10} {'30d':<10} "
                    f"{'DL/mo':<12} {'Traction':<10} {'Bucket':<16}"
                )
                lines.append("  " + "-" * 135)
                for i, r in enumerate(rows, 1):
                    has_bl = r.get(baseline_col, False)
                    delta_7d = _fmt_delta_safe(r.get('stars_7d_delta'), r.get('has_7d_baseline', False))
                    delta_30d = _fmt_delta_safe(r.get('stars_30d_delta'), r.get('has_30d_baseline', False))
                    traction = str(r.get('traction_score', '')) if r.get('traction_score') is not None else ''
                    bucket = str(r.get('traction_bucket', '')) or ''
                    lines.append(
                        f"  {i:<3} {str(r.get('name', '')):<24} "
                        f"T{int(r.get('tier', 4)):<4} "
                        f"{str(r.get('lifecycle_stage', '')):<12} "
                        f"{str(r.get('category', '')):<10} "
                        f"{_fmt_number(r.get('stars')):<10} "
                        f"{delta_7d:<10} "
                        f"{delta_30d:<10} "
                        f"{_fmt_number(r.get('monthly_downloads')):<12} "
                        f"{traction:<10} "
                        f"{bucket:<16}"
                    )
            else:
                lines.append("")
                lines.append("  No trending data available. The mv_project_summary materialized view")
                lines.append("  may not exist yet, or no data has been synced.")
                lines.append("")
                lines.append("  Falling back to base tables...")
                lines.append("")

                # Fallback: query GitHub snapshots directly
                session = SessionLocal()
                try:
                    gh_query = (
                        session.query(
                            Project.name,
                            Project.category,
                            GitHubSnapshot.stars,
                            GitHubSnapshot.forks,
                            GitHubSnapshot.commits_30d,
                        )
                        .join(GitHubSnapshot, GitHubSnapshot.project_id == Project.id)
                        .order_by(GitHubSnapshot.stars.desc())
                    )
                    if category:
                        gh_query = gh_query.filter(
                            func.lower(Project.category) == category.lower()
                        )
                    gh_query = gh_query.limit(20)
                    fallback_rows = gh_query.all()

                    if fallback_rows:
                        lines.append(
                            f"  {'#':<3} {'Project':<28} {'Category':<14} "
                            f"{'Stars':<10} {'Forks':<10} {'Commits 30d':<12}"
                        )
                        lines.append("  " + "-" * 80)
                        for i, row in enumerate(fallback_rows, 1):
                            lines.append(
                                f"  {i:<3} {row.name:<28} {row.category:<14} "
                                f"{_fmt_number(row.stars):<10} "
                                f"{_fmt_number(row.forks):<10} "
                                f"{_fmt_number(row.commits_30d):<12}"
                            )
                    else:
                        lines.append("  No GitHub snapshot data available either.")
                finally:
                    session.close()

    except Exception as e:
        lines.append(f"  Error querying trending data: {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: breakouts — small repos with explosive % growth
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def breakouts(
    min_stars: int = 100,
    max_stars: int = 5000,
    window: str = "7d",
    limit: int = 15,
) -> str:
    """Surface small repos with explosive percentage growth — the breakout detector.

    Finds repos that are small but growing disproportionately fast. These are
    the projects gaining traction before anyone's talking about them.

    Args:
        min_stars: Minimum stars at start of window (default 100)
        max_stars: Maximum stars at start of window (default 5000)
        window: '7d' or '30d' (default '7d')
        limit: Max results (default 15, max 30)

    Examples:
      breakouts()                          — 7-day breakouts, 100-5000 stars
      breakouts(max_stars=1000)            — micro-repos only
      breakouts(min_stars=5000, max_stars=20000) — mid-tier breakouts
      breakouts(window='30d', limit=20)    — 30-day breakouts
    """
    limit = min(max(1, limit), 30)
    days = 30 if window == "30d" else 7
    window_label = "7 days" if days == 7 else "30 days"

    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                WITH then_snapshot AS (
                    SELECT DISTINCT ON (project_id)
                        project_id, stars AS stars_then
                    FROM github_snapshots
                    WHERE snapshot_date <= (SELECT MAX(snapshot_date) - :days FROM github_snapshots)
                    ORDER BY project_id, snapshot_date DESC
                ),
                now_snapshot AS (
                    SELECT DISTINCT ON (project_id)
                        project_id, stars AS stars_now
                    FROM github_snapshots
                    ORDER BY project_id, snapshot_date DESC
                )
                SELECT
                    p.name, p.slug, p.category, p.domain, p.stack_layer,
                    LEFT(p.description, 100) AS description,
                    now_snapshot.stars_now,
                    then_snapshot.stars_then,
                    now_snapshot.stars_now - then_snapshot.stars_then AS gain,
                    ROUND(100.0 * (now_snapshot.stars_now - then_snapshot.stars_then)
                          / NULLIF(then_snapshot.stars_then, 0), 1) AS pct
                FROM now_snapshot
                JOIN then_snapshot USING (project_id)
                JOIN projects p ON p.id = now_snapshot.project_id
                WHERE then_snapshot.stars_then BETWEEN :min_stars AND :max_stars
                  AND now_snapshot.stars_now - then_snapshot.stars_then > 0
                  AND p.is_active = true
                ORDER BY pct DESC
                LIMIT :limit
            """), {
                "days": days,
                "min_stars": min_stars,
                "max_stars": max_stars,
                "limit": limit,
            }).fetchall()

        lines = [
            f"BREAKOUT DETECTION (last {window_label})",
            f"Star range at start of window: {min_stars:,} – {max_stars:,}",
            "=" * 60,
        ]

        if not rows:
            lines.append("  No breakouts detected in this range.")
            return "\n".join(lines)

        lines.append("")
        for i, r in enumerate(rows, 1):
            m = r._mapping
            lines.append(
                f"  {i}. {m['name']}  (+{m['pct']}%)"
            )
            lines.append(
                f"     {_fmt_number(m['stars_then'])} → {_fmt_number(m['stars_now'])} stars  "
                f"(+{_fmt_number(m['gain'])})"
            )
            if m.get('domain') or m.get('category'):
                parts = [x for x in [m.get('domain'), m.get('category'), m.get('stack_layer')] if x]
                lines.append(f"     {' / '.join(parts)}")
            if m.get('description'):
                lines.append(f"     {m['description']}")
            lines.append("")

        lines.append("Tip: Use project_pulse('name') for full details on any breakout.")

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"breakouts failed: {e}")
        return "Error detecting breakouts. Please try again."


# ---------------------------------------------------------------------------
# Tool: ecosystem_layer — explore a specific ecosystem layer
# ---------------------------------------------------------------------------

# Mapping of user-friendly layer names to query filters
_LAYER_FILTERS = {
    # MCP plumbing
    "mcp-gateway":    {"domain": "mcp", "subcategory": "gateway"},
    "mcp-transport":  {"domain": "mcp", "subcategory": "transport"},
    "mcp-security":   {"domain": "mcp", "subcategory": "security"},
    "mcp-framework":  {"domain": "mcp", "subcategory": "framework"},
    "mcp-ide":        {"domain": "mcp", "subcategory": "ide"},
    "mcp-observability": {"domain": "mcp", "subcategory": "observability"},
    "mcp":            {"domain": "mcp"},
    # Perception
    "perception":     {"domain": "perception"},
    # Agent subcategories
    "agent-framework": {"domain": "agents", "subcategory": "agent-framework"},
    "multi-agent":     {"domain": "agents", "subcategory": "multi-agent"},
    "coding-agent":    {"domain": "agents", "subcategory": "coding-agent"},
    "browser-agent":   {"domain": "agents", "subcategory": "browser-agent"},
    # Stack layers
    "orchestration":  {"stack_layer": "orchestration"},
    "inference":      {"stack_layer": "inference"},
    "model":          {"stack_layer": "model"},
    "data":           {"stack_layer": "data"},
    "eval":           {"stack_layer": "eval"},
    "interface":      {"stack_layer": "interface"},
    "infra":          {"stack_layer": "infra"},
    # AI repo domains
    "agents":         {"domain": "agents"},
    "nlp":            {"domain": "nlp"},
    "ai-coding":      {"domain": "ai-coding"},
    "llm-tools":      {"domain": "llm-tools"},
}


@mcp.tool()
@track_usage
async def ecosystem_layer(
    layer: str,
    sort_by: str = "stars",
    limit: int = 20,
) -> str:
    """Explore an ecosystem layer — e.g. MCP gateways, perception tools, agent frameworks.

    Shows repos in that layer with stars, downloads, growth, and traction data.

    Args:
        layer: Layer to explore. Options: mcp-gateway, mcp-transport, mcp-security,
               mcp-framework, mcp-ide, mcp-observability, mcp, perception,
               orchestration, inference, model, data, eval, interface, infra,
               agents, nlp, ai-coding, llm-tools
        sort_by: 'stars', 'downloads', or 'growth' (default: stars)
        limit: Max results (default 20, max 50)

    Examples:
      ecosystem_layer('mcp-gateway')
      ecosystem_layer('orchestration', sort_by='growth')
      ecosystem_layer('perception', limit=30)
    """
    layer = layer.strip().lower()
    limit = min(max(1, limit), 50)

    filters = _LAYER_FILTERS.get(layer)
    if not filters:
        available = ", ".join(sorted(_LAYER_FILTERS.keys()))
        return f"Unknown layer '{layer}'. Available layers:\n{available}"

    # Build WHERE clause
    conditions = []
    params: dict = {"limit": limit}

    if "domain" in filters:
        conditions.append("ar.domain = :domain")
        params["domain"] = filters["domain"]
    if "subcategory" in filters:
        conditions.append("ar.subcategory = :subcategory")
        params["subcategory"] = filters["subcategory"]
    if "stack_layer" in filters:
        conditions.append("p.stack_layer = :stack_layer")
        params["stack_layer"] = filters["stack_layer"]

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    order_col = {
        "downloads": "ar.downloads_monthly DESC NULLS LAST",
        "growth": "star_gain DESC NULLS LAST",
    }.get(sort_by, "ar.stars DESC NULLS LAST")

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                WITH latest_gh AS (
                    SELECT DISTINCT ON (project_id)
                        project_id, stars AS stars_now
                    FROM github_snapshots
                    ORDER BY project_id, snapshot_date DESC
                ),
                prev_7d AS (
                    SELECT DISTINCT ON (gs.project_id)
                        gs.project_id, gs.stars AS stars_7d_ago
                    FROM github_snapshots gs
                    JOIN latest_gh l ON gs.project_id = l.project_id
                    WHERE gs.snapshot_date <= (SELECT MAX(snapshot_date) - 7 FROM github_snapshots)
                    ORDER BY gs.project_id, gs.snapshot_date DESC
                )
                SELECT
                    ar.full_name, ar.name, ar.description,
                    ar.stars, ar.forks, ar.language, ar.domain, ar.subcategory,
                    ar.downloads_monthly, ar.dependency_count,
                    COALESCE(l.stars_now, 0) - COALESCE(p7.stars_7d_ago, 0) AS star_gain,
                    CASE WHEN COALESCE(p7.stars_7d_ago, 0) > 0
                         THEN ROUND(100.0 * (COALESCE(l.stars_now, 0) - COALESCE(p7.stars_7d_ago, 0))
                              / p7.stars_7d_ago, 1)
                         ELSE NULL END AS star_pct
                FROM ai_repos ar
                LEFT JOIN projects p ON p.ai_repo_id = ar.id
                LEFT JOIN latest_gh l ON l.project_id = p.id
                LEFT JOIN prev_7d p7 ON p7.project_id = p.id
                WHERE {where_clause}
                  AND ar.archived = false
                ORDER BY {order_col}
                LIMIT :limit
            """), params).fetchall()

        sort_label = {"downloads": "downloads", "growth": "7d growth"}.get(sort_by, "stars")
        lines = [
            f"ECOSYSTEM LAYER: {layer}",
            f"Sorted by: {sort_label}  |  {len(rows)} results",
            "=" * 60,
            "",
        ]

        if not rows:
            lines.append(f"  No repos found for layer '{layer}'.")
            return "\n".join(lines)

        for i, r in enumerate(rows, 1):
            m = r._mapping
            star_info = f"{_fmt_number(m['stars'])} stars"
            if m.get('star_gain') and m['star_gain'] > 0:
                star_info += f"  (+{_fmt_number(m['star_gain'])} / +{m.get('star_pct', '?')}% 7d)"

            dl_info = ""
            if m.get('downloads_monthly') and m['downloads_monthly'] > 0:
                dl_info = f"  |  {_fmt_number(m['downloads_monthly'])} dl/mo"

            dep_info = ""
            if m.get('dependency_count') and m['dependency_count'] > 0:
                dep_info = f"  |  {m['dependency_count']} dependents"

            lines.append(f"  {i}. {m['full_name']}  ({m.get('language', '?')})")
            lines.append(f"     {star_info}{dl_info}{dep_info}")
            if m.get('description'):
                desc = str(m['description'])[:120]
                lines.append(f"     {desc}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"ecosystem_layer failed: {e}")
        return f"Error querying ecosystem layer '{layer}'. Please try again."


# ---------------------------------------------------------------------------
# Tool 8: hype_check
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def hype_check(project: str) -> str:
    """Stars vs downloads reality check for a project."""
    session = SessionLocal()
    try:
        proj, suggestions = await _find_project_or_suggest(session, project)
        if not proj:
            return _not_found_msg("Project", project, suggestions)

        lines = [
            f"HYPE CHECK: {proj.name}",
            "=" * 40,
            "",
        ]

        hype_data = None
        category_avg = None

        try:
            with engine.connect() as conn:
                hype_rows = _safe_mv_query(conn, """
                    SELECT stars, monthly_downloads, hype_ratio, hype_bucket
                    FROM mv_hype_ratio
                    WHERE project_id = :pid
                """, {"pid": proj.id})

                if hype_rows:
                    hype_data = hype_rows[0]

                # Category average for context
                if proj.category:
                    avg_rows = _safe_mv_query(conn, """
                        SELECT
                            AVG(hype_ratio) as avg_ratio,
                            COUNT(*) as count
                        FROM mv_hype_ratio
                        WHERE category = :cat
                    """, {"cat": proj.category})
                    if avg_rows and avg_rows[0].get("avg_ratio"):
                        category_avg = avg_rows[0]
        except Exception:
            pass

        if hype_data:
            stars = hype_data.get("stars")
            downloads = hype_data.get("monthly_downloads")
            ratio = hype_data.get("hype_ratio")
            bucket = hype_data.get("hype_bucket", "unknown")

            lines.extend([
                f"  Stars:              {_fmt_number(stars)}",
                f"  Monthly Downloads:  {_fmt_number(downloads)}",
                f"  Hype Ratio:         {_fmt_ratio(ratio)}",
                f"  Bucket:             {bucket}",
                f"             explain('hype_ratio') for methodology and known limitations",
                "",
            ])

            # Multi-source download breakdown
            try:
                with engine.connect() as dl_conn:
                    source_rows = dl_conn.execute(text("""
                        SELECT source, downloads_monthly
                        FROM (
                            SELECT DISTINCT ON (source)
                                source, downloads_monthly
                            FROM download_snapshots
                            WHERE project_id = :pid
                            ORDER BY source, snapshot_date DESC
                        ) latest_per_source
                        ORDER BY downloads_monthly DESC
                    """), {"pid": proj.id}).fetchall()

                    if len(source_rows) > 1:
                        lines.append("DOWNLOAD SOURCES")
                        lines.append("-" * 30)
                        src_total = 0
                        for sr in source_rows:
                            src_name = sr[0] or "unknown"
                            src_dl = int(sr[1] or 0)
                            src_total += src_dl
                            lines.append(f"  {src_name + ':':<16} {_fmt_number(src_dl)}/mo")
                        lines.append(f"  {'Total:':<16} {_fmt_number(src_total)}/mo")
                        lines.append("")
            except Exception:
                pass  # Non-critical — skip if download_snapshots query fails

            # Interpretation
            lines.append("INTERPRETATION")
            lines.append("-" * 30)
            lines.append(f"  {_bucket_interpretation(bucket)}")

            if category_avg:
                lines.append("")
                lines.append("CATEGORY CONTEXT")
                lines.append("-" * 30)
                avg_val = category_avg.get('avg_ratio', 'n/a')
                lines.append(
                    f"  Average hype ratio in '{proj.category}': "
                    f"{_fmt_ratio(avg_val)}"
                )
                lines.append(
                    f"  Projects in category: {category_avg.get('count', 'n/a')}"
                )
                try:
                    project_ratio = float(ratio)
                    avg_ratio = float(avg_val)
                    if project_ratio > avg_ratio * 1.5:
                        lines.append(
                            "  This project is significantly more hyped than its category average."
                        )
                    elif project_ratio < avg_ratio * 0.5:
                        lines.append(
                            "  This project is significantly less hyped than its category average."
                        )
                    else:
                        lines.append(
                            "  This project is close to the category average."
                        )
                except (ValueError, TypeError):
                    pass
        else:
            # Fallback: compute from base tables
            gh = (
                session.query(GitHubSnapshot)
                .filter(GitHubSnapshot.project_id == proj.id)
                .order_by(GitHubSnapshot.snapshot_date.desc())
                .first()
            )
            dl = (
                session.query(DownloadSnapshot)
                .filter(DownloadSnapshot.project_id == proj.id)
                .order_by(DownloadSnapshot.snapshot_date.desc())
                .first()
            )

            if gh and dl and dl.downloads_monthly and dl.downloads_monthly > 0:
                ratio = round(gh.stars / dl.downloads_monthly, 4)
                lines.extend([
                    f"  Stars:              {_fmt_number(gh.stars)}",
                    f"  Monthly Downloads:  {_fmt_number(dl.downloads_monthly)}",
                    f"  Hype Ratio:         {ratio} (computed from base tables)",
                    "",
                    "  Note: mv_hype_ratio view not available. Bucket classification",
                    "  and category comparisons require the materialized view.",
                ])
            elif gh:
                lines.extend([
                    f"  Stars:              {_fmt_number(gh.stars)}",
                    "  Monthly Downloads:  no download data available",
                    "  Cannot compute hype ratio without download data.",
                ])
            else:
                lines.append("  No metrics data available for this project yet.")

    finally:
        session.close()

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 9: submit_feedback (was submit_correction)
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def submit_feedback(
    topic: str, correction: str, context: str = None, category: str = "observation"
) -> str:
    """Submit feedback about an AI topic or project.

    Categories: bug (broken/wrong data), feature (buildable thing), observation (strategic context), insight (analytical finding).
    Default 'observation' when unsure. All submissions are PUBLIC — do not include sensitive data.
    """
    # Input length limits
    if len(topic) > 300:
        return "Topic must be 300 characters or fewer."
    if len(correction) > 5000:
        return "Correction must be 5,000 characters or fewer."
    if context and len(context) > 2000:
        return "Context must be 2,000 characters or fewer."

    VALID_CATEGORIES = {"bug", "feature", "observation", "insight"}
    if category not in VALID_CATEGORIES:
        return f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"

    session = SessionLocal()
    try:
        c = Correction(
            topic=topic.strip(),
            correction=correction.strip(),
            context=context.strip() if context else None,
            category=category,
            status="active",
            upvotes=0,
        )
        session.add(c)
        session.commit()
        correction_id = c.id
        session.close()
        return (
            f"Feedback submitted successfully.\n"
            f"  ID:       {correction_id}\n"
            f"  Topic:    {topic}\n"
            f"  Category: {category}\n"
            f"  Text:     {correction[:200]}\n\n"
            f"Others can upvote this with upvote_feedback({correction_id})."
        )
    except Exception as e:
        session.rollback()
        session.close()
        return f"Failed to submit feedback: {e}"


# ---------------------------------------------------------------------------
# Tool 10: upvote_feedback (was upvote_correction)
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def upvote_feedback(correction_id: int) -> str:
    """Confirm someone else's feedback by upvoting it."""
    session = SessionLocal()
    try:
        # Rate limit: max 5 upvotes per correction per day
        recent = session.execute(text(
            "SELECT COUNT(*) FROM tool_usage "
            "WHERE tool_name IN ('upvote_correction', 'upvote_feedback') "
            "AND params->>'correction_id' = :cid "
            "AND created_at > NOW() - INTERVAL '24 hours'"
        ), {"cid": str(correction_id)}).scalar()
        if recent and recent >= 5:
            session.close()
            return f"Rate limit: feedback #{correction_id} has been upvoted {recent} times in the last 24 hours (max 5/day)."

        c = session.query(Correction).filter(Correction.id == correction_id).first()
        if not c:
            session.close()
            return f"Feedback #{correction_id} not found."

        c.upvotes = (c.upvotes or 0) + 1
        session.commit()
        new_count = c.upvotes
        topic = c.topic
        session.close()
        return (
            f"Upvoted feedback #{correction_id}.\n"
            f"  Topic:   {topic}\n"
            f"  Upvotes: {new_count}"
        )
    except Exception as e:
        session.rollback()
        session.close()
        return f"Failed to upvote feedback: {e}"


# ---------------------------------------------------------------------------
# Tool 11: list_feedback (was list_corrections)
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def list_feedback(topic: str = None, status: str = "active", category: str = None) -> str:
    """Browse practitioner feedback. Optionally filter by topic, status, and category."""
    session = SessionLocal()
    try:
        q = session.query(Correction).filter(Correction.status == status)

        if topic:
            q = q.filter(func.lower(Correction.topic).contains(topic.lower()))

        if category:
            q = q.filter(Correction.category == category)

        corrections = q.order_by(Correction.submitted_at.desc()).limit(50).all()

        if not corrections:
            filter_desc = f" for topic '{topic}'" if topic else ""
            return f"No {status} feedback found{filter_desc}."

        lines = [
            f"FEEDBACK (status: {status}{f', category: {category}' if category else ''})",
            "=" * 40,
        ]

        for c in corrections:
            lines.append("")
            lines.append(f"  [{c.id}] [{c.category.upper()}] {c.topic}")
            feedback_text = c.correction[:200]
            # Truncate at word boundary
            if len(c.correction) > 200:
                last_space = feedback_text.rfind(" ")
                if last_space > 100:
                    feedback_text = feedback_text[:last_space] + "..."
                else:
                    feedback_text += "..."
            lines.append(f"       {feedback_text}")
            if c.context:
                lines.append(f"       Context: {c.context[:100]}")
            lines.append(
                f"       Upvotes: {c.upvotes}  |  "
                f"Submitted: {_fmt_date(c.submitted_at)}  |  "
                f"Tags: {', '.join(c.tags) if c.tags else 'none'}"
            )

        lines.append("")
        lines.append(f"Total: {len(corrections)} feedback item(s)")

    finally:
        session.close()

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 12a: propose_article — community article pitches
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def propose_article(
    topic: str, thesis: str, evidence: str = None, audience_angle: str = None
) -> str:
    """Pitch an article idea for Phase Transitions newsletter.

    topic: Short title (e.g. 'The MCP Gold Rush')
    thesis: 1-2 sentences on why this matters now
    evidence: Which PT-Edge tools/signals support this (optional)
    audience_angle: Why Phase Transitions readers would care (optional)
    """
    if len(topic) > 300:
        return "Topic must be 300 characters or fewer."
    if len(thesis) > 2000:
        return "Thesis must be 2,000 characters or fewer."
    if evidence and len(evidence) > 2000:
        return "Evidence must be 2,000 characters or fewer."
    if audience_angle and len(audience_angle) > 1000:
        return "Audience angle must be 1,000 characters or fewer."

    session = SessionLocal()
    try:
        pitch = ArticlePitch(
            topic=topic.strip(),
            thesis=thesis.strip(),
            evidence=evidence.strip() if evidence else None,
            audience_angle=audience_angle.strip() if audience_angle else None,
            status="pending",
            upvotes=0,
        )
        session.add(pitch)
        session.commit()
        pitch_id = pitch.id
    except Exception as e:
        session.rollback()
        return f"Failed to submit pitch: {e}"
    finally:
        session.close()

    return (
        f"Article pitch submitted successfully.\n"
        f"  ID:       {pitch_id}\n"
        f"  Topic:    {topic}\n"
        f"  Thesis:   {thesis[:200]}\n\n"
        f"Others can upvote this with upvote_pitch({pitch_id}).\n"
        f"Browse all pitches with list_pitches()."
    )


# ---------------------------------------------------------------------------
# Tool 12b: list_pitches — browse article pitches
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def list_pitches(status: str = None) -> str:
    """Browse article pitches submitted by the community.

    Optional status filter: 'pending', 'accepted', 'rejected'.
    """
    session = SessionLocal()
    try:
        query = session.query(ArticlePitch)
        if status:
            query = query.filter(ArticlePitch.status == status)
        pitches = query.order_by(ArticlePitch.upvotes.desc(), ArticlePitch.submitted_at.desc()).all()

        if not pitches:
            return f"No article pitches found{f' with status={status}' if status else ''}."

        lines = [
            "ARTICLE PITCHES",
            "=" * 60,
        ]

        for p in pitches:
            lines.append(
                f"  [{p.id}] {p.topic}  (upvotes: {p.upvotes}, status: {p.status})"
            )

        lines.append("")
        lines.append(f"Total: {len(pitches)} pitch(es)")
        lines.append("")
        lines.append("Use upvote_pitch(id) to support a pitch.")

    finally:
        session.close()

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 12c: upvote_pitch — support an article pitch
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def upvote_pitch(pitch_id: int) -> str:
    """Upvote an article pitch to signal interest."""
    from app.models import ToolUsage

    session = SessionLocal()
    try:
        pitch = session.query(ArticlePitch).filter(ArticlePitch.id == pitch_id).first()
        if not pitch:
            return f"No article pitch found with ID {pitch_id}."

        # Rate limit: max 5 upvotes per pitch per day
        recent = (
            session.query(ToolUsage)
            .filter(
                ToolUsage.tool_name == "upvote_pitch",
                ToolUsage.created_at >= datetime.now(timezone.utc) - timedelta(days=1),
            )
            .count()
        )
        if recent >= 5:
            return "Rate limit: max 5 pitch upvotes per day."

        pitch.upvotes += 1
        session.commit()
        return (
            f"Upvoted pitch #{pitch_id}: {pitch.topic}\n"
            f"  Now at {pitch.upvotes} upvote(s)."
        )
    except Exception as e:
        session.rollback()
        return f"Failed to upvote: {e}"
    finally:
        session.close()


@mcp.tool()
@track_usage
async def amend_feedback(correction_id: int, reason: str) -> str:
    """Append an amendment note to feedback (e.g. flag a duplicate or outdated item).

    This is append-only — it does not delete or modify the original feedback.
    """
    if not reason or not reason.strip():
        return "Amendment reason is required."
    reason = reason.strip()
    if len(reason) > 500:
        return f"Reason too long ({len(reason)} chars). Max 500."

    from app.models import ToolUsage

    session = SessionLocal()
    try:
        correction = session.query(Correction).filter(Correction.id == correction_id).first()
        if not correction:
            return f"No feedback found with ID {correction_id}."

        # Rate limit: max 5 amendments per day
        recent = (
            session.query(ToolUsage)
            .filter(
                ToolUsage.tool_name.in_(["amend_correction", "amend_feedback"]),
                ToolUsage.created_at >= datetime.now(timezone.utc) - timedelta(days=1),
            )
            .count()
        )
        if recent >= 5:
            return "Rate limit: max 5 amendments per day."

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        note = f"\n[{timestamp}] {reason}"
        correction.amendments = (correction.amendments or "") + note
        session.commit()
        return (
            f"Amendment added to feedback #{correction_id}: {correction.topic}\n"
            f"  Note: {reason}"
        )
    except Exception as e:
        session.rollback()
        return f"Failed to amend: {e}"
    finally:
        session.close()


@mcp.tool()
@track_usage
async def amend_pitch(pitch_id: int, reason: str) -> str:
    """Append an amendment note to an article pitch (e.g. flag a duplicate or add context).

    This is append-only — it does not delete or modify the original pitch.
    """
    if not reason or not reason.strip():
        return "Amendment reason is required."
    reason = reason.strip()
    if len(reason) > 500:
        return f"Reason too long ({len(reason)} chars). Max 500."

    from app.models import ToolUsage

    session = SessionLocal()
    try:
        pitch = session.query(ArticlePitch).filter(ArticlePitch.id == pitch_id).first()
        if not pitch:
            return f"No article pitch found with ID {pitch_id}."

        # Rate limit: max 5 amendments per day
        recent = (
            session.query(ToolUsage)
            .filter(
                ToolUsage.tool_name == "amend_pitch",
                ToolUsage.created_at >= datetime.now(timezone.utc) - timedelta(days=1),
            )
            .count()
        )
        if recent >= 5:
            return "Rate limit: max 5 amendments per day."

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        note = f"\n[{timestamp}] {reason}"
        pitch.amendments = (pitch.amendments or "") + note
        session.commit()
        return (
            f"Amendment added to pitch #{pitch_id}: {pitch.topic}\n"
            f"  Note: {reason}"
        )
    except Exception as e:
        session.rollback()
        return f"Failed to amend: {e}"
    finally:
        session.close()


# Backwards-compatible aliases — delegate to new feedback tools
# Use _tool_fn() to unwrap the FunctionTool decorator and call the raw async fn.
async def submit_correction(topic: str, correction: str, context: str = None) -> str:
    """[Alias] Use submit_feedback() instead. Submits as category='observation'."""
    return await _tool_fn(submit_feedback)(topic=topic, correction=correction, context=context, category="observation")

async def upvote_correction(correction_id: int) -> str:
    """[Alias] Use upvote_feedback() instead."""
    return await _tool_fn(upvote_feedback)(correction_id=correction_id)

async def list_corrections(topic: str = None, status: str = "active") -> str:
    """[Alias] Use list_feedback() instead."""
    return await _tool_fn(list_feedback)(topic=topic, status=status)

async def amend_correction(correction_id: int, reason: str) -> str:
    """[Alias] Use amend_feedback() instead."""
    return await _tool_fn(amend_feedback)(correction_id=correction_id, reason=reason)


# ---------------------------------------------------------------------------
# Lab Intelligence tools
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def submit_lab_event(
    lab: str, event_type: str, title: str,
    summary: str = None, source_url: str = None, event_date: str = None,
) -> str:
    """Record a significant lab event that moved the practical frontier.

    Only record events where the capability surface area changed — new models, products,
    APIs, or deprecations. Skip funding, politics, opinions, and adoption news.

    Event types: product_launch, model_launch, capability, api_change, deprecation, protocol, other
    """
    VALID_EVENT_TYPES = {
        "product_launch", "model_launch", "capability", "api_change",
        "protocol", "deprecation", "other",
    }
    if event_type not in VALID_EVENT_TYPES:
        return f"Invalid event_type '{event_type}'. Must be one of: {', '.join(sorted(VALID_EVENT_TYPES))}"
    if not title or len(title) > 300:
        return "Title is required and must be ≤ 300 characters."
    if summary and len(summary) > 2000:
        return "Summary must be ≤ 2000 characters."

    session = SessionLocal()
    try:
        lab_obj, suggestions = _find_lab_or_suggest(session, lab)
        if not lab_obj:
            return _not_found_msg("Lab", lab, suggestions)

        from app.models import LabEvent
        from datetime import datetime, timezone

        parsed_date = None
        if event_date:
            try:
                parsed_date = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
            except ValueError:
                return f"Invalid event_date format. Use ISO 8601 (e.g., '2026-03-05')."
        else:
            parsed_date = datetime.now(timezone.utc)

        event = LabEvent(
            lab_id=lab_obj.id,
            event_type=event_type,
            title=title.strip(),
            summary=summary.strip() if summary else None,
            source_url=source_url,
            event_date=parsed_date,
        )
        session.add(event)
        session.commit()
        session.refresh(event)

        return (
            f"Lab event recorded (ID: {event.id}).\n"
            f"  Lab: {lab_obj.name}\n"
            f"  Type: {event_type}\n"
            f"  Title: {title[:100]}\n"
            f"  Date: {parsed_date.strftime('%Y-%m-%d') if parsed_date else 'now'}"
        )
    except Exception as e:
        return f"Failed to record lab event: {e}"
    finally:
        session.close()


@mcp.tool()
@track_usage
async def list_lab_events(lab: str = None, event_type: str = None, limit: int = 20) -> str:
    """Browse lab events — product launches, model releases, API changes, etc.

    Optional lab filter (slug or name). Optional event_type filter.
    """
    session = SessionLocal()
    try:
        from app.models import LabEvent

        q = session.query(LabEvent, Lab.name.label("lab_name")).join(
            Lab, LabEvent.lab_id == Lab.id
        )

        if lab:
            lab_obj, suggestions = _find_lab_or_suggest(session, lab)
            if not lab_obj:
                return _not_found_msg("Lab", lab, suggestions)
            q = q.filter(LabEvent.lab_id == lab_obj.id)

        if event_type:
            q = q.filter(LabEvent.event_type == event_type)

        events = q.order_by(LabEvent.event_date.desc()).limit(min(limit, 50)).all()

        if not events:
            return f"No lab events found{f' for {lab}' if lab else ''}."

        lines = [
            f"LAB EVENTS{f' — {lab}' if lab else ''}",
            "=" * 60,
        ]

        for event, lab_name in events:
            date_str = event.event_date.strftime("%Y-%m-%d") if event.event_date else "n/a"
            lines.append(
                f"  {date_str}  [{event.event_type}]  {lab_name}: {event.title}"
            )
            if event.summary:
                summary_text = event.summary[:120]
                if len(event.summary) > 120:
                    last_space = summary_text.rfind(" ")
                    if last_space > 60:
                        summary_text = summary_text[:last_space] + "..."
                    else:
                        summary_text += "..."
                lines.append(f"             {summary_text}")
            if event.source_url:
                lines.append(f"             {event.source_url}")
            lines.append("")

        lines.append(f"Total: {len(events)} event(s)")
        return "\n".join(lines)
    finally:
        session.close()


@mcp.tool()
@track_usage
async def lab_models(lab: str = None, capability: str = None) -> str:
    """Browse frontier models by lab. Shows context windows, pricing, and capabilities.

    Optional lab filter (slug or name). Optional capability filter (e.g. 'vision', 'reasoning').
    """
    session = SessionLocal()
    try:
        from app.models import FrontierModel

        q = session.query(FrontierModel, Lab.name.label("lab_name")).join(
            Lab, FrontierModel.lab_id == Lab.id
        ).filter(FrontierModel.status == "active")

        if lab:
            lab_obj, suggestions = _find_lab_or_suggest(session, lab)
            if not lab_obj:
                return _not_found_msg("Lab", lab, suggestions)
            q = q.filter(FrontierModel.lab_id == lab_obj.id)

        models = q.order_by(Lab.name, FrontierModel.name).all()

        if capability:
            # Filter in Python since capabilities is JSONB
            models = [
                (m, ln) for m, ln in models
                if m.capabilities and m.capabilities.get(capability)
            ]

        if not models:
            return f"No frontier models found{f' for {lab}' if lab else ''}{f' with {capability}' if capability else ''}."

        lines = [
            "FRONTIER MODELS",
            "=" * 60,
        ]

        current_lab = None
        for model, lab_name in models:
            if lab_name != current_lab:
                current_lab = lab_name
                lines.append("")
                lines.append(f"{lab_name}")
                lines.append("-" * 30)

            ctx = f"{model.context_window:,}tok" if model.context_window else "n/a"
            pricing = ""
            if model.pricing_input and model.pricing_output:
                pricing = f"  in: {model.pricing_input}, out: {model.pricing_output}"
            elif not model.pricing_input and not model.pricing_output:
                pricing = "  (open weights)"

            caps = ""
            if model.capabilities:
                cap_list = [k for k, v in model.capabilities.items() if v]
                if cap_list:
                    caps = f"  [{', '.join(cap_list[:5])}]"

            lines.append(
                f"  {model.name:<30} ctx: {ctx:<14}{pricing}{caps}"
            )

        lines.append("")
        lines.append(f"Total: {len(models)} model(s)")
        return "\n".join(lines)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Tool 12: lifecycle_map
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def lifecycle_map(category: str = None, tier: int = None, transitions: bool = False) -> str:
    """Groups all projects by lifecycle stage. Filter by category or tier.

    Set transitions=True to see which projects changed lifecycle stage recently.
    """
    lines = ["LIFECYCLE MAP", "=" * 40]

    try:
        with engine.connect() as conn:
            where_parts = []
            params: dict = {}
            if category:
                where_parts.append("lc.category = :cat")
                params["cat"] = category
            if tier:
                where_parts.append("COALESCE(t.tier, 4) = :tier")
                params["tier"] = tier

            where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

            rows = _safe_mv_query(conn, f"""
                SELECT lc.name, lc.category, lc.lifecycle_stage,
                       lc.stars, lc.monthly_downloads,
                       lc.commits_30d, lc.releases_30d,
                       COALESCE(t.tier, 4) AS tier
                FROM mv_lifecycle lc
                LEFT JOIN mv_project_tier t ON lc.project_id = t.project_id
                {where_clause}
                ORDER BY lc.lifecycle_stage, lc.stars DESC
            """, params)

            if not rows:
                lines.append("")
                lines.append("  No lifecycle data available. Run view refresh first.")
                return "\n".join(lines)

            stage_order = ["emerging", "launching", "growing", "established", "fading", "dormant", "unknown"]
            stage_descriptions = {
                "emerging": "New projects, few releases, building initial traction",
                "launching": "First releases within 90 days, downloads ramping up",
                "growing": "Active development, positive momentum, regular releases",
                "established": "High adoption (>100K downloads/mo), stable, well-maintained",
                "fading": "Declining activity -- commits slowing, releases drying up",
                "dormant": "No recent commits or releases",
                "unknown": "Insufficient data -- missing GitHub or download metrics",
            }

            grouped = {}
            for r in rows:
                stage = r.get("lifecycle_stage", "unknown")
                grouped.setdefault(stage, []).append(r)

            # Summary line
            total_projects = sum(len(grouped.get(s, [])) for s in stage_order)
            active_stages = sum(1 for s in stage_order if grouped.get(s))
            lines.append("")
            lines.append(f"{total_projects} projects across {active_stages} stages.")

            stage_cap = 10

            for stage in stage_order:
                projects = grouped.get(stage, [])
                if not projects:
                    continue
                lines.append("")
                lines.append(f"{stage.upper()} ({len(projects)} projects)")
                lines.append(f"  {stage_descriptions.get(stage, '')}")
                lines.append("-" * 30)
                display = projects[:stage_cap]
                for r in display:
                    lines.append(
                        f"  [T{int(r.get('tier', 4))}] {r.get('name', ''):<24} "
                        f"[{r.get('category', '')}]  "
                        f"stars: {_fmt_number(r.get('stars'))}  "
                        f"DL/mo: {_fmt_number(r.get('monthly_downloads'))}  "
                        f"commits: {_fmt_number(r.get('commits_30d'))}  "
                        f"releases: {r.get('releases_30d', 0)}/30d"
                    )
                if len(projects) > stage_cap:
                    lines.append(f"  ... showing top {stage_cap} of {len(projects)}. Use lifecycle_map(category='X') to filter.")

            # Transitions section
            if transitions:
                cat_filter = "AND c.category = :cat" if category else ""
                transition_rows = conn.execute(text(f"""
                    SELECT c.name, c.category,
                           h.lifecycle_stage AS previous_stage,
                           c.lifecycle_stage AS current_stage,
                           c.stars
                    FROM mv_lifecycle c
                    JOIN lifecycle_history h ON h.project_id = c.project_id
                    WHERE h.snapshot_date = (
                        SELECT MAX(snapshot_date) FROM lifecycle_history
                        WHERE project_id = c.project_id
                          AND snapshot_date <= CURRENT_DATE - INTERVAL '30 days'
                    )
                    AND h.lifecycle_stage != c.lifecycle_stage
                    {cat_filter}
                    ORDER BY c.stars DESC
                """), params).fetchall()

                lines.append("")
                lines.append("LIFECYCLE TRANSITIONS (last 30 days)")
                lines.append("-" * 40)
                if transition_rows:
                    for r in transition_rows:
                        m = r._mapping
                        lines.append(
                            f"  {m['name']:<28} [{m['category']}]  "
                            f"{m['previous_stage']} -> {m['current_stage']}  "
                            f"stars: {_fmt_number(m['stars'])}"
                        )
                else:
                    lines.append("  No stage transitions detected (needs 30+ days of history).")

    except Exception as e:
        lines.append(f"  Error: {e}")

    lines.append("")
    lines.append("explain('lifecycle_stages') for how stages are computed.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 13: hype_landscape
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def hype_landscape(category: str = None, limit: int = 10, window: str = None, format: str = "text") -> str:
    """Top overhyped + top underrated projects. Bulk hype comparison.

    Optional window ('30d' or '90d') adds a hype-ratio trend section showing
    which projects' ratios are shifting fastest.
    Set format='json' for machine-readable output.
    """
    limit = min(limit, 20)
    lines = ["HYPE LANDSCAPE", "=" * 40]
    overhyped = []
    underrated = []
    trend_data = []

    try:
        with engine.connect() as conn:
            cat_filter = "AND category = :cat" if category else ""
            params: dict = {"lim": limit}
            if category:
                params["cat"] = category

            # Most overhyped (highest ratio, must actually be in 'hype' bucket)
            overhyped = _safe_mv_query(conn, f"""
                SELECT name, category, stars, monthly_downloads, hype_ratio, hype_bucket
                FROM mv_hype_ratio
                WHERE hype_ratio IS NOT NULL AND hype_ratio > 0
                  AND hype_bucket = 'hype'
                  {cat_filter}
                ORDER BY hype_ratio DESC
                LIMIT :lim
            """, params)

            # Most underrated (lowest ratio, excluding zero)
            underrated = _safe_mv_query(conn, f"""
                SELECT name, category, stars, monthly_downloads, hype_ratio, hype_bucket
                FROM mv_hype_ratio
                WHERE hype_ratio IS NOT NULL AND hype_ratio > 0 {cat_filter}
                ORDER BY hype_ratio ASC
                LIMIT :lim
            """, params)

            if not overhyped and not underrated:
                if format == "json":
                    return json.dumps({"overhyped": [], "underrated": [], "trend": []})
                lines.append("")
                lines.append("  No hype data available. Run view refresh first.")
                return "\n".join(lines)

            lines.append("")
            lines.append(f"MOST OVERHYPED (stars >> downloads){f' in {category}' if category else ''}")
            lines.append("-" * 30)
            for r in overhyped:
                lines.append(
                    f"  {r.get('name', ''):<28} ratio: {_fmt_ratio(r.get('hype_ratio')):<10} "
                    f"stars: {_fmt_number(r.get('stars')):<10} "
                    f"DL/mo: {_fmt_number(r.get('monthly_downloads')):<12} "
                    f"[{r.get('hype_bucket', '')}]"
                )

            lines.append("")
            lines.append(f"MOST UNDERRATED (downloads >> stars){f' in {category}' if category else ''}")
            lines.append("-" * 30)
            for r in underrated:
                lines.append(
                    f"  {r.get('name', ''):<28} ratio: {_fmt_ratio(r.get('hype_ratio')):<10} "
                    f"stars: {_fmt_number(r.get('stars')):<10} "
                    f"DL/mo: {_fmt_number(r.get('monthly_downloads')):<12} "
                    f"[{r.get('hype_bucket', '')}]"
                )

            # Time dimension — hype ratio trend from historical snapshots
            if window:
                weeks = 12 if window == "90d" else 4
                trend_params: dict = {"lim": limit, "weeks": weeks}
                trend_cat = ""
                if category:
                    trend_cat = "AND p.category = :cat"
                    trend_params["cat"] = category

                trend_rows = conn.execute(text(f"""
                    WITH weekly_hype AS (
                        SELECT p.name, p.category,
                               gs.snapshot_date,
                               gs.stars,
                               ds.downloads_monthly,
                               CASE WHEN ds.downloads_monthly > 0
                                    THEN gs.stars::numeric / ds.downloads_monthly
                                    ELSE NULL END AS hype_ratio
                        FROM projects p
                        JOIN github_snapshots gs ON gs.project_id = p.id
                        LEFT JOIN download_snapshots ds ON ds.project_id = p.id
                            AND ds.snapshot_date = gs.snapshot_date
                        WHERE p.is_active = true
                          AND gs.snapshot_date >= CURRENT_DATE - INTERVAL ':weeks weeks'
                          {trend_cat}
                    )
                    SELECT name, category,
                           MIN(hype_ratio) AS min_ratio,
                           MAX(hype_ratio) AS max_ratio,
                           MAX(hype_ratio) - MIN(hype_ratio) AS ratio_change
                    FROM weekly_hype
                    WHERE hype_ratio IS NOT NULL
                    GROUP BY name, category
                    HAVING COUNT(DISTINCT snapshot_date) >= 2
                    ORDER BY ratio_change DESC
                    LIMIT :lim
                """), trend_params).fetchall()

                if trend_rows:
                    trend_data = [dict(r._mapping) for r in trend_rows]
                    lines.append("")
                    lines.append(f"HYPE RATIO TREND (last {window})")
                    lines.append("-" * 30)
                    for r in trend_data:
                        lines.append(
                            f"  {r['name']:<28} "
                            f"min: {_fmt_ratio(r.get('min_ratio')):<8} "
                            f"max: {_fmt_ratio(r.get('max_ratio')):<8} "
                            f"change: {_fmt_ratio(r.get('ratio_change'))}"
                        )

    except Exception as e:
        lines.append(f"  Error: {e}")

    if format == "json":
        data = {"overhyped": overhyped, "underrated": underrated}
        if window:
            data["trend"] = trend_data
        return json.dumps(data, default=_serialize)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 14: sniff_projects
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def sniff_projects(limit: int = 20) -> str:
    """Auto-discovered project candidates awaiting review."""
    lines = ["PROJECT CANDIDATES", "=" * 40]

    session = SessionLocal()
    try:
        rows = session.execute(text("""
            SELECT id, github_url, name, description, stars, language, source, source_detail, discovered_at
            FROM project_candidates
            WHERE status = 'pending'
            ORDER BY stars DESC NULLS LAST, discovered_at DESC
            LIMIT :lim
        """), {"lim": limit}).fetchall()

        total = session.execute(text(
            "SELECT COUNT(*) FROM project_candidates WHERE status = 'pending'"
        )).scalar() or 0

        if not rows:
            lines.append("")
            lines.append("  No pending candidates. Run ingest to discover new projects.")
            return "\n".join(lines)

        lines.append(f"  Showing {len(rows)} of {total} pending candidates")
        lines.append("")

        for r in rows:
            m = r._mapping
            lines.append(f"  [{m['id']}] {m['name'] or m['github_url']}")
            if m.get("description"):
                lines.append(f"       {str(m['description'])[:120]}")
            lines.append(
                f"       Stars: {_fmt_number(m.get('stars'))}  "
                f"Language: {m.get('language') or 'n/a'}  "
                f"Source: {m.get('source')}"
            )
            if m.get("source_detail"):
                lines.append(f"       Found via: {str(m['source_detail'])[:100]}")
            lines.append("")

        lines.append(f"Use accept_candidate(id, category) to promote a candidate.")

    except Exception as e:
        lines.append(f"  Error: {e}")
    finally:
        session.close()

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 15: accept_candidate
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {
    "tool", "model", "framework", "library", "agent", "eval", "dataset", "infra",
    "mcp-server", "security",
}


@mcp.tool()
@track_usage
async def accept_candidate(candidate_id: int, category: str = "tool", lab_slug: str = None) -> str:
    """Promote a candidate to a tracked project."""
    if category not in VALID_CATEGORIES:
        return f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"

    session = SessionLocal()
    try:
        candidate = session.execute(text(
            "SELECT * FROM project_candidates WHERE id = :cid AND status = 'pending'"
        ), {"cid": candidate_id}).fetchone()

        if not candidate:
            return f"Candidate #{candidate_id} not found or already reviewed."

        c = candidate._mapping

        # Resolve lab
        lab_id = None
        if lab_slug:
            lab_obj, _ = _find_lab_or_suggest(session, lab_slug)
            if lab_obj:
                lab_id = lab_obj.id

        # Generate slug from repo name
        slug = (c.get("github_repo") or c.get("name") or f"candidate-{candidate_id}").lower()
        slug = re.sub(r"[^a-z0-9-]", "-", slug).strip("-")

        # Check for duplicate slug
        existing = session.query(Project).filter(Project.slug == slug).first()
        if existing:
            return f"A project with slug '{slug}' already exists."

        # Create project
        project = Project(
            slug=slug,
            name=c.get("name") or c.get("github_repo") or slug,
            category=category,
            lab_id=lab_id,
            github_owner=c.get("github_owner"),
            github_repo=c.get("github_repo"),
            url=c.get("github_url"),
            description=(c.get("description") or "")[:500],
            is_active=True,
        )
        session.add(project)

        # Mark candidate as accepted
        session.execute(text(
            "UPDATE project_candidates SET status = 'accepted', reviewed_at = NOW() WHERE id = :cid"
        ), {"cid": candidate_id})

        session.commit()

        return (
            f"Candidate accepted and added as tracked project.\n"
            f"  Slug:     {slug}\n"
            f"  Category: {category}\n"
            f"  GitHub:   {c.get('github_owner')}/{c.get('github_repo')}\n\n"
            f"It will be included in the next ingest cycle."
        )

    except Exception as e:
        session.rollback()
        return f"Failed to accept candidate: {e}"
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Tool 16: set_tier
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def set_tier(project: str, tier: int) -> str:
    """Set an editorial tier override for a project. Tier 1-4, or 0 to clear."""
    if tier not in (0, 1, 2, 3, 4):
        return "Tier must be 0 (clear override), 1 (Foundational), 2 (Major), 3 (Notable), or 4 (Emerging)."

    session = SessionLocal()
    try:
        proj, suggestions = await _find_project_or_suggest(session, project)
        if not proj:
            return _not_found_msg("Project", project, suggestions)

        if tier == 0:
            proj.tier_override = None
            session.commit()
            return f"Tier override cleared for {proj.name}. Will use auto-computed tier on next refresh."
        else:
            proj.tier_override = tier
            session.commit()
            return (
                f"Tier override set for {proj.name}.\n"
                f"  New tier: {_fmt_tier(tier)}\n"
                f"  Takes effect on next materialized view refresh."
            )
    except Exception as e:
        session.rollback()
        return f"Failed to set tier: {e}"
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Tool 17: movers — second-derivative acceleration detector
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def movers(window: str = "7d", limit: int = 10) -> str:
    """Show which projects are accelerating or decelerating — the biggest directional changes.

    Compares the current window's star delta to the prior window's delta.
    Requires 14+ days of snapshot data to work.
    """
    if window not in ("7d", "30d"):
        return "Window must be '7d' or '30d'."

    days = 7 if window == "7d" else 30
    need_days = days * 2

    lines = [
        f"MOVERS (comparing last {days}d vs prior {days}d)",
        "=" * 50,
    ]

    try:
        with engine.connect() as conn:
            # Check if we have enough snapshot history
            span = conn.execute(text("""
                SELECT MAX(snapshot_date) - MIN(snapshot_date) AS span
                FROM github_snapshots
            """))
            span_row = span.fetchone()
            if not span_row or (span_row[0] or 0) < need_days:
                actual = int(span_row[0]) if span_row and span_row[0] else 0
                lines.append("")
                lines.append(f"  Need {need_days} days of snapshot data, have {actual} day(s).")
                lines.append(f"  Check back when the dataset has {need_days}+ days of history.")
                return "\n".join(lines)

            rows = _safe_mv_query(conn, """
                WITH snapshots_ranked AS (
                    SELECT
                        project_id,
                        snapshot_date,
                        stars,
                        ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY snapshot_date DESC) AS rn
                    FROM github_snapshots
                    WHERE stars IS NOT NULL
                ),
                deltas AS (
                    SELECT
                        cur.project_id,
                        cur.stars AS stars_now,
                        cur.stars - mid.stars AS current_delta,
                        mid.stars - prev.stars AS prior_delta,
                        (cur.stars - mid.stars) - (mid.stars - prev.stars) AS acceleration
                    FROM snapshots_ranked cur
                    JOIN snapshots_ranked mid
                        ON mid.project_id = cur.project_id AND mid.rn = :days + 1
                    JOIN snapshots_ranked prev
                        ON prev.project_id = cur.project_id AND prev.rn = :need_days + 1
                    WHERE cur.rn = 1
                )
                SELECT
                    p.name, p.slug,
                    COALESCE(s.tier, 4) AS tier,
                    d.stars_now, d.current_delta, d.prior_delta, d.acceleration
                FROM deltas d
                JOIN projects p ON p.id = d.project_id
                LEFT JOIN mv_project_summary s ON s.slug = p.slug
                ORDER BY d.acceleration DESC
            """, {"days": days, "need_days": need_days})

            if not rows:
                lines.append("")
                lines.append("  No mover data available yet.")
                return "\n".join(lines)

            accel = [r for r in rows if (r.get("acceleration") or 0) > 0][:limit]
            decel = [r for r in rows if (r.get("acceleration") or 0) < 0]
            decel = decel[-limit:][::-1]  # biggest negative last, then reverse for display

            if accel:
                lines.append("")
                lines.append("ACCELERATING (gaining momentum)")
                lines.append(f"  {'Project':<24} {'Tier':<5} {'Stars':<12} "
                             f"{'This {days}d':<12} {'Prior {days}d':<12} {'Accel':<10}")
                lines.append("  " + "-" * 80)
                for r in accel:
                    lines.append(
                        f"  {str(r.get('name', '')):<24} "
                        f"T{int(r.get('tier', 4)):<4} "
                        f"{_fmt_number(r.get('stars_now')):<12} "
                        f"{_fmt_delta(r.get('current_delta')):<12} "
                        f"{_fmt_delta(r.get('prior_delta')):<12} "
                        f"{_fmt_delta(r.get('acceleration')):<10}"
                    )

            if decel:
                lines.append("")
                lines.append("DECELERATING (losing momentum)")
                lines.append(f"  {'Project':<24} {'Tier':<5} {'Stars':<12} "
                             f"{'This {days}d':<12} {'Prior {days}d':<12} {'Accel':<10}")
                lines.append("  " + "-" * 80)
                for r in decel:
                    lines.append(
                        f"  {str(r.get('name', '')):<24} "
                        f"T{int(r.get('tier', 4)):<4} "
                        f"{_fmt_number(r.get('stars_now')):<12} "
                        f"{_fmt_delta(r.get('current_delta')):<12} "
                        f"{_fmt_delta(r.get('prior_delta')):<12} "
                        f"{_fmt_delta(r.get('acceleration')):<10}"
                    )

            if not accel and not decel:
                lines.append("")
                lines.append("  No significant movers detected.")

    except Exception as e:
        lines.append(f"  Error: {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 18: compare — side-by-side project comparison
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def compare(projects: str) -> str:
    """Side-by-side comparison of 2-5 projects. Pass comma-separated names or slugs."""
    names = [n.strip() for n in projects.split(",") if n.strip()]
    if len(names) < 2:
        return "Please provide at least 2 project names, separated by commas."
    if len(names) > 5:
        return "Maximum 5 projects for comparison. Please narrow your selection."

    session = SessionLocal()
    try:
        found = []
        for name in names:
            proj, suggestions = await _find_project_or_suggest(session, name)
            if not proj:
                return _not_found_msg("Project", name, suggestions)
            found.append(proj)
    finally:
        session.close()

    slugs = [p.slug for p in found]
    display_names = [p.name for p in found]

    try:
        with engine.connect() as conn:
            placeholders = ", ".join(f":s{i}" for i in range(len(slugs)))
            params = {f"s{i}": s for i, s in enumerate(slugs)}

            rows = _safe_mv_query(conn, f"""
                SELECT s.slug, s.name, s.category,
                       COALESCE(s.tier, 4) AS tier,
                       s.lifecycle_stage, s.stars, s.forks,
                       s.monthly_downloads, s.stars_7d_delta, s.stars_30d_delta,
                       s.hype_ratio, s.hype_bucket,
                       s.commits_30d,
                       s.last_release_at, s.last_release_title,
                       s.days_since_release,
                       s.has_7d_baseline, s.has_30d_baseline
                FROM mv_project_summary s
                WHERE s.slug IN ({placeholders})
            """, params)

            # Index by slug for ordered output
            by_slug = {r["slug"]: r for r in rows}

        # Build comparison table
        col_width = max(len(n) for n in display_names) + 2
        col_width = max(col_width, 16)

        header = f"{'':20}" + "".join(f"{n:<{col_width}}" for n in display_names)
        lines = [
            f"COMPARE: {' vs '.join(display_names)}",
            "=" * len(header),
            header,
            "-" * len(header),
        ]

        def _row(label, key, fmt=None):
            vals = []
            for slug in slugs:
                r = by_slug.get(slug, {})
                v = r.get(key)
                if fmt:
                    v = fmt(v)
                elif v is None:
                    v = "n/a"
                else:
                    v = str(v)
                vals.append(v)
            lines.append(f"{label:20}" + "".join(f"{v:<{col_width}}" for v in vals))

        _row("Category", "category")
        _row("Tier", "tier", lambda v: f"T{int(v)}" if v is not None else "n/a")
        _row("Stage", "lifecycle_stage")
        _row("Stars", "stars", _fmt_number)
        _row("Forks", "forks", _fmt_number)
        _row("DL/mo", "monthly_downloads", _fmt_number)
        def _delta_7d(slug):
            r = by_slug.get(slug, {})
            return _fmt_delta_safe(r.get("stars_7d_delta"), r.get("has_7d_baseline", False))

        def _delta_30d(slug):
            r = by_slug.get(slug, {})
            return _fmt_delta_safe(r.get("stars_30d_delta"), r.get("has_30d_baseline", False))

        # Stars 7d/30d — use actual baseline flags
        vals_7d = [_delta_7d(s) for s in slugs]
        lines.append(f"{'Stars 7d':20}" + "".join(f"{v:<{col_width}}" for v in vals_7d))
        vals_30d = [_delta_30d(s) for s in slugs]
        lines.append(f"{'Stars 30d':20}" + "".join(f"{v:<{col_width}}" for v in vals_30d))
        _row("Hype Ratio", "hype_ratio", _fmt_ratio)
        _row("Hype Bucket", "hype_bucket")
        _row("Commits 30d", "commits_30d", _fmt_number)
        _row("Last Release", "last_release_title", lambda v: _fmt_version(str(v)) if v else "n/a")
        _row("Days Since Rel", "days_since_release", lambda v: str(int(v)) if v is not None and int(v) > 0 else "n/a")

        # Add missing projects warning
        missing = [s for s in slugs if s not in by_slug]
        if missing:
            lines.append("")
            lines.append(f"Note: No summary data for: {', '.join(missing)}. Views may need refreshing.")

        # Auto-generated editorial narrative
        narratives = []

        # Size disparity
        stars_data = [(by_slug.get(s, {}).get("stars") or 0, s) for s in slugs]
        stars_data.sort(reverse=True)
        if stars_data[0][0] and stars_data[-1][0] and stars_data[-1][0] > 0:
            ratio = stars_data[0][0] / stars_data[-1][0]
            if ratio > 10:
                top_name = by_slug.get(stars_data[0][1], {}).get("name", "?")
                bot_name = by_slug.get(stars_data[-1][1], {}).get("name", "?")
                narratives.append(
                    f"{top_name} has {ratio:.0f}x more stars than {bot_name}, "
                    f"but stars aren't adoption."
                )

        # Hype divergence — group by bucket to avoid repetitive lines
        bucket_groups: dict[str, list[str]] = {}
        for slug in slugs:
            r = by_slug.get(slug, {})
            bucket = r.get("hype_bucket", "")
            if bucket in ("hype", "quiet_adoption"):
                bucket_groups.setdefault(bucket, []).append(r.get("name", "?"))
        for bucket, names in bucket_groups.items():
            if bucket == "hype":
                label = "'hype' territory — stars vastly exceed downloads"
            else:
                label = "'quiet adoption' — heavily used but few stars"
            if len(names) == 1:
                narratives.append(f"{names[0]} is {label}.")
            else:
                all_count = sum(len(v) for v in bucket_groups.values())
                total = len(slugs)
                if len(names) >= total - 1 and total > 2:
                    # Almost all share the same bucket — highlight the outlier
                    others = [n for b, ns in bucket_groups.items() if b != bucket for n in ns]
                    if others:
                        narratives.append(
                            f"{len(names)} of {total} projects are {label}. "
                            f"The outlier is {others[0]}."
                        )
                    else:
                        narratives.append(f"All {len(names)} projects are {label}.")
                else:
                    narratives.append(f"{', '.join(names)} are all {label}.")

        # Lifecycle mismatch
        stages = {}
        for slug in slugs:
            r = by_slug.get(slug, {})
            if r.get("lifecycle_stage"):
                stages[slug] = r["lifecycle_stage"]
        if len(set(stages.values())) > 1:
            stage_strs = [f"{by_slug[s].get('name', '?')}: {stages[s]}" for s in slugs if s in stages]
            narratives.append(f"Different lifecycle stages: {', '.join(stage_strs)}.")

        # Momentum winner — only if we have valid baselines
        has_any_baseline = any(
            by_slug.get(s, {}).get("has_7d_baseline") for s in slugs
        )
        if has_any_baseline:
            accel = [(by_slug.get(s, {}).get("stars_7d_delta") or 0, s) for s in slugs]
            accel.sort(reverse=True)
            if accel[0][0] > 0:
                winner = by_slug.get(accel[0][1], {}).get("name", "?")
                narratives.append(
                    f"{winner} is gaining the most momentum ({_fmt_delta(accel[0][0])} stars in 7d)."
                )

        # Hype ratio divergence — always surface the largest gap if meaningful
        hype_data = [
            (by_slug.get(s, {}).get("hype_ratio"), by_slug.get(s, {}).get("name", "?"), s)
            for s in slugs if by_slug.get(s, {}).get("hype_ratio") is not None
        ]
        if len(hype_data) >= 2:
            hype_data.sort(key=lambda x: x[0], reverse=True)
            top_hr, top_name, _ = hype_data[0]
            bot_hr, bot_name, _ = hype_data[-1]
            if bot_hr and bot_hr > 0:
                gap = top_hr / bot_hr
                if gap > 100:
                    narratives.append(
                        f"{top_name} has {gap:.0f}x more stars per download than "
                        f"{bot_name} — a massive hype gap."
                    )
                elif gap > 5:
                    narratives.append(
                        f"{top_name} has {gap:.0f}x more stars per download than "
                        f"{bot_name}."
                    )

        # Release staleness alert — flag outliers
        release_data = [
            (by_slug.get(s, {}).get("days_since_release"), by_slug.get(s, {}).get("name", "?"))
            for s in slugs
            if by_slug.get(s, {}).get("days_since_release") is not None
        ]
        if len(release_data) >= 2:
            release_data.sort(key=lambda x: x[0], reverse=True)
            stalest_days, stalest_name = release_data[0]
            freshest_days, freshest_name = release_data[-1]
            if stalest_days and stalest_days > 90 and (stalest_days - (freshest_days or 0)) > 60:
                narratives.append(
                    f"{stalest_name} hasn't released in {stalest_days} days while "
                    f"{freshest_name} released {freshest_days} day{'s' if freshest_days != 1 else ''} ago."
                )

        if narratives:
            lines.append("")
            lines.append("EDITORIAL NARRATIVE")
            lines.append("-" * 30)
            for n in narratives:
                lines.append(f"  {n}")

        # Dig deeper suggestions
        lines.append("")
        lines.append("DIG DEEPER")
        lines.append("-" * 30)
        for slug in slugs:
            name = by_slug.get(slug, {}).get("name", slug)
            lines.append(f"  project_pulse('{slug}')  — full profile of {name}")
            lines.append(f"  hype_check('{slug}')     — stars vs downloads reality check")

        return "\n".join(lines)

    except Exception as e:
        return f"Error comparing projects: {e}"


# ---------------------------------------------------------------------------
# Tool 19: related — HN co-occurrence analysis
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def related(project: str) -> str:
    """Show which other tracked projects appear most often alongside this one in HN discussions."""
    session = SessionLocal()
    try:
        proj, suggestions = await _find_project_or_suggest(session, project)
        if not proj:
            return _not_found_msg("Project", project, suggestions)
        proj_id = proj.id
        proj_name = proj.name
        proj_slug = proj.slug

        # Get all tracked project names/slugs for matching
        all_projects = session.query(Project.id, Project.name, Project.slug).filter(
            Project.is_active.is_(True),
            Project.id != proj_id,
        ).all()
    finally:
        session.close()

    try:
        with engine.connect() as conn:
            # Get HN post titles/URLs for this project
            result = conn.execute(text("""
                SELECT id, title FROM hn_posts WHERE project_id = :pid
            """), {"pid": proj_id})
            hn_posts = [dict(r._mapping) for r in result]

            if not hn_posts:
                return (
                    f"No HN posts found for {proj_name}.\n"
                    "This project may not have been discussed on Hacker News yet,\n"
                    "or HN data hasn't been ingested."
                )

            # For each HN post title, check which other tracked project names appear
            co_counts: dict[int, int] = {}
            for post in hn_posts:
                title = (post.get("title") or "").lower()
                for p in all_projects:
                    # Match on name or slug (case-insensitive, word-ish boundary)
                    name_lower = p.name.lower()
                    slug_lower = p.slug.lower()
                    if name_lower in title or slug_lower in title:
                        co_counts[p.id] = co_counts.get(p.id, 0) + 1

            if not co_counts:
                return (
                    f"RELATED TO: {proj_name}\n"
                    f"{'=' * 40}\n\n"
                    f"  Analyzed {len(hn_posts)} HN posts.\n"
                    f"  No other tracked projects co-occur in the same post titles.\n"
                    f"  This could mean the project occupies a unique niche,\n"
                    f"  or the HN dataset is too small for overlap."
                )

            # Sort by co-occurrence count
            sorted_co = sorted(co_counts.items(), key=lambda x: x[1], reverse=True)[:15]

            # Look up names
            proj_map = {p.id: (p.name, p.slug) for p in all_projects}

            lines = [
                f"RELATED TO: {proj_name}",
                "=" * 40,
                f"  Based on {len(hn_posts)} HN post titles",
                "",
                f"  {'#':<4} {'Project':<28} {'Co-occurrences':<16}",
                "  " + "-" * 50,
            ]
            for i, (pid, count) in enumerate(sorted_co, 1):
                pname, pslug = proj_map.get(pid, ("?", "?"))
                lines.append(f"  {i:<4} {pname:<28} {count}")

            lines.append("")
            lines.append("  Projects that frequently appear in the same HN discussions")
            lines.append("  often compete, integrate, or serve adjacent use cases.")

            return "\n".join(lines)

    except Exception as e:
        return f"Error analyzing related projects: {e}"


# ---------------------------------------------------------------------------
# Tool 20: market_map — category concentration + power law
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def market_map() -> str:
    """Category concentration, power law distribution, and lab dominance across all tracked projects."""
    try:
        with engine.connect() as conn:
            # Pull project-level summary data
            rows = _safe_mv_query(conn, """
                SELECT
                    s.name, s.slug, s.category, s.tier,
                    s.stars, s.forks, s.monthly_downloads,
                    s.commits_30d,
                    p.lab_id
                FROM mv_project_summary s
                JOIN projects p ON p.id = s.project_id
                ORDER BY s.monthly_downloads DESC NULLS LAST
            """)

            if not rows:
                return "No summary data available. Materialized views may need refreshing."

            # Lab names
            lab_rows = conn.execute(text("SELECT id, name FROM labs")).fetchall()
            lab_names = {r[0]: r[1] for r in lab_rows}

        lines = [
            "MARKET MAP",
            "=" * 70,
            "",
        ]

        # ------------------------------------------------------------------
        # CATEGORY CONCENTRATION
        # ------------------------------------------------------------------
        from collections import defaultdict
        cat_data: dict[str, list] = defaultdict(list)
        for r in rows:
            cat = r.get("category") or "uncategorized"
            cat_data[cat].append(r)

        lines.append("CATEGORY CONCENTRATION")
        lines.append("-" * 70)
        lines.append(
            f"  {'Category':<16} {'#Proj':>5}  {'Total DL/mo':>14}  "
            f"{'#1 Project':<22} {'#1 Share':>8}  {'Top 3':>6}"
        )
        lines.append("  " + "-" * 68)

        # Sort categories by total downloads descending
        cat_totals = []
        for cat, projs in cat_data.items():
            total = sum(int(p.get("monthly_downloads") or 0) for p in projs)
            cat_totals.append((cat, projs, total))
        cat_totals.sort(key=lambda x: x[2], reverse=True)

        for cat, projs, total in cat_totals:
            sorted_projs = sorted(projs, key=lambda p: int(p.get("monthly_downloads") or 0), reverse=True)
            top1 = sorted_projs[0]
            top1_dl = int(top1.get("monthly_downloads") or 0)
            top1_share = (top1_dl / total * 100) if total > 0 else 0
            top3_dl = sum(int(p.get("monthly_downloads") or 0) for p in sorted_projs[:3])
            top3_share = (top3_dl / total * 100) if total > 0 else 0
            top1_name = top1.get("name", "?")
            if len(top1_name) > 20:
                top1_name = top1_name[:19] + "…"
            lines.append(
                f"  {cat:<16} {len(projs):>5}  {_fmt_number(total):>14}  "
                f"{top1_name:<22} {top1_share:>7.1f}%  {top3_share:>5.1f}%"
            )

        # ------------------------------------------------------------------
        # POWER LAW
        # ------------------------------------------------------------------
        all_dl = [int(r.get("monthly_downloads") or 0) for r in rows]
        grand_total = sum(all_dl)

        lines.append("")
        lines.append("POWER LAW")
        lines.append("-" * 70)

        if grand_total > 0:
            for n in [5, 10, 20]:
                top_n = sum(all_dl[:n]) if len(all_dl) >= n else sum(all_dl)
                pct = top_n / grand_total * 100
                lines.append(f"  Top {n:<3} = {pct:>5.1f}% of {_fmt_number(grand_total)} total monthly downloads")
        else:
            lines.append("  No download data available.")

        # ------------------------------------------------------------------
        # LAB DOMINANCE
        # ------------------------------------------------------------------
        lab_agg: dict[int, dict] = defaultdict(lambda: {"projects": 0, "stars": 0, "downloads": 0, "commits": 0})
        indie_agg = {"projects": 0, "stars": 0, "downloads": 0, "commits": 0}

        for r in rows:
            lab_id = r.get("lab_id")
            stars = int(r.get("stars") or 0)
            dl = int(r.get("monthly_downloads") or 0)
            commits = int(r.get("commits_30d") or 0)
            if lab_id:
                lab_agg[lab_id]["projects"] += 1
                lab_agg[lab_id]["stars"] += stars
                lab_agg[lab_id]["downloads"] += dl
                lab_agg[lab_id]["commits"] += commits
            else:
                indie_agg["projects"] += 1
                indie_agg["stars"] += stars
                indie_agg["downloads"] += dl
                indie_agg["commits"] += commits

        lines.append("")
        lines.append("LAB DOMINANCE")
        lines.append("-" * 70)
        lines.append(
            f"  {'Lab':<22} {'#Proj':>5}  {'Stars':>10}  "
            f"{'DL/mo':>14}  {'Commits 30d':>11}"
        )
        lines.append("  " + "-" * 68)

        sorted_labs = sorted(lab_agg.items(), key=lambda x: x[1]["downloads"], reverse=True)
        for lab_id, agg in sorted_labs:
            lab_name = lab_names.get(lab_id, f"Lab {lab_id}")
            if len(lab_name) > 20:
                lab_name = lab_name[:19] + "…"
            lines.append(
                f"  {lab_name:<22} {agg['projects']:>5}  "
                f"{_fmt_number(agg['stars']):>10}  "
                f"{_fmt_number(agg['downloads']):>14}  "
                f"{_fmt_number(agg['commits']):>11}"
            )
        if indie_agg["projects"] > 0:
            lines.append(
                f"  {'(Independent)':<22} {indie_agg['projects']:>5}  "
                f"{_fmt_number(indie_agg['stars']):>10}  "
                f"{_fmt_number(indie_agg['downloads']):>14}  "
                f"{_fmt_number(indie_agg['commits']):>11}"
            )

        # ------------------------------------------------------------------
        # KEY NARRATIVES (auto-generated)
        # ------------------------------------------------------------------
        lines.append("")
        lines.append("KEY NARRATIVES")
        lines.append("-" * 70)

        # Narrative 1: Biggest category leader
        if cat_totals:
            biggest_cat, biggest_projs, biggest_total = cat_totals[0]
            top_proj = sorted(biggest_projs, key=lambda p: int(p.get("monthly_downloads") or 0), reverse=True)[0]
            top_proj_dl = int(top_proj.get("monthly_downloads") or 0)
            share = (top_proj_dl / biggest_total * 100) if biggest_total > 0 else 0
            lines.append(
                f"  • {top_proj['name']} is {share:.0f}% of {biggest_cat} downloads "
                f"({_fmt_number(top_proj_dl)}/{_fmt_number(biggest_total)} per month)"
            )

        # Narrative 2: Stars-downloads disconnect
        for r in rows:
            stars = int(r.get("stars") or 0)
            dl = int(r.get("monthly_downloads") or 0)
            if stars > 50000 and dl == 0:
                lines.append(
                    f"  • {r['name']} has {_fmt_number(stars)} stars but 0 tracked downloads "
                    f"(binary/self-hosted distribution)"
                )
                break

        # Narrative 3: Invisible infrastructure — high downloads, low stars
        infra_candidates = [
            r for r in rows
            if int(r.get("monthly_downloads") or 0) > 1_000_000
            and int(r.get("stars") or 0) < 15_000
        ]
        if infra_candidates:
            inf = infra_candidates[0]
            lines.append(
                f"  • {inf['name']} has {_fmt_number(inf.get('monthly_downloads'))}/mo downloads "
                f"with only {_fmt_number(inf.get('stars'))} stars — invisible infrastructure"
            )

        # Narrative 4: Lab output efficiency
        if sorted_labs:
            top_lab_id, top_lab = sorted_labs[0]
            top_lab_name = lab_names.get(top_lab_id, "?")
            if top_lab["projects"] > 0:
                per_proj = top_lab["downloads"] // top_lab["projects"]
                lines.append(
                    f"  • {top_lab_name} averages {_fmt_number(per_proj)} downloads/mo "
                    f"per project ({top_lab['projects']} projects tracked)"
                )

        # Narrative 5: Small category, big ambition
        for cat, projs, total in cat_totals:
            if len(projs) >= 2 and total < 5_000_000:
                total_stars = sum(int(p.get("stars") or 0) for p in projs)
                if total_stars > 50_000:
                    lines.append(
                        f"  • {cat} has {_fmt_number(total_stars)} stars across "
                        f"{len(projs)} projects but only {_fmt_number(total)} downloads/mo "
                        f"— high interest, early adoption"
                    )
                    break

        return "\n".join(lines)

    except Exception as e:
        return f"Error generating market map: {e}"


# ---------------------------------------------------------------------------
# Tool 21: radar — early detection for untracked projects
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def radar() -> str:
    """What should you be paying attention to that isn't tracked yet? Surfaces candidate velocity, unmatched HN buzz, and fresh discoveries."""
    lines = [
        "RADAR",
        "=" * 70,
        "",
    ]

    try:
        with engine.connect() as conn:
            # ------------------------------------------------------------------
            # SECTION 1: VELOCITY ALERTS
            # ------------------------------------------------------------------
            velocity_rows = conn.execute(text("""
                SELECT id, name, github_owner, github_repo, stars, stars_previous,
                       source, discovered_at, stars_updated_at,
                       CASE
                           WHEN stars_previous IS NOT NULL AND stars_updated_at IS NOT NULL
                                AND stars_updated_at > discovered_at
                           THEN EXTRACT(EPOCH FROM (stars_updated_at - discovered_at)) / 86400.0
                           ELSE NULL
                       END AS days_elapsed
                FROM project_candidates
                WHERE status = 'pending'
                  AND stars IS NOT NULL
                ORDER BY
                    CASE
                        WHEN stars_previous IS NOT NULL THEN stars - stars_previous
                        ELSE stars
                    END DESC NULLS LAST
                LIMIT 10
            """)).fetchall()

            lines.append("VELOCITY ALERTS")
            lines.append("-" * 70)

            if velocity_rows:
                lines.append(
                    f"  {'#':<3} {'Name':<26} {'Stars':>8}  "
                    f"{'Δ Stars':>10}  {'Days':>5}  {'Velocity':>10}  {'Source':<10}"
                )
                lines.append("  " + "-" * 68)

                for i, r in enumerate(velocity_rows, 1):
                    m = r._mapping
                    name = (m["name"] or m["github_repo"] or "?")[:24]
                    stars = int(m["stars"] or 0)
                    prev = m.get("stars_previous")
                    days = m.get("days_elapsed")

                    if prev is not None and days and float(days) > 0:
                        delta = stars - int(prev)
                        velocity = f"{delta / float(days):,.0f}/d"
                        delta_str = f"+{delta:,}" if delta >= 0 else f"{delta:,}"
                        days_str = f"{float(days):.1f}"
                    else:
                        delta_str = "new"
                        velocity = "—"
                        days_str = "—"

                    source = m.get("source") or "?"
                    lines.append(
                        f"  {i:<3} {name:<26} {_fmt_number(stars):>8}  "
                        f"{delta_str:>10}  {days_str:>5}  {velocity:>10}  {source:<10}"
                    )
            else:
                lines.append("  No pending candidates with star data.")
                lines.append("  Run ingest to discover candidates from HN and GitHub trending.")

            # ------------------------------------------------------------------
            # SECTION 2: HN BUZZ (UNTRACKED)
            # ------------------------------------------------------------------
            lines.append("")
            lines.append("HN BUZZ (UNTRACKED)")
            lines.append("-" * 70)

            hn_rows = conn.execute(text("""
                SELECT title, url, points, num_comments, posted_at
                FROM hn_posts
                WHERE project_id IS NULL
                  AND posted_at >= NOW() - INTERVAL '14 days'
                  AND points > 20
                ORDER BY points DESC
                LIMIT 10
            """)).fetchall()

            if hn_rows:
                lines.append(
                    f"  {'Pts':>5}  {'Cmt':>4}  {'Title':<48}  {'Posted':<10}"
                )
                lines.append("  " + "-" * 68)

                for r in hn_rows:
                    m = r._mapping
                    title = str(m.get("title") or "")
                    if len(title) > 46:
                        title = title[:45] + "…"
                    pts = int(m.get("points") or 0)
                    cmt = int(m.get("num_comments") or 0)
                    posted = m.get("posted_at")
                    if posted:
                        delta = datetime.now(timezone.utc) - posted
                        if delta.days == 0:
                            age = f"{delta.seconds // 3600}h ago"
                        elif delta.days == 1:
                            age = "1d ago"
                        else:
                            age = f"{delta.days}d ago"
                    else:
                        age = "?"
                    lines.append(
                        f"  {pts:>5}  {cmt:>4}  {title:<48}  {age:<10}"
                    )
            else:
                lines.append("  No unmatched HN posts in the last 14 days.")
                lines.append("  This means either all posts matched to tracked projects,")
                lines.append("  or the HN ingest hasn't run recently.")

            # ------------------------------------------------------------------
            # SECTION 3: FRESH CANDIDATES
            # ------------------------------------------------------------------
            lines.append("")
            lines.append("FRESH CANDIDATES")
            lines.append("-" * 70)

            fresh_rows = conn.execute(text("""
                SELECT id, name, github_repo, description, stars, language,
                       source, source_detail, discovered_at
                FROM project_candidates
                WHERE status = 'pending'
                ORDER BY discovered_at DESC
                LIMIT 10
            """)).fetchall()

            if fresh_rows:
                for r in fresh_rows:
                    m = r._mapping
                    name = m.get("name") or m.get("github_repo") or "?"
                    stars = _fmt_number(m.get("stars"))
                    lang = m.get("language") or "?"
                    lines.append(f"  [{m['id']}] {name} ({stars} ★) — {lang}")
                    desc = str(m.get("description") or "")
                    if desc:
                        if len(desc) > 100:
                            desc = desc[:99] + "…"
                        lines.append(f"       {desc}")
                    detail = m.get("source_detail")
                    if detail:
                        lines.append(f"       Found via: {str(detail)[:80]}")
                    lines.append("")
            else:
                lines.append("  No pending candidates.")

            # ------------------------------------------------------------------
            # NARRATIVES
            # ------------------------------------------------------------------
            lines.append("NARRATIVES")
            lines.append("-" * 70)

            # Total pending candidates + star distribution
            stats = conn.execute(text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE stars > 1000) AS gt_1k,
                    COUNT(*) FILTER (WHERE stars > 10000) AS gt_10k,
                    MAX(stars) AS max_stars
                FROM project_candidates
                WHERE status = 'pending'
            """)).fetchone()

            if stats:
                sm = stats._mapping
                total = int(sm["total"] or 0)
                gt_1k = int(sm["gt_1k"] or 0)
                gt_10k = int(sm["gt_10k"] or 0)
                max_stars = int(sm["max_stars"] or 0)
                lines.append(f"  • {total} pending candidates, {gt_1k} with >1K stars, {gt_10k} with >10K stars")

            # Biggest velocity gainer
            if velocity_rows:
                top = velocity_rows[0]._mapping
                prev = top.get("stars_previous")
                days = top.get("days_elapsed")
                if prev is not None and days and float(days) > 0:
                    delta = int(top["stars"] or 0) - int(prev)
                    name = top.get("name") or top.get("github_repo") or "?"
                    lines.append(
                        f"  • {name} gained {_fmt_number(delta)} stars in "
                        f"{float(days):.1f} days — fastest candidate velocity"
                    )

            # Unmatched HN summary
            hn_unmatched_count = conn.execute(text("""
                SELECT COUNT(*) FROM hn_posts
                WHERE project_id IS NULL
                  AND posted_at >= NOW() - INTERVAL '7 days'
            """)).scalar() or 0

            hn_matched_count = conn.execute(text("""
                SELECT COUNT(*) FROM hn_posts
                WHERE project_id IS NOT NULL
                  AND posted_at >= NOW() - INTERVAL '7 days'
            """)).scalar() or 0

            total_hn = hn_unmatched_count + hn_matched_count
            if total_hn > 0:
                pct = hn_unmatched_count / total_hn * 100
                lines.append(
                    f"  • {hn_unmatched_count} of {total_hn} HN posts this week "
                    f"({pct:.0f}%) mention projects we don't track"
                )

            # Recently auto-promoted
            auto_promoted = conn.execute(text("""
                SELECT pc.name, pc.stars, pc.source, pc.reviewed_at
                FROM project_candidates pc
                WHERE pc.status = 'accepted'
                  AND pc.reviewed_at >= NOW() - INTERVAL '7 days'
                ORDER BY pc.stars DESC NULLS LAST
                LIMIT 5
            """)).fetchall()

            if auto_promoted:
                count = len(auto_promoted)
                names = ", ".join(r._mapping.get("name") or "?" for r in auto_promoted[:3])
                lines.append(
                    f"  • {count} projects auto-promoted this week: {names}"
                    + (" ..." if count > 3 else "")
                )

            lines.append("")
            lines.append("  Projects with >1K stars (HN) or >5K stars (any source)")
            lines.append("  are auto-promoted to tracking. Use set_tier() to adjust.")
            lines.append("")
            lines.append("Use deep_dive('owner/repo') to investigate, or accept_candidate(id, category) to start tracking.")

        return "\n".join(lines)

    except Exception as e:
        return f"Error generating radar: {e}"


# ---------------------------------------------------------------------------
# Tool 22: nucleation_scan — surfaces forming patterns before they're named
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def nucleation_scan(min_score: int = 30, limit: int = 20) -> str:
    """Surfaces nucleation signals — patterns forming in the AI ecosystem
    that haven't been named yet. Shows projects with unusual cross-signal
    momentum and subcategories with accelerating creation velocity.

    Projects with narrative_gap=True have strong GitHub traction but zero
    media coverage — the moment before a phase transition crystallizes.

    Use radar() for untracked candidates. Use nucleation_scan() for patterns
    in what we already track.

    Args:
        min_score: Minimum nucleation score for projects (0-100, default 30)
        limit: Max rows per section (default 20)
    """
    lines = [
        "NUCLEATION SCAN",
        "=" * 70,
        "",
    ]

    try:
        with engine.connect() as conn:
            # ------------------------------------------------------------------
            # SECTION 1: PROJECT SIGNALS
            # ------------------------------------------------------------------
            project_rows = conn.execute(text("""
                SELECT full_name, name, domain, subcategory, stars,
                       nucleation_score, narrative_gap, created_at,
                       star_delta_7d, star_velocity_zscore,
                       hn_posts_7d, hn_points_7d,
                       newsletter_mentions_7d, newsletter_feeds_7d,
                       releases_7d, commits_30d
                FROM mv_nucleation_project
                WHERE nucleation_score >= :min_score
                ORDER BY nucleation_score DESC
                LIMIT :limit
            """), {"min_score": min_score, "limit": limit}).fetchall()

            lines.append("PROJECT NUCLEATION SIGNALS")
            lines.append("-" * 70)

            if project_rows:
                lines.append(
                    f"  {'#':<3} {'Project':<30} {'Score':>5}  "
                    f"{'Δ★ 7d':>7}  {'z':>5}  {'HN':>4}  {'NL':>3}  {'Rel':>3}  {'Age':>5}  {'Gap':<5}"
                )
                lines.append("  " + "-" * 76)

                narrative_gap_count = 0
                for i, r in enumerate(project_rows, 1):
                    m = r._mapping
                    name = str(m["full_name"] or "?")
                    if len(name) > 28:
                        name = name[:27] + "…"
                    score = int(m["nucleation_score"] or 0)
                    delta = int(m["star_delta_7d"] or 0)
                    zscore = float(m["star_velocity_zscore"] or 0)
                    hn = int(m["hn_posts_7d"] or 0)
                    nl = int(m["newsletter_mentions_7d"] or 0)
                    rel = int(m["releases_7d"] or 0)
                    gap = bool(m["narrative_gap"])
                    if gap:
                        narrative_gap_count += 1

                    delta_str = f"+{delta:,}" if delta >= 0 else f"{delta:,}"
                    gap_str = "★ GAP" if gap else ""

                    # Repo age from created_at
                    created = m.get("created_at")
                    if created:
                        age_days = (datetime.now(timezone.utc) - created).days
                        if age_days >= 365:
                            age_str = f"{age_days / 365:.1f}y"
                        elif age_days >= 30:
                            age_str = f"{age_days // 30}mo"
                        else:
                            age_str = f"{age_days}d"
                    else:
                        age_str = "?"

                    lines.append(
                        f"  {i:<3} {name:<30} {score:>5}  "
                        f"{delta_str:>7}  {zscore:>5.1f}  {hn:>4}  {nl:>3}  {rel:>3}  {age_str:>5}  {gap_str:<5}"
                    )
            else:
                lines.append("  No projects above threshold.")
                lines.append("  Try lowering min_score or check that mv_nucleation_project has been refreshed.")

            # ------------------------------------------------------------------
            # SECTION 2: CATEGORY CREATION VELOCITY
            # ------------------------------------------------------------------
            lines.append("")
            lines.append("CATEGORY CREATION VELOCITY")
            lines.append("-" * 70)

            cat_rows = conn.execute(text("""
                SELECT domain, subcategory,
                       new_repos_7d, new_repos_14d, new_repo_stars_7d,
                       acceleration,
                       hn_coverage_7d, newsletter_coverage_7d,
                       creation_without_buzz
                FROM mv_nucleation_category
                WHERE new_repos_7d >= 1
                ORDER BY new_repos_7d DESC
                LIMIT :limit
            """), {"limit": limit}).fetchall()

            if cat_rows:
                lines.append(
                    f"  {'#':<3} {'Domain':<16} {'Subcategory':<30} "
                    f"{'7d':>4}  {'14d':>4}  {'★ new':>7}  {'Accel':>5}  {'Buzz':<6}"
                )
                lines.append("  " + "-" * 68)

                buzz_gap_count = 0
                for i, r in enumerate(cat_rows, 1):
                    m = r._mapping
                    domain = str(m["domain"] or "?")[:14]
                    subcat = str(m["subcategory"] or "?")
                    if len(subcat) > 28:
                        subcat = subcat[:27] + "…"
                    n7 = int(m["new_repos_7d"] or 0)
                    n14 = int(m["new_repos_14d"] or 0)
                    stars = int(m["new_repo_stars_7d"] or 0)
                    accel = m["acceleration"]
                    accel_str = f"{float(accel):.1f}x" if accel is not None else "—"
                    no_buzz = bool(m["creation_without_buzz"])
                    if no_buzz:
                        buzz_gap_count += 1
                    buzz_str = "QUIET" if no_buzz else ""

                    lines.append(
                        f"  {i:<3} {domain:<16} {subcat:<30} "
                        f"{n7:>4}  {n14:>4}  {_fmt_number(stars):>7}  {accel_str:>5}  {buzz_str:<6}"
                    )
            else:
                lines.append("  No categories with new repo creation in the last 7 days.")

            # ------------------------------------------------------------------
            # NARRATIVES
            # ------------------------------------------------------------------
            lines.append("")
            lines.append("NARRATIVES")
            lines.append("-" * 70)

            # Summary stats
            total_scored = conn.execute(text(
                "SELECT COUNT(*) FROM mv_nucleation_project"
            )).scalar() or 0

            gap_count = conn.execute(text(
                "SELECT COUNT(*) FROM mv_nucleation_project WHERE narrative_gap"
            )).scalar() or 0

            quiet_count = conn.execute(text(
                "SELECT COUNT(*) FROM mv_nucleation_category WHERE creation_without_buzz"
            )).scalar() or 0

            lines.append(f"  • {total_scored:,} projects scored, {gap_count} with narrative gaps")
            lines.append(f"  • {quiet_count} subcategories building without buzz")

            if project_rows:
                top = project_rows[0]._mapping
                lines.append(
                    f"  • Top signal: {top['full_name']} "
                    f"(score {top['nucleation_score']}, "
                    f"Δ★ {int(top['star_delta_7d'] or 0):+,})"
                )

            if cat_rows:
                top_cat = cat_rows[0]._mapping
                lines.append(
                    f"  • Fastest creation: {top_cat['domain']}/{top_cat['subcategory']} "
                    f"({top_cat['new_repos_7d']} new repos in 7d)"
                )

            lines.append("")
            lines.append("  ★ GAP = GitHub signal without media coverage (predictive edge)")
            lines.append("  QUIET = builders active, HN + newsletters silent")
            lines.append("")
            lines.append("  Use project_pulse('owner/repo') to drill into specific projects.")
            lines.append("  Use topic('theme') to explore a category in depth.")

        return "\n".join(lines)

    except Exception as e:
        return f"Error generating nucleation scan: {e}"


# ---------------------------------------------------------------------------
# Tool 23: explain — deep methodology documentation
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def explain(topic: str = None) -> str:
    """Deep documentation on how PT-Edge works. Ask about any tool, metric, algorithm, or design decision.

    Call with no topic to see all available topics.
    Call with a topic name for the full explanation, including known limitations and what we'd change.

    Examples: explain('hype_ratio'), explain('auto_promotion'), explain('data_sources')
    """
    try:
        with engine.connect() as conn:
            if not topic:
                # List all topics grouped by category
                rows = conn.execute(text("""
                    SELECT topic, category, title, summary
                    FROM methodology
                    ORDER BY category, topic
                """)).fetchall()

                if not rows:
                    return (
                        "No methodology documentation found. "
                        "Run `python -m app.methodology_seed` to populate."
                    )

                lines = [
                    "PT-EDGE METHODOLOGY",
                    "=" * 60,
                    "",
                    "Deep documentation on how every tool, metric, and algorithm works.",
                    "Each entry includes known limitations and what we'd change.",
                    "Call explain('topic_name') for the full explanation.",
                    "",
                    "We publish this so you can tell us where we're wrong.",
                    "Use submit_feedback() to push back on anything.",
                    "",
                ]

                current_category = None
                for r in rows:
                    m = r._mapping
                    cat = m["category"].upper()
                    if cat != current_category:
                        current_category = cat
                        lines.append(f"{cat}S")
                        lines.append("-" * 40)

                    lines.append(f"  {m['topic']:<28} {m['title']}")
                    lines.append(f"  {' ' * 28} {m['summary'][:80]}...")
                    lines.append("")

                return "\n".join(lines)

            # Specific topic — fuzzy match
            row = conn.execute(text("""
                SELECT topic, category, title, summary, detail, updated_at
                FROM methodology
                WHERE LOWER(topic) = LOWER(:topic)
            """), {"topic": topic.strip()}).fetchone()

            if row:
                m = row._mapping
                lines = [
                    f"{m['title']}",
                    "=" * 60,
                    f"Category: {m['category']}  |  Topic: {m['topic']}",
                    f"Last updated: {_fmt_date(m['updated_at'])}",
                    "",
                    m["detail"],
                    "",
                    "-" * 60,
                    "Think we're wrong about something? Use submit_feedback()",
                    "to tell us. We read every one.",
                ]
                return "\n".join(lines)

            # No exact match — search for partial matches
            similar = conn.execute(text("""
                SELECT topic, title FROM methodology
                WHERE LOWER(topic) LIKE '%' || LOWER(:q) || '%'
                   OR LOWER(title) LIKE '%' || LOWER(:q) || '%'
                   OR LOWER(summary) LIKE '%' || LOWER(:q) || '%'
                ORDER BY topic
                LIMIT 10
            """), {"q": topic.strip()}).fetchall()

            if similar:
                lines = [
                    f"No exact match for '{topic}'. Did you mean one of these?",
                    "",
                ]
                for s in similar:
                    sm = s._mapping
                    lines.append(f"  explain('{sm['topic']}')  — {sm['title']}")
                return "\n".join(lines)

            # Semantic fallback — find methodology entries by meaning
            from app.embeddings import is_enabled, embed_one
            embed_err = None
            if not is_enabled():
                embed_err = "OPENAI_API_KEY not configured on this server"
            else:
                vec = await embed_one(topic.strip())
                if vec is not None:
                    sem_rows = conn.execute(text("""
                        SELECT topic, title, summary,
                               1 - (embedding <=> :vec) AS similarity
                        FROM methodology
                        WHERE embedding IS NOT NULL
                        ORDER BY embedding <=> :vec
                        LIMIT 3
                    """), {"vec": str(vec)}).fetchall()

                    sem_matches = [r._mapping for r in sem_rows]
                    if sem_matches:
                        lines = [
                            f"No exact match for '{topic}', but found semantically related entries:",
                            "",
                        ]
                        for sm in sem_matches:
                            lines.append(
                                f"  explain('{sm['topic']}')  — {sm['title']} "
                                f"(similarity: {float(sm['similarity']):.0%})"
                            )
                            lines.append(f"    {sm['summary'][:100]}...")
                            lines.append("")
                        return "\n".join(lines)
                else:
                    embed_err = "Embedding API call failed (check server logs)"

            no_match = f"No methodology entry found for '{topic}'."
            if embed_err:
                no_match += f"\n⚠ Semantic search unavailable: {embed_err}"
            no_match += "\nCall explain() with no arguments to see all available topics."
            return no_match

    except Exception as e:
        return f"Error querying methodology: {e}"


# ---------------------------------------------------------------------------
# Tool 22b: briefing
# ---------------------------------------------------------------------------

def _lookup_current(conn, slug: str, metric: str):
    """Look up current value for a project metric used in briefing evidence."""
    # Try projects → ai_repos FK first (direct link)
    row = conn.execute(text("""
        SELECT a.stars, a.downloads_monthly
        FROM projects p
        JOIN ai_repos a ON a.id = p.ai_repo_id
        WHERE LOWER(p.slug) = LOWER(:slug)
        LIMIT 1
    """), {"slug": slug}).fetchone()

    if row and row._mapping.get(metric) is not None:
        return row._mapping[metric]

    # Try ai_repos by name
    row = conn.execute(text("""
        SELECT stars, downloads_monthly
        FROM ai_repos
        WHERE LOWER(name) = LOWER(:slug)
        LIMIT 1
    """), {"slug": slug}).fetchone()

    if row and row._mapping.get(metric) is not None:
        return row._mapping[metric]

    # Try with full_name pattern (owner/repo)
    row = conn.execute(text("""
        SELECT stars, downloads_monthly
        FROM ai_repos
        WHERE LOWER(full_name) LIKE '%/' || LOWER(:slug)
        LIMIT 1
    """), {"slug": slug}).fetchone()

    if row and row._mapping.get(metric) is not None:
        return row._mapping[metric]

    # Fall back to tracked projects
    row = conn.execute(text("""
        SELECT gs.stars, ds.total_downloads as downloads_monthly
        FROM projects p
        LEFT JOIN LATERAL (
            SELECT stars FROM github_snapshots
            WHERE project_id = p.id ORDER BY snapshot_date DESC LIMIT 1
        ) gs ON true
        LEFT JOIN LATERAL (
            SELECT SUM(download_count) as total_downloads FROM download_snapshots
            WHERE project_id = p.id AND snapshot_date = (
                SELECT MAX(snapshot_date) FROM download_snapshots WHERE project_id = p.id
            )
        ) ds ON true
        WHERE LOWER(p.slug) = LOWER(:slug)
        LIMIT 1
    """), {"slug": slug}).fetchone()

    if row and row._mapping.get(metric) is not None:
        return row._mapping[metric]

    return None


@mcp.tool()
@track_usage
async def briefing(topic: str = None, domain: str = "") -> str:
    """Curated intelligence briefings on the AI ecosystem. Distilled findings
    from data analysis — not raw data, but interpretive conclusions backed
    by evidence.

    Call with no arguments to see all available briefings.
    Call with a topic for the full briefing with live data comparison.
    Filter by domain: mcp, agents, rag, llm-tools, etc.

    Examples: briefing('mcp-framework-dominance'), briefing(domain='mcp'), briefing('gateway')
    """
    try:
        with engine.connect() as conn:
            # ---------------------------------------------------------------
            # Listing mode — no topic
            # ---------------------------------------------------------------
            if not topic:
                where = "WHERE LOWER(domain) = LOWER(:domain)" if domain else ""
                params = {"domain": domain} if domain else {}
                rows = conn.execute(text(f"""
                    SELECT slug, domain, title, summary, verified_at
                    FROM briefings
                    {where}
                    ORDER BY domain, slug
                """), params).fetchall()

                if not rows:
                    if domain:
                        return f"No briefings found for domain '{domain}'. Call briefing() to see all domains."
                    return (
                        "No briefings found. "
                        "Run `python -m app.briefings_seed` to populate."
                    )

                lines = [
                    "ECOSYSTEM BRIEFINGS",
                    "=" * 60,
                    "",
                    "Curated intelligence on the AI ecosystem. Each briefing is a",
                    "distilled finding backed by specific data points.",
                    "",
                    "Call briefing('slug') for the full analysis with live data deltas.",
                    "",
                ]

                current_domain = None
                for r in rows:
                    m = r._mapping
                    d = m["domain"].upper()
                    if d != current_domain:
                        current_domain = d
                        lines.append(f"{d}")
                        lines.append("-" * 40)

                    # Freshness indicator
                    verified = m["verified_at"]
                    if verified:
                        from datetime import datetime, timezone
                        age_days = (datetime.now(timezone.utc) - verified).days
                        if age_days <= 7:
                            freshness = "current"
                        elif age_days <= 30:
                            freshness = f"{age_days}d ago"
                        else:
                            freshness = f"{age_days}d ago — may be stale"
                    else:
                        freshness = "unknown"

                    lines.append(f"  {m['slug']}")
                    lines.append(f"    {m['title']}")
                    lines.append(f"    Verified: {freshness}")
                    lines.append("")

                # Also show landscape briefs if they exist
                try:
                    lb_rows = conn.execute(text("""
                        SELECT layer, title, generated_at FROM landscape_briefs
                        ORDER BY layer
                    """)).fetchall()
                    if lb_rows:
                        lines.append("")
                        lines.append("LANDSCAPE BRIEFS (weekly, per ecosystem layer)")
                        lines.append("=" * 60)
                        lines.append("")
                        lines.append("Auto-generated weekly overviews of ecosystem layers.")
                        lines.append("Call briefing('layer-name') for the full analysis.")
                        lines.append("")
                        for lb in lb_rows:
                            lm = lb._mapping
                            lines.append(f"  {lm['layer']}")
                            lines.append(f"    {lm['title']}")
                            lines.append(f"    Generated: {_fmt_date(lm['generated_at'])}")
                            lines.append("")
                except Exception:
                    pass  # landscape_briefs table may not exist yet

                return "\n".join(lines)

            # ---------------------------------------------------------------
            # Detail mode — specific topic
            # ---------------------------------------------------------------

            # 0. Check landscape_briefs first
            lb_row = None
            try:
                lb_row = conn.execute(text("""
                    SELECT layer, title, summary, evidence, generated_at
                    FROM landscape_briefs
                    WHERE LOWER(layer) = LOWER(:topic)
                """), {"topic": topic.strip()}).fetchone()
            except Exception:
                pass

            if lb_row:
                lm = lb_row._mapping
                lines = [
                    f"LANDSCAPE BRIEF: {lm['title']}",
                    f"Layer: {lm['layer']}  |  Generated: {_fmt_date(lm['generated_at'])}",
                    "=" * 60,
                    "",
                    lm["summary"],
                ]
                return "\n".join(lines)

            # 1. Exact slug match
            row = conn.execute(text("""
                SELECT slug, domain, title, summary, detail, evidence, source_article, verified_at
                FROM briefings
                WHERE LOWER(slug) = LOWER(:topic)
            """), {"topic": topic.strip()}).fetchone()

            if not row:
                # 2. Partial match on slug, title, or summary
                # Also search landscape_briefs
                lb_similar = []
                try:
                    lb_similar = conn.execute(text("""
                        SELECT layer AS slug, title FROM landscape_briefs
                        WHERE LOWER(layer) LIKE '%' || LOWER(:q) || '%'
                           OR LOWER(title) LIKE '%' || LOWER(:q) || '%'
                        ORDER BY layer
                        LIMIT 5
                    """), {"q": topic.strip()}).fetchall()
                except Exception:
                    pass

                similar = conn.execute(text("""
                    SELECT slug, title FROM briefings
                    WHERE LOWER(slug) LIKE '%' || LOWER(:q) || '%'
                       OR LOWER(title) LIKE '%' || LOWER(:q) || '%'
                       OR LOWER(summary) LIKE '%' || LOWER(:q) || '%'
                    ORDER BY slug
                    LIMIT 10
                """), {"q": topic.strip()}).fetchall()

                if similar or lb_similar:
                    lines = [
                        f"No exact match for '{topic}'. Did you mean one of these?",
                        "",
                    ]
                    for s in lb_similar:
                        sm = s._mapping
                        lines.append(f"  briefing('{sm['slug']}')  — {sm['title']}  [landscape]")
                    for s in similar:
                        sm = s._mapping
                        lines.append(f"  briefing('{sm['slug']}')  — {sm['title']}")
                    return "\n".join(lines)

                # 3. Semantic fallback
                from app.embeddings import is_enabled, embed_one
                if is_enabled():
                    vec = await embed_one(topic.strip())
                    if vec is not None:
                        sem_rows = conn.execute(text("""
                            SELECT slug, title, summary,
                                   1 - (embedding <=> :vec) AS similarity
                            FROM briefings
                            WHERE embedding IS NOT NULL
                            ORDER BY embedding <=> :vec
                            LIMIT 3
                        """), {"vec": str(vec)}).fetchall()

                        if sem_rows:
                            lines = [
                                f"No exact match for '{topic}', but found related briefings:",
                                "",
                            ]
                            for s in sem_rows:
                                sm = s._mapping
                                lines.append(
                                    f"  briefing('{sm['slug']}')  — {sm['title']} "
                                    f"(similarity: {float(sm['similarity']):.0%})"
                                )
                            return "\n".join(lines)

                return (
                    f"No briefing found for '{topic}'.\n"
                    "Call briefing() with no arguments to see all available briefings."
                )

            # Found a match — render it
            m = row._mapping
            lines = [
                m["title"],
                "=" * 60,
                f"Domain: {m['domain']}  |  Slug: {m['slug']}",
                f"Verified: {_fmt_date(m['verified_at'])}",
                "",
                m["detail"],
            ]

            # Live delta — compare evidence values to current data
            evidence = m.get("evidence") or []
            if isinstance(evidence, str):
                import json
                evidence = json.loads(evidence)

            deltas = []
            for ev in evidence:
                if ev.get("type") != "project" or not ev.get("metric"):
                    continue
                old_val = ev.get("value")
                if not isinstance(old_val, (int, float)):
                    continue
                current = _lookup_current(conn, ev["slug"], ev["metric"])
                if current is None:
                    continue
                try:
                    current = int(current)
                    old_val = int(old_val)
                    if old_val == current:
                        continue
                    pct = ((current - old_val) / old_val * 100) if old_val != 0 else 0
                    deltas.append(
                        f"  {ev['slug']}: {ev['metric']} was {_fmt_number(old_val)}, "
                        f"now {_fmt_number(current)} ({pct:+.1f}%)"
                    )
                except (ValueError, TypeError):
                    continue

            if deltas:
                verified_date = _fmt_date(m["verified_at"]) if m["verified_at"] else "unknown"
                lines.append("")
                lines.append(f"LIVE DATA DELTA (since {verified_date})")
                lines.append("-" * 40)
                lines.extend(deltas)

            if m.get("source_article"):
                lines.append("")
                lines.append(f"Source article: {m['source_article']}")

            lines.append("")
            lines.append("-" * 60)
            lines.append("Think we're wrong? Use submit_feedback() to push back.")

            return "\n".join(lines)

    except Exception as e:
        return f"Error querying briefings: {e}"


# ---------------------------------------------------------------------------
# Tool 23: topic
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def topic(query: str) -> str:
    """Search across the entire AI ecosystem by topic — tracked projects, candidates, and HN posts. Use for conceptual queries like 'MCP', 'vector databases', 'code generation', 'reasoning models'.

    Examples:
      topic('MCP')               — everything related to Model Context Protocol
      topic('vector databases')  — vector DB projects, HN discussion, candidates
    """
    lines = [
        f"TOPIC: {query}",
        "=" * 60,
    ]

    candidate_rows = []
    hn_posts = []

    # 1. TRACKED PROJECTS — semantic search
    semantic_results, embed_error = await _semantic_project_search(query, limit=10)

    lines.append("")
    lines.append("TRACKED PROJECTS (by semantic similarity)")
    lines.append("-" * 40)

    if embed_error:
        lines.append(f"  ⚠ Semantic search unavailable: {embed_error}")
        lines.append("  Falling back to keyword matching.")
        lines.append("")

        # Fallback to keyword search
        session = SessionLocal()
        try:
            keyword_matches = session.query(Project).filter(
                (Project.name.ilike(f"%{query}%")) |
                (Project.description.ilike(f"%{query}%")) |
                (Project.slug.ilike(f"%{query}%"))
            ).limit(10).all()
            if keyword_matches:
                for p in keyword_matches:
                    desc = (p.description or "")[:80]
                    lines.append(f"  [{p.category}] {p.name:<28} {desc}")
            else:
                lines.append("  No matching tracked projects found.")
        finally:
            session.close()
    elif semantic_results:
        for r in semantic_results:
            desc = (r.get("description") or "")[:80]
            lines.append(
                f"  [{r['category']}] {r['name']:<28} "
                f"(similarity: {r['similarity']:.0%})  {desc}"
            )
    else:
        lines.append("  No matching tracked projects found.")

    # Also search by topic array — always runs independently
    lines.append("")
    lines.append("PROJECTS WITH MATCHING GITHUB TOPICS")
    lines.append("-" * 40)
    try:
        with engine.connect() as conn:
            topic_rows = conn.execute(text("""
                SELECT slug, name, category, description, topics
                FROM projects
                WHERE topics IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM unnest(topics) t
                      WHERE t ILIKE '%' || :q || '%'
                  )
                ORDER BY name
                LIMIT 10
            """), {"q": query.strip()}).fetchall()

            # Deduplicate against projects already shown above
            seen_slugs = {r["slug"] for r in semantic_results} if semantic_results else set()
            topic_matches = [
                r._mapping for r in topic_rows
                if r._mapping["slug"] not in seen_slugs
            ]

            if topic_matches:
                for m in topic_matches:
                    topics_str = ", ".join(m["topics"][:5]) if m["topics"] else ""
                    lines.append(
                        f"  [{m['category']}] {m['name']:<28} topics: {topics_str}"
                    )
            else:
                lines.append("  No projects with matching GitHub topics.")
    except Exception as e:
        logger.debug(f"Topic array search error: {e}")
        lines.append("  Could not query GitHub topics.")

    # 2. CANDIDATES — keyword + topic search
    lines.append("")
    lines.append("PENDING CANDIDATES")
    lines.append("-" * 40)
    try:
        with engine.connect() as conn:
            candidate_rows = conn.execute(text("""
                SELECT name, description, stars, language, topics, source
                FROM project_candidates
                WHERE status = 'pending'
                  AND (
                      name ILIKE '%' || :q || '%'
                      OR description ILIKE '%' || :q || '%'
                      OR EXISTS (
                          SELECT 1 FROM unnest(topics) t
                          WHERE t ILIKE '%' || :q || '%'
                      )
                  )
                ORDER BY stars DESC NULLS LAST
                LIMIT 10
            """), {"q": query.strip()}).fetchall()

            if candidate_rows:
                for r in candidate_rows:
                    m = r._mapping
                    topics_str = ""
                    if m.get("topics"):
                        topics_str = f" [{', '.join(m['topics'][:3])}]"
                    lines.append(
                        f"  {m['name'] or '?':<28} "
                        f"stars: {_fmt_number(m.get('stars'))}  "
                        f"source: {m.get('source')}{topics_str}"
                    )
            else:
                lines.append("  No matching candidates.")
    except Exception as e:
        lines.append(f"  Could not query candidates: {e}")

    # 3. HN DISCUSSION
    lines.append("")
    lines.append("RECENT HN DISCUSSION")
    lines.append("-" * 40)
    session = SessionLocal()
    try:
        hn_posts = (
            session.query(HNPost)
            .filter(HNPost.title.ilike(f"%{query}%"))
            .order_by(HNPost.posted_at.desc())
            .limit(10)
            .all()
        )
        if hn_posts:
            for post in hn_posts:
                lines.append(
                    f"  {post.points:>5} pts  {post.num_comments:>4} comments  "
                    f"{_fmt_date(post.posted_at)}  {post.title[:70]}"
                )
        else:
            lines.append("  No HN posts found matching this topic.")
    finally:
        session.close()

    # 3b. V2EX DISCUSSION (Chinese dev community)
    lines.append("")
    lines.append("V2EX DISCUSSION (Chinese dev community)")
    lines.append("-" * 40)
    session = SessionLocal()
    try:
        v2ex_posts = (
            session.query(V2EXPost)
            .filter(V2EXPost.title.ilike(f"%{query}%"))
            .order_by(V2EXPost.posted_at.desc())
            .limit(10)
            .all()
        )
        if v2ex_posts:
            for post in v2ex_posts:
                lines.append(
                    f"  {post.replies:>5} replies  "
                    f"{_fmt_date(post.posted_at)}  {post.title[:70]}  "
                    f"(/{post.node_name or '?'})"
                )
        else:
            lines.append("  No V2EX posts found matching this topic.")
    finally:
        session.close()

    # 3c. NEWSLETTER COVERAGE — semantic search across extracted topics
    lines.append("")
    lines.append("NEWSLETTER COVERAGE")
    lines.append("-" * 40)
    nl_found = False
    try:
        from app.embeddings import is_enabled, embed_one
        if is_enabled():
            nl_vec = await embed_one(query)
            if nl_vec:
                with engine.connect() as conn:
                    nl_rows = conn.execute(text("""
                        SELECT title, summary, sentiment, feed_slug,
                               published_at,
                               1 - (embedding <=> :vec) AS similarity
                        FROM newsletter_mentions
                        WHERE embedding IS NOT NULL
                        ORDER BY embedding <=> :vec
                        LIMIT 5
                    """), {"vec": str(nl_vec)}).fetchall()
                    for r in nl_rows:
                        m = r._mapping
                        sim = float(m["similarity"])
                        if sim < 0.3:
                            continue
                        nl_found = True
                        sentiment_badge = f" [{m['sentiment']}]" if m.get("sentiment") else ""
                        lines.append(
                            f"  {_fmt_date(m.get('published_at'))}  "
                            f"({m['feed_slug']}) {m['title'][:70]}{sentiment_badge}  "
                            f"(similarity: {sim:.0%})"
                        )
                        if m.get("summary"):
                            lines.append(f"    {m['summary'][:200]}")
    except Exception as e:
        logger.debug(f"Newsletter search error: {e}")
    if not nl_found:
        lines.append("  No newsletter coverage found for this topic.")

    # 4. METHODOLOGY — semantic search across explanations
    lines.append("")
    lines.append("RELATED METHODOLOGY")
    lines.append("-" * 40)
    meth_found = False
    meth_embed_err = None
    try:
        from app.embeddings import is_enabled, embed_one
        if not is_enabled():
            meth_embed_err = "OPENAI_API_KEY not configured on this server"
        else:
            vec = await embed_one(query)
            if vec:
                with engine.connect() as conn:
                    meth_rows = conn.execute(text("""
                        SELECT topic, title, summary,
                               1 - (embedding <=> :vec::vector) AS similarity
                        FROM methodology
                        WHERE embedding IS NOT NULL
                        ORDER BY embedding <=> :vec::vector
                        LIMIT 3
                    """), {"vec": str(vec)}).fetchall()
                    for r in meth_rows:
                        m = r._mapping
                        meth_found = True
                        lines.append(
                            f"  explain('{m['topic']}')  — {m['title']} "
                            f"(similarity: {float(m['similarity']):.0%})"
                        )
            else:
                meth_embed_err = "Embedding API call failed (check server logs)"
    except Exception as e:
        logger.debug(f"Methodology search error: {e}")
    if not meth_found:
        if meth_embed_err:
            lines.append(f"  ⚠ Semantic search unavailable: {meth_embed_err}")
        else:
            lines.append("  No matching methodology entries.")

    # 5. FEEDBACK — community intelligence on this topic
    lines.append("")
    lines.append("ACTIVE FEEDBACK")
    lines.append("-" * 40)
    correction_session = SessionLocal()
    try:
        corrections = (
            correction_session.query(Correction)
            .filter(
                Correction.topic.ilike(f"%{query}%"),
                Correction.status == "active",
            )
            .order_by(Correction.upvotes.desc())
            .limit(5)
            .all()
        )
        if corrections:
            for c in corrections:
                lines.append(f"  [{c.id}] {c.topic} (upvotes: {c.upvotes})")
                lines.append(f"       {c.correction[:120]}")
        else:
            lines.append("  No active feedback on this topic.")
    finally:
        correction_session.close()

    # 6. NARRATIVE SUMMARY
    lines.append("")
    lines.append("SUMMARY")
    lines.append("-" * 40)
    tracked_count = len(semantic_results) if semantic_results else 0
    candidate_count = len(candidate_rows)
    hn_count = len(hn_posts)
    lines.append(
        f"  {tracked_count} related tracked projects, "
        f"{candidate_count} pending candidates, "
        f"{hn_count} HN posts"
    )
    lines.append("")
    lines.append("Use scout(category='...') to find the fastest growing projects in this space.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 24: scout — find what's growing fastest
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def scout(category: str = None, limit: int = 15) -> str:
    """Find projects growing fastest — candidates and small tracked projects ranked by stars/day.

    Uses pre-computed enrichment data from the ingest pipeline (no live API calls).
    Candidates without enrichment data yet are shown separately.
    Optional category filters by project category, name, description, or topics.
    Valid categories: agent, dataset, eval, framework, infra, library, mcp-server, model, security, tool.
    Also accepts any keyword (e.g. 'database', 'rust', 'embedding').
    """
    lines = [
        "SCOUT — fastest growing projects",
        "=" * 60,
        "",
    ]

    try:
        with engine.connect() as conn:
            # ---- Enriched candidates: have repo_created_at from ingest ----
            candidate_sql = """
                SELECT id, name, github_owner, github_repo, stars, description,
                       language, source, discovered_at, repo_created_at,
                       commit_trend, contributor_count
                FROM project_candidates
                WHERE status = 'pending'
                  AND stars > 100
                  AND repo_created_at IS NOT NULL
            """
            params: dict = {}
            if category:
                candidate_sql += """
                    AND (
                        name ILIKE '%' || :cat || '%'
                        OR description ILIKE '%' || :cat || '%'
                        OR language ILIKE :cat
                        OR EXISTS (
                            SELECT 1 FROM unnest(topics) t
                            WHERE t ILIKE '%' || :cat || '%'
                        )
                    )
                """
                params["cat"] = category
            candidate_sql += " ORDER BY stars DESC"
            candidate_rows = conn.execute(text(candidate_sql), params).fetchall()

            # ---- Unenriched candidates (not yet processed by ingest) ----
            unenriched_sql = """
                SELECT id, name, github_owner, github_repo, stars, source
                FROM project_candidates
                WHERE status = 'pending'
                  AND stars > 100
                  AND repo_created_at IS NULL
            """
            unenriched_params: dict = {}
            if category:
                unenriched_sql += """
                    AND (
                        name ILIKE '%' || :cat || '%'
                        OR description ILIKE '%' || :cat || '%'
                        OR EXISTS (
                            SELECT 1 FROM unnest(topics) t
                            WHERE t ILIKE '%' || :cat || '%'
                        )
                    )
                """
                unenriched_params["cat"] = category
            unenriched_sql += " ORDER BY stars DESC LIMIT 10"
            unenriched_rows = conn.execute(text(unenriched_sql), unenriched_params).fetchall()

            # ---- Small tracked projects with repo_created_at ----
            tracked_sql = """
                SELECT DISTINCT ON (p.id)
                       p.name, p.slug, p.category, p.github_owner, p.github_repo,
                       p.repo_created_at, gs.stars
                FROM projects p
                JOIN github_snapshots gs ON gs.project_id = p.id
                WHERE p.is_active = true
                  AND p.repo_created_at IS NOT NULL
                  AND gs.stars < 10000
                  AND gs.snapshot_date = (
                      SELECT MAX(snapshot_date) FROM github_snapshots
                      WHERE project_id = p.id
                  )
            """
            tracked_params: dict = {}
            if category:
                tracked_sql += """
                    AND (
                        p.category = :cat
                        OR p.name ILIKE '%' || :cat || '%'
                        OR p.category ILIKE '%' || :cat || '%'
                        OR EXISTS (
                            SELECT 1 FROM unnest(p.topics) t
                            WHERE t ILIKE '%' || :cat || '%'
                        )
                    )
                """
                tracked_params["cat"] = category
            tracked_sql += " ORDER BY gs.stars DESC"
            tracked_rows = conn.execute(text(tracked_sql), tracked_params).fetchall()

        # ---- Build velocity entries from cached data ----
        velocity_entries = []  # (stars_per_day, name, stars, age_days, source_label, owner_repo)

        for r in candidate_rows:
            m = r._mapping
            stars = int(m["stars"] or 0)
            name = m["name"] or m["github_repo"] or "?"
            owner_repo = f"{m['github_owner']}/{m['github_repo']}"
            source = f"candidate [{m['source']}]"
            age = max(1, (datetime.now(timezone.utc) - m["repo_created_at"]).days)
            spd = stars / age
            velocity_entries.append((spd, name, stars, age, source, owner_repo))

        for r in tracked_rows:
            m = r._mapping
            stars = int(m["stars"] or 0)
            name = m["name"] or "?"
            owner_repo = f"{m['github_owner']}/{m['github_repo']}"
            source = f"tracked [{m['category']}]"
            age = max(1, (datetime.now(timezone.utc) - m["repo_created_at"]).days)
            spd = stars / age
            velocity_entries.append((spd, name, stars, age, source, owner_repo))

        # ---- Sort and display ----
        velocity_entries.sort(reverse=True)
        display = velocity_entries[:limit]

        lines.append("FASTEST GROWING (by stars/day)")
        lines.append("-" * 60)

        if display:
            lines.append(
                f"  {'#':<3} {'Name':<28} {'Stars':>7}  "
                f"{'Age':>6}  {'★/day':>7}  {'Source':<20}"
            )
            lines.append("  " + "-" * 58)

            for i, (spd, name, stars, age, source, owner_repo) in enumerate(
                display, 1
            ):
                name_str = name[:26] if len(name) > 26 else name
                lines.append(
                    f"  {i:<3} {name_str:<28} {_fmt_number(stars):>7}  "
                    f"{age:>4}d  {spd:>7.1f}  {source:<20}"
                )
                lines.append(f"      github.com/{owner_repo}")
        else:
            lines.append("  No candidates or small projects found.")
            if category:
                lines.append(f"  Try without the category filter, or a broader term.")

        # ---- Commit intensity (local DB only) ----
        lines.append("")
        lines.append("HIGHEST COMMIT INTENSITY (commits_30d / stars × 1000)")
        lines.append("-" * 60)

        with engine.connect() as conn:
            intensity_sql = """
                SELECT p.name, p.category, gs.stars, gs.commits_30d,
                       ROUND(gs.commits_30d::numeric / GREATEST(gs.stars, 1) * 1000, 1) as ratio
                FROM projects p
                JOIN github_snapshots gs ON gs.project_id = p.id
                WHERE gs.commits_30d > 20 AND gs.stars < 50000
            """
            intensity_params: dict = {}
            if category:
                intensity_sql += """
                    AND (
                        p.name ILIKE '%' || :cat || '%'
                        OR p.category ILIKE '%' || :cat || '%'
                    )
                """
                intensity_params["cat"] = category
            intensity_sql += " ORDER BY ratio DESC LIMIT 10"
            intensity_rows = conn.execute(
                text(intensity_sql), intensity_params
            ).fetchall()

        if intensity_rows:
            lines.append(
                f"  {'Ratio':>6}  {'Commits':>8}  {'Stars':>7}  {'Project':<30}"
            )
            lines.append("  " + "-" * 55)
            for r in intensity_rows:
                m = r._mapping
                lines.append(
                    f"  {float(m['ratio']):>6.1f}  {int(m['commits_30d']):>8}  "
                    f"{_fmt_number(m['stars']):>7}  "
                    f"[{m['category']}] {m['name']}"
                )
        else:
            lines.append("  No projects with sufficient commit data yet.")

        # ---- Awaiting enrichment ----
        if unenriched_rows:
            lines.append("")
            lines.append("AWAITING ENRICHMENT (no velocity data yet)")
            lines.append("-" * 60)
            lines.append(
                f"  {'Name':<28} {'Stars':>7}  {'Source':<15}"
            )
            lines.append("  " + "-" * 52)
            for r in unenriched_rows:
                m = r._mapping
                name = (m["name"] or m["github_repo"] or "?")[:26]
                lines.append(
                    f"  {name:<28} {_fmt_number(m['stars']):>7}  "
                    f"{m['source']:<15}"
                )
            lines.append(
                f"  ({len(unenriched_rows)} candidates not yet enriched — "
                f"next ingest run will compute velocity)"
            )

        # ---- Scout notes ----
        lines.append("")
        lines.append("SCOUT NOTES")
        lines.append("-" * 60)

        if display:
            top = display[0]
            lines.append(
                f"  • Fastest: {top[1]} at {top[0]:.1f} ★/day "
                f"({_fmt_number(top[2])} stars in {top[3]} days)"
            )

            # Count by source type
            candidate_count = sum(
                1 for _, _, _, _, s, _ in display if "candidate" in s
            )
            if candidate_count:
                lines.append(
                    f"  • {candidate_count} of top {len(display)} are untracked "
                    f"candidates — consider promoting with accept_candidate()"
                )

            # Highlight any > 50 stars/day
            rockets = [
                (n, s) for s, n, _, _, _, _ in display if s > 50
            ]
            if rockets:
                names = ", ".join(n for n, _ in rockets)
                lines.append(f"  • 🚀 Exponential: {names} (>50 ★/day)")

        lines.append("")
        lines.append("Use deep_dive('owner/repo') for full profiles, or accept_candidate(id, category) to track.")

        return "\n".join(lines)

    except Exception as e:
        return f"Error running scout: {e}"


# ---------------------------------------------------------------------------
# Tool 26: hn_pulse — HN discourse intelligence
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def hn_pulse(query: str = None, days: int = 14) -> str:
    """HN discourse intelligence. What is the community actually talking about?

    Without a query: top discussions, trending topics, and discussion quality metrics.
    With a query: focused analysis of HN discourse around a specific topic/project.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    lines = [
        f"HN PULSE (last {days} days)",
        "=" * 60,
    ]

    try:
        with engine.connect() as conn:
            if query:
                # FOCUSED MODE: discourse around a specific topic
                posts = conn.execute(text("""
                    SELECT title, url, points, num_comments, posted_at, post_type,
                           project_id
                    FROM hn_posts
                    WHERE title ILIKE '%' || :q || '%'
                      AND posted_at >= :cutoff
                    ORDER BY points DESC
                    LIMIT 20
                """), {"q": query.strip(), "cutoff": cutoff}).fetchall()

                lines.append(f"  Topic: {query}")
                lines.append(f"  Posts found: {len(posts)}")

                if posts:
                    total_points = sum(int(r._mapping["points"] or 0) for r in posts)
                    total_comments = sum(int(r._mapping["num_comments"] or 0) for r in posts)
                    avg_points = total_points / len(posts)
                    avg_comments = total_comments / len(posts)
                    comment_density = total_comments / max(total_points, 1)

                    lines.append("")
                    lines.append("ENGAGEMENT SUMMARY")
                    lines.append("-" * 40)
                    lines.append(f"  Total posts:      {len(posts)}")
                    lines.append(f"  Total points:     {total_points:,}")
                    lines.append(f"  Total comments:   {total_comments:,}")
                    lines.append(f"  Avg points:       {avg_points:.0f}")
                    lines.append(f"  Avg comments:     {avg_comments:.0f}")
                    lines.append(f"  Comment density:  {comment_density:.2f} comments/point")

                    # Post type breakdown
                    show_count = sum(1 for r in posts if r._mapping["post_type"] == "show")
                    ask_count = sum(1 for r in posts if r._mapping["post_type"] == "ask")
                    link_count = len(posts) - show_count - ask_count
                    lines.append("")
                    lines.append(f"  Show HN: {show_count}  |  Ask HN: {ask_count}  |  Links: {link_count}")

                    # Top posts
                    lines.append("")
                    lines.append("TOP POSTS")
                    lines.append("-" * 40)
                    for r in posts[:10]:
                        m = r._mapping
                        tracked = " [tracked]" if m["project_id"] else ""
                        lines.append(
                            f"  {int(m['points'] or 0):>5} pts  {int(m['num_comments'] or 0):>4} cmt  "
                            f"[{m['post_type']}] {m['title'][:65]}{tracked}"
                        )

                    # Discussion quality signal
                    high_discussion = [
                        r for r in posts
                        if (int(r._mapping["num_comments"] or 0) >
                            int(r._mapping["points"] or 0) * 0.5)
                    ]
                    if high_discussion:
                        lines.append("")
                        lines.append("DISCUSSION QUALITY")
                        lines.append("-" * 40)
                        lines.append(
                            f"  {len(high_discussion)} posts have high comment density "
                            f"(>0.5 comments per point)"
                        )
                        lines.append(
                            "  High density often signals controversy or genuine technical debate:"
                        )
                        sorted_disc = sorted(
                            high_discussion,
                            key=lambda x: int(x._mapping["num_comments"] or 0),
                            reverse=True,
                        )
                        for r in sorted_disc[:3]:
                            m = r._mapping
                            lines.append(
                                f"    {int(m['num_comments'] or 0)} comments on "
                                f"{int(m['points'] or 0)} pts: {m['title'][:60]}"
                            )
                else:
                    lines.append("")
                    lines.append("  No HN posts found for this topic in the period.")

            else:
                # OVERVIEW MODE: general HN discourse health
                lines.append("")
                lines.append("TOP DISCUSSIONS")
                lines.append("-" * 40)
                top = conn.execute(text("""
                    SELECT title, points, num_comments, post_type, posted_at
                    FROM hn_posts
                    WHERE posted_at >= :cutoff
                    ORDER BY points DESC
                    LIMIT 10
                """), {"cutoff": cutoff}).fetchall()
                for r in top:
                    m = r._mapping
                    lines.append(
                        f"  {int(m['points'] or 0):>5} pts  {int(m['num_comments'] or 0):>4} cmt  "
                        f"[{m['post_type']}] {m['title'][:65]}"
                    )

                # Most discussed (by comment count)
                lines.append("")
                lines.append("MOST DISCUSSED (by comments)")
                lines.append("-" * 40)
                discussed = conn.execute(text("""
                    SELECT title, points, num_comments, post_type
                    FROM hn_posts
                    WHERE posted_at >= :cutoff
                    ORDER BY num_comments DESC
                    LIMIT 10
                """), {"cutoff": cutoff}).fetchall()
                for r in discussed:
                    m = r._mapping
                    lines.append(
                        f"  {int(m['num_comments'] or 0):>5} cmt  {int(m['points'] or 0):>4} pts  "
                        f"[{m['post_type']}] {m['title'][:65]}"
                    )

                # Show HN launches
                lines.append("")
                lines.append("SHOW HN LAUNCHES")
                lines.append("-" * 40)
                shows = conn.execute(text("""
                    SELECT title, points, num_comments, posted_at
                    FROM hn_posts
                    WHERE posted_at >= :cutoff AND post_type = 'show'
                    ORDER BY points DESC
                    LIMIT 5
                """), {"cutoff": cutoff}).fetchall()
                if shows:
                    for r in shows:
                        m = r._mapping
                        lines.append(
                            f"  {int(m['points'] or 0):>5} pts  {int(m['num_comments'] or 0):>4} cmt  "
                            f"{m['title'][:65]}"
                        )
                else:
                    lines.append("  No Show HN posts in this period.")

                # Daily volume trend
                lines.append("")
                lines.append("DAILY POST VOLUME")
                lines.append("-" * 40)
                daily = conn.execute(text("""
                    SELECT posted_at::date AS day,
                           COUNT(*) AS posts,
                           SUM(points) AS total_points,
                           SUM(num_comments) AS total_comments
                    FROM hn_posts
                    WHERE posted_at >= :cutoff
                    GROUP BY posted_at::date
                    ORDER BY day DESC
                    LIMIT 14
                """), {"cutoff": cutoff}).fetchall()
                for r in daily:
                    m = r._mapping
                    lines.append(
                        f"  {m['day']}  {int(m['posts']):>3} posts  "
                        f"{int(m['total_points']):>6} pts  "
                        f"{int(m['total_comments']):>5} cmt"
                    )

        lines.append("")
        lines.append(
            "Use topic('...') for ecosystem-wide analysis, "
            "or radar() for untracked project discovery."
        )

    except Exception as e:
        lines.append(f"  Error: {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 25: deep_dive — full profile from PT-Edge data
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def deep_dive(identifier: str) -> str:
    """Full profile of any project or candidate using PT-Edge's cached data.
    No live API calls — all data comes from ingestion pipeline.

    Accepts owner/repo (e.g. 'microsoft/Trellis'), a tracked project name/slug,
    or a candidate name. Shows different detail levels depending on what
    PT-Edge knows about the project.
    """
    lines = []

    try:
        with engine.connect() as conn:
            # ---- Resolve identifier ----
            proj_row = None
            cand_row = None

            if "/" in identifier:
                owner, repo = identifier.split("/", 1)
                owner, repo = owner.strip(), repo.strip()

                proj_row = conn.execute(text("""
                    SELECT id, name, slug, category, description, url,
                           github_owner, github_repo, pypi_package, npm_package,
                           hf_model_id, distribution_type, topics,
                           is_active, tier_override, repo_created_at, created_at
                    FROM projects
                    WHERE github_owner ILIKE :owner AND github_repo ILIKE :repo
                """), {"owner": owner, "repo": repo}).fetchone()

                if not proj_row:
                    cand_row = conn.execute(text("""
                        SELECT id, name, github_url, github_owner, github_repo,
                               description, stars, stars_previous, language,
                               source, source_detail, topics, status,
                               discovered_at, repo_created_at,
                               commit_trend, contributor_count
                        FROM project_candidates
                        WHERE github_owner ILIKE :owner AND github_repo ILIKE :repo
                    """), {"owner": owner, "repo": repo}).fetchone()
            else:
                # Check for exact candidate name match FIRST — prevents
                # fuzzy tracked project matching from stealing candidates
                # (e.g. "mini-swe-agent" fuzzy-matching to "swe-agent")
                cand_row = conn.execute(text("""
                    SELECT id, name, github_url, github_owner, github_repo,
                           description, stars, stars_previous, language,
                           source, source_detail, topics, status,
                           discovered_at, repo_created_at,
                           commit_trend, contributor_count
                    FROM project_candidates
                    WHERE name ILIKE :name OR github_repo ILIKE :name
                    ORDER BY stars DESC NULLS LAST
                    LIMIT 1
                """), {"name": identifier}).fetchone()

                # If no exact candidate match, try tracked projects (with fuzzy)
                if not cand_row:
                    session = SessionLocal()
                    try:
                        proj, suggestions = await _find_project_or_suggest(
                            session, identifier
                        )
                        if proj:
                            proj_row = conn.execute(text("""
                                SELECT id, name, slug, category, description, url,
                                       github_owner, github_repo, pypi_package, npm_package,
                                       hf_model_id, distribution_type, topics,
                                       is_active, tier_override, repo_created_at, created_at
                                FROM projects WHERE id = :pid
                            """), {"pid": proj.id}).fetchone()
                    finally:
                        session.close()

                # If still nothing, try fuzzy candidate match as last resort
                if not proj_row and not cand_row:
                    cand_row = conn.execute(text("""
                        SELECT id, name, github_url, github_owner, github_repo,
                               description, stars, stars_previous, language,
                               source, source_detail, topics, status,
                               discovered_at, repo_created_at,
                               commit_trend, contributor_count
                        FROM project_candidates
                        WHERE name ILIKE :name OR github_repo ILIKE :name
                        ORDER BY stars DESC NULLS LAST
                        LIMIT 1
                    """), {"name": f"%{identifier}%"}).fetchone()

            # ---- Tracked project deep dive ----
            if proj_row:
                p = proj_row._mapping

                lines.append(f"DEEP DIVE: {p['name']}")
                lines.append("=" * 60)
                if p["description"]:
                    lines.append(f"  {p['description']}")
                lines.append("")

                # Identity
                lines.append("IDENTITY")
                lines.append("-" * 40)
                lines.append(f"  Slug:        {p['slug']}")
                lines.append(f"  Category:    {p['category']}")
                if p.get("tier_override"):
                    lines.append(f"  Tier:        {_fmt_tier(p['tier_override'])}")
                lines.append(f"  Dist type:   {p.get('distribution_type') or 'package'}")
                if p.get("github_owner") and p.get("github_repo"):
                    lines.append(f"  GitHub:      github.com/{p['github_owner']}/{p['github_repo']}")
                if p.get("pypi_package"):
                    lines.append(f"  PyPI:        {p['pypi_package']}")
                if p.get("npm_package"):
                    lines.append(f"  npm:         {p['npm_package']}")
                if p.get("hf_model_id"):
                    lines.append(f"  HF model:    {p['hf_model_id']}")
                if p.get("url"):
                    lines.append(f"  URL:         {p['url']}")
                if p.get("topics"):
                    lines.append(f"  Topics:      {', '.join(p['topics'][:10])}")

                # Latest GitHub snapshot
                snap = conn.execute(text("""
                    SELECT stars, forks, open_issues, watchers,
                           commits_30d, contributors, last_commit_at, license,
                           snapshot_date
                    FROM github_snapshots
                    WHERE project_id = :pid
                    ORDER BY snapshot_date DESC LIMIT 1
                """), {"pid": p["id"]}).fetchone()

                if snap:
                    s = snap._mapping
                    lines.append("")
                    lines.append(f"GITHUB METRICS (snapshot {s['snapshot_date']})")
                    lines.append("-" * 40)
                    lines.append(f"  Stars:         {_fmt_number(s['stars'])}")
                    lines.append(f"  Forks:         {_fmt_number(s['forks'])}")
                    lines.append(f"  Open issues:   {_fmt_number(s['open_issues'])}")
                    lines.append(f"  Contributors:  {_fmt_number(s['contributors'])}")
                    lines.append(f"  Commits (30d): {_fmt_number(s['commits_30d'])}")
                    if s.get("license"):
                        lines.append(f"  License:       {s['license']}")
                    if s.get("last_commit_at"):
                        lines.append(f"  Last commit:   {_fmt_date(s['last_commit_at'])}")

                    # Growth signals
                    stars = int(s["stars"] or 0)
                    if stars > 0:
                        lines.append("")
                        lines.append("GROWTH SIGNALS")
                        lines.append("-" * 40)

                        if p.get("repo_created_at"):
                            age_days = max(1, (datetime.now(timezone.utc) - p["repo_created_at"]).days)
                            spd = stars / age_days
                            lines.append(f"  Repo created:  {_fmt_date(p['repo_created_at'])[:10]}")
                            lines.append(f"  Age:           {age_days:,} days")
                            lines.append(f"  Stars/day:     {spd:.1f}")

                        forks = int(s["forks"] or 0)
                        commits = int(s["commits_30d"] or 0)
                        lines.append(f"  Fork ratio:    {forks / stars * 100:.1f}%")
                        if commits > 0:
                            intensity = commits / max(stars, 1) * 1000
                            lines.append(f"  Commit ratio:  {intensity:.1f} (commits_30d / stars × 1000)")

                    # Star history (last 7 snapshots)
                    history = conn.execute(text("""
                        SELECT snapshot_date, stars
                        FROM github_snapshots
                        WHERE project_id = :pid
                        ORDER BY snapshot_date DESC LIMIT 7
                    """), {"pid": p["id"]}).fetchall()

                    if len(history) > 1:
                        lines.append("")
                        lines.append("STAR HISTORY (recent snapshots)")
                        lines.append("-" * 40)
                        for h in reversed(history):
                            hm = h._mapping
                            lines.append(f"  {hm['snapshot_date']}  {_fmt_number(hm['stars'])}")

                # Downloads
                dl = conn.execute(text("""
                    SELECT source, downloads_daily, downloads_weekly, downloads_monthly,
                           snapshot_date
                    FROM download_snapshots
                    WHERE project_id = :pid
                    ORDER BY snapshot_date DESC LIMIT 3
                """), {"pid": p["id"]}).fetchall()

                if dl:
                    lines.append("")
                    lines.append("DOWNLOADS")
                    lines.append("-" * 40)
                    for d in dl:
                        dm = d._mapping
                        lines.append(
                            f"  [{dm['source']}] {dm['snapshot_date']}  "
                            f"daily={_fmt_number(dm['downloads_daily'])}  "
                            f"weekly={_fmt_number(dm['downloads_weekly'])}  "
                            f"monthly={_fmt_number(dm['downloads_monthly'])}"
                        )

                # Recent releases
                rels = conn.execute(text("""
                    SELECT version, title, released_at, source
                    FROM releases
                    WHERE project_id = :pid
                    ORDER BY released_at DESC LIMIT 5
                """), {"pid": p["id"]}).fetchall()

                if rels:
                    lines.append("")
                    lines.append("RECENT RELEASES")
                    lines.append("-" * 40)
                    for r in rels:
                        rm = r._mapping
                        ver = _fmt_version(rm["version"])
                        rel_date = _fmt_date(rm["released_at"])[:10]
                        title = (rm["title"] or "")[:40]
                        lines.append(f"  {ver:<20} {rel_date}  {title}")

                # HN mentions
                hn = conn.execute(text("""
                    SELECT title, points, num_comments, posted_at
                    FROM hn_posts
                    WHERE project_id = :pid
                    ORDER BY posted_at DESC LIMIT 5
                """), {"pid": p["id"]}).fetchall()

                if hn:
                    lines.append("")
                    lines.append("HACKER NEWS MENTIONS")
                    lines.append("-" * 40)
                    for h in hn:
                        hm = h._mapping
                        lines.append(
                            f"  {_fmt_date(hm['posted_at'])[:10]}  "
                            f"{hm['points']}pts  {hm['num_comments']}c  "
                            f"{(hm['title'] or '')[:50]}"
                        )

                lines.append("")
                lines.append("STATUS: Tracked project")
                lines.append(f"  Active: {'yes' if p['is_active'] else 'no'}")
                lines.append(f"  Tracked since: {_fmt_date(p['created_at'])[:10]}")

            # ---- Candidate deep dive ----
            elif cand_row:
                c = cand_row._mapping

                name = c["name"] or c["github_repo"] or "Unknown"
                lines.append(f"DEEP DIVE: {name}")
                lines.append("=" * 60)
                if c.get("description"):
                    lines.append(f"  {c['description']}")
                lines.append("")

                # Identity
                lines.append("IDENTITY")
                lines.append("-" * 40)
                lines.append(f"  GitHub:      github.com/{c['github_owner']}/{c['github_repo']}")
                lines.append(f"  Stars:       {_fmt_number(c['stars'])}")
                if c.get("stars_previous") is not None:
                    delta = (c["stars"] or 0) - (c["stars_previous"] or 0)
                    lines.append(f"  Star delta:  {_fmt_delta(delta)} (since last check)")
                if c.get("language"):
                    lines.append(f"  Language:    {c['language']}")
                lines.append(f"  Source:      {c['source']}")
                if c.get("source_detail"):
                    lines.append(f"  Source ref:  {c['source_detail'][:80]}")
                if c.get("topics"):
                    lines.append(f"  Topics:      {', '.join(c['topics'][:10])}")
                lines.append(f"  Discovered:  {_fmt_date(c['discovered_at'])[:10]}")

                # Growth signals (from enrichment)
                if c.get("repo_created_at"):
                    lines.append("")
                    lines.append("GROWTH SIGNALS")
                    lines.append("-" * 40)

                    age_days = max(1, (datetime.now(timezone.utc) - c["repo_created_at"]).days)
                    stars = int(c["stars"] or 0)
                    spd = stars / age_days
                    lines.append(f"  Repo created:    {_fmt_date(c['repo_created_at'])[:10]}")
                    lines.append(f"  Age:             {age_days:,} days")
                    lines.append(f"  Stars/day:       {spd:.1f}")

                    if c.get("commit_trend") is not None:
                        lines.append(f"  Commits (30d):   {_fmt_number(c['commit_trend'])}")
                        if stars > 0:
                            intensity = c["commit_trend"] / max(stars, 1) * 1000
                            lines.append(f"  Commit ratio:    {intensity:.1f} (commits_30d / stars × 1000)")

                    if c.get("contributor_count") is not None:
                        lines.append(f"  Contributors:    {_fmt_number(c['contributor_count'])}")
                else:
                    lines.append("")
                    lines.append("GROWTH SIGNALS")
                    lines.append("-" * 40)
                    lines.append("  Not yet enriched — next ingest run will compute velocity data.")

                # Status
                lines.append("")
                lines.append(f"STATUS: Candidate ({c['status']})")
                if c["status"] == "pending":
                    lines.append(
                        f"  Promote with: accept_candidate({c['id']}, '<category>')"
                    )
                    lines.append(
                        f"  Dismiss with: reject_candidate({c['id']})"
                    )

            # ---- Not found ----
            else:
                return (
                    f"Could not find '{identifier}' in tracked projects or candidates.\n"
                    f"Try: deep_dive('owner/repo'), a project slug, or a candidate name.\n"
                    f"Use topic('keyword') to find projects, or scout() to see candidates."
                )

        return "\n".join(lines)

    except Exception as e:
        return f"Error running deep_dive: {e}"


# ---------------------------------------------------------------------------
# AI repo discovery
# ---------------------------------------------------------------------------

AI_REPO_EMBED_DIM = 256


def _fmt_downloads(n: int) -> str:
    """Format download count: 1234567 → '1.2M', 45000 → '45K'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _name_boost(
    query: str, *fields: str,
    exact_bonus: float = 0.15, partial_bonus: float = 0.08,
) -> float:
    """Score boost when query matches a name/title field."""
    q = query.strip().lower()
    if not q:
        return 0.0
    for f in fields:
        fl = (f or "").lower()
        if q == fl or fl.endswith(f"/{q}"):
            return exact_bonus
    for f in fields:
        if q in (f or "").lower():
            return partial_bonus
    return 0.0


def _freshness_indicator(dt) -> str:
    """Return freshness string like 'last push 3 months ago' with stale warning."""
    if dt is None:
        return ""
    from datetime import datetime, timezone
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


async def _search_ai_repos(query: str, domain: str = "", limit: int = 5, offset: int = 0) -> str:
    """Core search logic shared by find_ai_tool and find_mcp_server."""
    if not query or len(query) > 500:
        return "Please provide a search query (max 500 characters)."
    limit = min(max(1, limit), 20)
    offset = min(max(0, offset), 100)
    domain = domain.strip().lower()

    from math import log10
    from app.embeddings import is_enabled, embed_one

    lines = []
    seen_ids: set[int] = set()
    results: list[dict] = []
    domain_filter = "AND domain = :domain" if domain else ""
    params_base: dict = {"domain": domain} if domain else {}

    try:
        # ---- Semantic search ----
        if is_enabled():
            vec = await embed_one(query, dimensions=AI_REPO_EMBED_DIM)
            if vec:
                with engine.connect() as conn:
                    rows = conn.execute(text(f"""
                        SELECT id, full_name, name, description, stars, forks,
                               language, topics, license, archived, domain,
                               subcategory, downloads_monthly, last_pushed_at,
                               1 - (embedding <=> :vec) AS similarity
                        FROM ai_repos
                        WHERE embedding IS NOT NULL AND archived = false
                        {domain_filter}
                        ORDER BY embedding <=> :vec
                        LIMIT :lim
                    """), {**params_base, "vec": str(vec), "lim": (offset + limit) * 3}).fetchall()

                    for r in rows:
                        m = r._mapping
                        results.append({
                            "id": m["id"],
                            "full_name": m["full_name"],
                            "name": m["name"],
                            "description": m["description"],
                            "stars": m["stars"],
                            "forks": m["forks"],
                            "language": m["language"],
                            "topics": list(m["topics"]) if m["topics"] else [],
                            "license": m["license"],
                            "domain": m["domain"],
                            "subcategory": m["subcategory"],
                            "downloads_monthly": m["downloads_monthly"] or 0,
                            "last_pushed_at": m["last_pushed_at"],
                            "similarity": float(m["similarity"]),
                        })
                        seen_ids.add(m["id"])

        # ---- Keyword fallback ----
        keyword = f"%{query.strip()[:100]}%"
        with engine.connect() as conn:
            kw_rows = conn.execute(text(f"""
                SELECT id, full_name, name, description, stars, forks,
                       language, topics, license, domain, subcategory,
                       downloads_monthly, last_pushed_at
                FROM ai_repos
                WHERE archived = false
                  AND (name ILIKE :kw OR description ILIKE :kw
                       OR full_name ILIKE :kw)
                  {domain_filter}
                ORDER BY stars DESC
                LIMIT :lim
            """), {**params_base, "kw": keyword, "lim": offset + limit}).fetchall()

            for r in kw_rows:
                m = r._mapping
                if m["id"] not in seen_ids:
                    results.append({
                        "id": m["id"],
                        "full_name": m["full_name"],
                        "name": m["name"],
                        "description": m["description"],
                        "stars": m["stars"],
                        "forks": m["forks"],
                        "language": m["language"],
                        "topics": list(m["topics"]) if m["topics"] else [],
                        "license": m["license"],
                        "domain": m["domain"],
                        "subcategory": m["subcategory"],
                        "downloads_monthly": m["downloads_monthly"] or 0,
                        "last_pushed_at": m["last_pushed_at"],
                        "similarity": 0.5,
                    })
                    seen_ids.add(m["id"])

        if not results:
            with engine.connect() as conn:
                count = conn.execute(text("SELECT COUNT(*) FROM ai_repos")).scalar()
            if count == 0:
                return "AI repo index is empty — the first ingest hasn't run yet."
            scope = f" in domain '{domain}'" if domain else ""
            return f"No AI repos found matching '{query}'{scope}. Try broader terms."

        # ---- Rank: blend semantic similarity, stars, downloads, and name match ----
        for r in results:
            star_score = log10(max(r["stars"], 1) + 1) / 5.0
            dl = r.get("downloads_monthly") or 0
            download_score = log10(max(dl, 1) + 1) / 7.0
            nb = _name_boost(query, r["name"], r["full_name"])
            r["score"] = (0.6 * r["similarity"] + 0.2 * star_score + 0.2 * download_score + nb)
            r["_name_boost"] = nb
            # Normalise license label
            if r.get("license") == "NOASSERTION":
                r["license"] = None

        # ---- Filter low-quality results ----
        results = [r for r in results if r["similarity"] >= 0.3 or r["_name_boost"] > 0]

        if not results:
            # Fallback: check builder_tools for hosted MCP endpoints
            if domain in ("", "mcp"):
                try:
                    with engine.connect() as conn:
                        bt_rows = conn.execute(text("""
                            SELECT slug, name, category, mcp_status, mcp_type,
                                   mcp_endpoint, mcp_repo_slug, mcp_npm_package
                            FROM builder_tools
                            WHERE (LOWER(slug) = LOWER(:kw) OR LOWER(name) ILIKE :kwp)
                              AND mcp_status IN ('has_official', 'has_community')
                            ORDER BY
                                CASE mcp_status WHEN 'has_official' THEN 0 ELSE 1 END
                            LIMIT 5
                        """), {"kw": query.strip(), "kwp": f"%{query.strip()[:100]}%"}).fetchall()
                    if bt_rows:
                        bt_lines = []
                        bt_lines.append(f"MCP SERVER SEARCH: \"{query}\"")
                        bt_lines.append(f"No repos found in ai_repos index, but found in builder tools registry:")
                        bt_lines.append("=" * 55)
                        for i, r in enumerate(bt_rows, 1):
                            m = r._mapping
                            type_label = (m["mcp_type"] or "").replace("_", " ")
                            bt_lines.append("")
                            bt_lines.append(f"{i}. {m['name']} ({m['slug']})  [{type_label}]")
                            if m["category"]:
                                bt_lines.append(f"   Category: {m['category']}")
                            if m["mcp_endpoint"]:
                                bt_lines.append(f"   Hosted endpoint: {m['mcp_endpoint']}")
                            if m["mcp_repo_slug"]:
                                bt_lines.append(f"   Repo: https://github.com/{m['mcp_repo_slug']}")
                            if m["mcp_npm_package"]:
                                bt_lines.append(f"   npm: {m['mcp_npm_package']}")
                        bt_lines.append("")
                        bt_lines.append("-> Next: mcp_coverage() for full MCP adoption stats")
                        return "\n".join(bt_lines)
                except Exception:
                    pass  # table may not exist yet; fall through
            scope = f" in domain '{domain}'" if domain else ""
            return f"No relevant results found for '{query}'{scope}. Try broader terms or a different domain."

        results.sort(key=lambda x: x["score"], reverse=True)
        page = results[offset:offset + limit]

        if not page and offset > 0:
            return f"No more results at offset {offset}."

        # ---- Format output ----
        with engine.connect() as conn:
            if domain:
                total = conn.execute(text(
                    "SELECT COUNT(*) FROM ai_repos WHERE archived = false AND domain = :d"
                ), {"d": domain}).scalar()
                lines.append(f"AI REPO SEARCH: \"{query}\" (domain: {domain})")
            else:
                total = conn.execute(text(
                    "SELECT COUNT(*) FROM ai_repos WHERE archived = false"
                )).scalar()
                lines.append(f"AI REPO SEARCH: \"{query}\"")
            lines.append(f"Searching {total:,} indexed repos")
            if offset > 0:
                lines.append(f"Showing results {offset + 1}–{offset + len(page)}")
            lines.append("=" * 50)

        for i, r in enumerate(page, offset + 1):
            lines.append("")
            dl = r.get("downloads_monthly") or 0
            dl_str = f" | {_fmt_downloads(dl)}/mo" if dl > 0 else ""
            lang = f" · {r['language']}" if r['language'] else ""
            lic = f" · {r['license']}" if r['license'] else ""
            if not domain:
                sub = r.get("subcategory")
                dom = f" [{r['domain']}/{sub}]" if sub else f" [{r['domain']}]"
            else:
                sub = r.get("subcategory")
                dom = f" [{sub}]" if sub else ""
            lines.append(
                f"{i}. {r['full_name']}{dom}  "
                f"(⭐ {r['stars']:,}{dl_str}{lang}{lic})"
            )
            if r["description"]:
                lines.append(f"   {r['description'][:200]}")
            if r["topics"]:
                lines.append(f"   Topics: {', '.join(r['topics'][:8])}")
            freshness = _freshness_indicator(r.get("last_pushed_at"))
            if freshness:
                lines.append(f"   {freshness}")
            lines.append(f"   https://github.com/{r['full_name']}")

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"_search_ai_repos failed: {e}")
        return "Error searching AI repos. Please try again."


@mcp.tool()
@track_usage
async def find_ai_tool(query: str, domain: str = "", limit: int = 5, offset: int = 0) -> str:
    """Find AI/ML tools and libraries by describing what you need in plain English.
    Searches ~100K indexed AI repos from GitHub. Use when someone asks
    "is there a tool for X?" or "what libraries exist for Y?".

    Optional domain filter: mcp, agents, ai-coding, rag, llm-tools, generative-ai,
    diffusion, voice-ai, nlp, computer-vision, embeddings, vector-db,
    prompt-engineering, transformers, mlops, data-engineering, ml-frameworks

    Examples:
      find_ai_tool("database query tool for postgres", domain="mcp")
      find_ai_tool("autonomous coding agent")
      find_ai_tool("PDF document chunking for RAG pipeline")
    """
    return await _search_ai_repos(query=query, domain=domain, limit=limit, offset=offset)


@mcp.tool()
@track_usage
async def find_mcp_server(query: str, limit: int = 5, offset: int = 0) -> str:
    """Find MCP servers by describing what you need in plain English.
    Use when someone asks "is there an MCP server for X?" or needs
    to connect Claude to an external service.

    Examples:
      find_mcp_server("database query tool for postgres")
      find_mcp_server("Jira issue tracker")
      find_mcp_server("file system access")
    """
    return await _search_ai_repos(query=query, domain="mcp", limit=limit, offset=offset)


@mcp.tool()
@track_usage
async def mcp_coverage(category: str = "") -> str:
    """MCP adoption across developer tools. Shows which tools have MCP servers
    and which don't, broken down by category with coverage percentages.

    Optional category filter to drill into a specific category.

    Examples:
      mcp_coverage()
      mcp_coverage(category="financial")
      mcp_coverage(category="cloud")
    """
    category = category.strip().lower()

    try:
        with engine.connect() as conn:
            total = conn.execute(text(
                "SELECT COUNT(*) FROM builder_tools"
            )).scalar() or 0

            if total == 0:
                return "Builder tools index is empty — run the builder_tools ingest first."

            cat_filter = "AND LOWER(category) = :cat" if category else ""
            params = {"cat": category} if category else {}

            # Coverage by category
            cat_rows = conn.execute(text(f"""
                SELECT
                    COALESCE(category, 'uncategorized') AS cat,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE mcp_status IN ('has_official', 'has_community')) AS has_mcp,
                    COUNT(*) FILTER (WHERE mcp_status = 'has_official') AS official,
                    COUNT(*) FILTER (WHERE mcp_status = 'has_community') AS community
                FROM builder_tools
                WHERE 1=1 {cat_filter}
                GROUP BY COALESCE(category, 'uncategorized')
                ORDER BY COUNT(*) FILTER (WHERE mcp_status IN ('has_official', 'has_community')) DESC,
                         COUNT(*) DESC
            """), params).fetchall()

            # Tools with MCP servers
            mcp_tools = conn.execute(text(f"""
                SELECT slug, name, category, mcp_status, mcp_type,
                       mcp_repo_slug, mcp_endpoint, mcp_npm_package
                FROM builder_tools
                WHERE mcp_status IN ('has_official', 'has_community')
                {cat_filter}
                ORDER BY
                    CASE mcp_status WHEN 'has_official' THEN 0 ELSE 1 END,
                    name
                LIMIT 20
            """), params).fetchall()

            # Notable gaps: popular tools without MCP (by API count)
            gap_sql = f"""
                SELECT bt.slug, bt.name, bt.category,
                       COUNT(pa.id) AS api_count
                FROM builder_tools bt
                JOIN public_apis pa ON pa.provider = bt.source_ref
                WHERE bt.mcp_status = 'none_found'
                {"AND LOWER(bt.category) = :cat" if category else ""}
                GROUP BY bt.slug, bt.name, bt.category
                ORDER BY COUNT(pa.id) DESC
                LIMIT 10
            """
            gap_tools = conn.execute(text(gap_sql), params).fetchall()

            # Recent additions (last 30 days)
            recent = conn.execute(text(f"""
                SELECT slug, name, category, mcp_type, mcp_repo_slug, mcp_endpoint
                FROM builder_tools
                WHERE mcp_status IN ('has_official', 'has_community')
                  AND mcp_checked_at > NOW() - INTERVAL '30 days'
                {cat_filter}
                ORDER BY mcp_checked_at DESC
                LIMIT 10
            """), params).fetchall()

        # ---- Format output ----
        lines = []
        lines.append("MCP COVERAGE REPORT")
        if category:
            lines.append(f"Category: {category}")
        lines.append(f"Tracking {total:,} developer tools")
        lines.append("=" * 55)

        # Summary
        total_has = sum(r._mapping["has_mcp"] for r in cat_rows)
        total_all = sum(r._mapping["total"] for r in cat_rows)
        pct = (total_has / total_all * 100) if total_all else 0
        lines.append(f"\nOverall: {total_has}/{total_all} tools have MCP servers ({pct:.1f}%)")

        # Per-category breakdown
        lines.append("\nCOVERAGE BY CATEGORY")
        lines.append("-" * 55)
        for r in cat_rows[:20]:
            m = r._mapping
            cat_pct = (m["has_mcp"] / m["total"] * 100) if m["total"] else 0
            bar_len = int(cat_pct / 5)  # 20-char bar
            bar = "#" * bar_len + "." * (20 - bar_len)
            off_label = ""
            if m["official"] > 0:
                off_label = f"  ({m['official']} official)"
            lines.append(
                f"  {m['cat']:<22} [{bar}] {cat_pct:4.0f}%  "
                f"({m['has_mcp']}/{m['total']}){off_label}"
            )

        # Tools with MCP servers
        if mcp_tools:
            lines.append(f"\nTOOLS WITH MCP SERVERS ({len(mcp_tools)})")
            lines.append("-" * 55)
            for r in mcp_tools:
                m = r._mapping
                badge = "***" if m["mcp_status"] == "has_official" else "   "
                type_label = (m["mcp_type"] or "").replace("_", " ")
                ref = ""
                if m["mcp_endpoint"]:
                    ref = m["mcp_endpoint"]
                elif m["mcp_repo_slug"]:
                    ref = f"github.com/{m['mcp_repo_slug']}"
                elif m["mcp_npm_package"]:
                    ref = f"npm: {m['mcp_npm_package']}"
                lines.append(f"  {badge} {m['name']:<25} {type_label:<18} {ref}")

        # Notable gaps
        if gap_tools:
            lines.append(f"\nNOTABLE GAPS (popular tools without MCP)")
            lines.append("-" * 55)
            for r in gap_tools:
                m = r._mapping
                lines.append(
                    f"  {m['name']:<25} [{m['category'] or '?':<15}] "
                    f"({m['api_count']} APIs indexed)"
                )

        # Recent
        if recent:
            lines.append(f"\nRECENTLY FOUND (last 30 days)")
            lines.append("-" * 55)
            for r in recent:
                m = r._mapping
                ref = m["mcp_repo_slug"] or m["mcp_endpoint"] or ""
                lines.append(f"  + {m['name']:<25} {(m['mcp_type'] or ''):<18} {ref}")

        # Footer
        lines.append("")
        lines.append("*** = official MCP server from the tool vendor")
        lines.append("")
        lines.append("-> Next: find_mcp_server('{tool}') to search for a specific tool")
        lines.append("-> Next: mcp_coverage(category='{cat}') to drill into a category")

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"mcp_coverage failed: {e}")
        return f"Error generating MCP coverage report: {e}"


# ---------------------------------------------------------------------------
# MCP health / quality score
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def mcp_health(repo: str) -> str:
    """Quality score (0-100) for an MCP server repository.

    Pass a GitHub full_name like 'owner/repo' or just the repo name.
    Returns maintenance, adoption, maturity, and community sub-scores,
    a quality tier (verified/established/emerging/experimental),
    and active risk flags.

    Examples:
      mcp_health("modelcontextprotocol/servers")
      mcp_health("punkpeye/fastmcp")
    """
    repo = repo.strip()
    if not repo:
        return "Please provide a repo name or owner/repo."

    try:
        with readonly_engine.connect() as conn:
            rows = _safe_mv_query(conn, """
                SELECT full_name, name, description, stars, forks,
                       language, license, archived, subcategory,
                       last_pushed_at, pypi_package, npm_package,
                       downloads_monthly, dependency_count, commits_30d,
                       reverse_dep_count,
                       maintenance_score, adoption_score,
                       maturity_score, community_score,
                       quality_score, quality_tier, risk_flags
                FROM mv_mcp_quality
                WHERE LOWER(full_name) = LOWER(:repo)
                   OR LOWER(name) = LOWER(:repo)
                LIMIT 1
            """, {"repo": repo})

        if not rows:
            return (
                f"MCP server '{repo}' not found in quality index.\n"
                f"Use find_mcp_server('{repo}') to check if it is indexed."
            )

        r = rows[0]
        risk = r.get("risk_flags") or []
        risk_str = ", ".join(risk) if risk else "none"

        lines = [
            f"MCP HEALTH: {r['full_name']}",
            "=" * 50,
            f"  Quality Score : {r['quality_score']} / 100",
            f"  Quality Tier  : {r['quality_tier'].upper()}",
            f"  Risk Flags    : {risk_str}",
            "",
            "SCORE BREAKDOWN",
            "-" * 30,
            f"  Maintenance   : {r['maintenance_score']} / 25  "
            f"(commits: {_fmt_number(r.get('commits_30d'))}/30d, "
            f"pushed: {_fmt_date(r.get('last_pushed_at'))})",
            f"  Adoption      : {r['adoption_score']} / 25  "
            f"(stars: {_fmt_number(r.get('stars'))}, "
            f"downloads: {_fmt_number(r.get('downloads_monthly'))}/mo, "
            f"dependents: {r.get('reverse_dep_count', 0)})",
            f"  Maturity      : {r['maturity_score']} / 25  "
            f"(license: {r.get('license') or 'none'}, "
            f"package: {'yes' if r.get('pypi_package') or r.get('npm_package') else 'no'})",
            f"  Community     : {r['community_score']} / 25  "
            f"(forks: {_fmt_number(r.get('forks'))})",
            "",
            "DETAILS",
            "-" * 30,
            f"  Subcategory   : {r.get('subcategory') or 'n/a'}",
            f"  Language      : {r.get('language') or 'n/a'}",
            f"  Archived      : {'YES' if r.get('archived') else 'No'}",
            f"  PyPI          : {r.get('pypi_package') or 'n/a'}",
            f"  npm           : {r.get('npm_package') or 'n/a'}",
        ]

        if r.get("description"):
            lines.append("")
            lines.append(f"  {str(r['description'])[:200]}")

        lines.extend([
            "",
            "-> Next: find_mcp_server() to find similar servers",
            "-> Next: mcp_coverage() for ecosystem-wide MCP adoption stats",
        ])

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"mcp_health failed for '{repo}': {e}")
        return f"Error retrieving MCP health data: {e}"


# ---------------------------------------------------------------------------
# Public API search
# ---------------------------------------------------------------------------

API_EMBED_DIM = 256


async def _search_public_apis(query: str, category: str = "", limit: int = 5, offset: int = 0) -> str:
    """Core search logic for public API discovery."""
    if not query or len(query) > 500:
        return "Please provide a search query (max 500 characters)."
    limit = min(max(1, limit), 20)
    offset = min(max(0, offset), 100)
    category = category.strip().lower()

    from math import log10
    from app.embeddings import is_enabled, embed_one

    lines = []
    seen_ids: set[int] = set()
    results: list[dict] = []
    cat_filter = "AND :cat = ANY(categories)" if category else ""
    params_base: dict = {"cat": category} if category else {}

    try:
        # ---- Semantic search ----
        if is_enabled():
            vec = await embed_one(query, dimensions=API_EMBED_DIM)
            if vec:
                with engine.connect() as conn:
                    rows = conn.execute(text(f"""
                        SELECT id, provider, service_name, title, description,
                               categories, openapi_version, spec_url,
                               1 - (embedding <=> :vec) AS similarity
                        FROM public_apis
                        WHERE embedding IS NOT NULL
                        {cat_filter}
                        ORDER BY embedding <=> :vec
                        LIMIT :lim
                    """), {**params_base, "vec": str(vec), "lim": (offset + limit) * 3}).fetchall()

                    for r in rows:
                        m = r._mapping
                        results.append({
                            "id": m["id"],
                            "provider": m["provider"],
                            "service_name": m["service_name"],
                            "title": m["title"],
                            "description": m["description"],
                            "categories": list(m["categories"]) if m["categories"] else [],
                            "openapi_version": m["openapi_version"],
                            "spec_url": m["spec_url"],
                            "similarity": float(m["similarity"]),
                        })
                        seen_ids.add(m["id"])

        # ---- Keyword fallback ----
        keyword = f"%{query.strip()[:100]}%"
        with engine.connect() as conn:
            kw_rows = conn.execute(text(f"""
                SELECT id, provider, service_name, title, description,
                       categories, openapi_version, spec_url
                FROM public_apis
                WHERE (title ILIKE :kw OR description ILIKE :kw
                       OR provider ILIKE :kw)
                  {cat_filter}
                LIMIT :lim
            """), {**params_base, "kw": keyword, "lim": offset + limit}).fetchall()

            for r in kw_rows:
                m = r._mapping
                if m["id"] not in seen_ids:
                    results.append({
                        "id": m["id"],
                        "provider": m["provider"],
                        "service_name": m["service_name"],
                        "title": m["title"],
                        "description": m["description"],
                        "categories": list(m["categories"]) if m["categories"] else [],
                        "openapi_version": m["openapi_version"],
                        "spec_url": m["spec_url"],
                        "similarity": 0.5,
                    })
                    seen_ids.add(m["id"])

        if not results:
            with engine.connect() as conn:
                count = conn.execute(text("SELECT COUNT(*) FROM public_apis")).scalar()
            if count == 0:
                return "Public API index is empty — the first ingest hasn't run yet."
            scope = f" in category '{category}'" if category else ""
            return f"No APIs found matching '{query}'{scope}. Try broader terms."

        # ---- Rank: semantic similarity + name boost ----
        for r in results:
            r["similarity"] += _name_boost(query, r["title"], r["provider"])
        results.sort(key=lambda x: x["similarity"], reverse=True)
        page = results[offset:offset + limit]

        if not page and offset > 0:
            return f"No more results at offset {offset}."

        # ---- Format output ----
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM public_apis")).scalar()
        lines.append(f"PUBLIC API SEARCH: \"{query}\"")
        if category:
            lines.append(f"Category filter: {category}")
        lines.append(f"Searching {total:,} indexed APIs")
        if offset > 0:
            lines.append(f"Showing results {offset + 1}–{offset + len(page)}")
        lines.append("=" * 50)

        for i, r in enumerate(page, offset + 1):
            lines.append("")
            # Build display key: "provider" or "provider:service"
            key = r["provider"]
            if r["service_name"]:
                key += f":{r['service_name']}"
            cats = f"  [{', '.join(r['categories'])}]" if r["categories"] else ""
            ver = f"OpenAPI {r['openapi_version']}" if r["openapi_version"] else ""
            lines.append(f"{i}. {r['title']} ({key}){cats}")
            if r["description"]:
                lines.append(f"   {r['description'][:200]}")
            if r["spec_url"]:
                lines.append(f"   Spec: {r['spec_url']}")
            if ver:
                lines.append(f"   {ver}")

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"_search_public_apis failed: {e}")
        return "Error searching public APIs. Please try again."


@mcp.tool()
@track_usage
async def find_public_api(query: str, category: str = "", limit: int = 5, offset: int = 0) -> str:
    """Find public REST APIs by describing what you need in plain English.
    Searches ~2,500 indexed APIs. Use when building integrations or looking
    for data sources. Returns endpoints, auth methods, and base URLs.

    Optional category filter: financial, cloud, analytics, social, media,
    machine_learning, security, ecommerce, iot, messaging, etc.

    Examples:
      find_public_api("payment processing")
      find_public_api("weather forecast data")
      find_public_api("send SMS messages", category="messaging")
    """
    return await _search_public_apis(query=query, category=category, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Spec-to-scaffold bridge
# ---------------------------------------------------------------------------


def _parse_spec_overview(spec: dict) -> dict:
    """Extract structured overview from an OpenAPI/Swagger spec."""
    result: dict = {}

    # Detect spec version
    oas_version = spec.get("openapi", "")
    swagger_version = spec.get("swagger", "")
    result["spec_version"] = f"OpenAPI {oas_version}" if oas_version else f"Swagger {swagger_version}"

    info = spec.get("info", {})
    result["title"] = info.get("title", "Unknown")
    result["version"] = info.get("version", "")
    desc = info.get("description", "")
    result["description"] = desc[:500] if desc else ""

    # Base URL
    if oas_version:
        servers = spec.get("servers") or []
        result["base_url"] = servers[0]["url"] if servers else ""
    else:
        host = spec.get("host", "")
        base_path = spec.get("basePath", "")
        schemes = spec.get("schemes", ["https"])
        scheme = schemes[0] if schemes else "https"
        result["base_url"] = f"{scheme}://{host}{base_path}" if host else ""

    # Auth methods
    auth_methods = []
    if oas_version:
        schemes_dict = (spec.get("components") or {}).get("securitySchemes") or {}
    else:
        schemes_dict = spec.get("securityDefinitions") or {}

    for name, scheme_def in schemes_dict.items():
        if isinstance(scheme_def, dict):
            stype = scheme_def.get("type", "")
            sin = scheme_def.get("in", "")
            flow = scheme_def.get("flow") or scheme_def.get("flows", "")
            desc_short = f"{stype}"
            if sin:
                desc_short += f" (in {sin})"
            if isinstance(flow, str) and flow:
                desc_short += f" [{flow}]"
            elif isinstance(flow, dict):
                desc_short += f" [{', '.join(flow.keys())}]"
            auth_methods.append(f"{name}: {desc_short}")
    result["auth_methods"] = auth_methods

    # Endpoints
    endpoints = []
    paths = spec.get("paths") or {}
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.startswith("x-") or method == "parameters":
                continue
            if not isinstance(op, dict):
                continue
            summary = op.get("summary") or op.get("description", "")
            endpoints.append({
                "method": method.upper(),
                "path": path,
                "summary": summary[:150] if summary else "",
            })
    result["endpoints"] = endpoints
    result["endpoint_count"] = len(endpoints)

    return result


def _flatten_schema(schema: dict | None, defs: dict, depth: int = 0, max_depth: int = 2) -> str:
    """Render a JSON Schema into compact notation for Claude."""
    if not schema or not isinstance(schema, dict):
        return "any"

    # Resolve $ref
    ref = schema.get("$ref")
    if ref:
        parts = ref.rsplit("/", 1)
        ref_name = parts[-1] if parts else ref
        if depth >= max_depth:
            return f"${ref_name}"
        resolved = defs.get(ref_name, {})
        return _flatten_schema(resolved, defs, depth + 1, max_depth)

    stype = schema.get("type", "")

    if stype == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        if not props:
            return "object"
        if depth >= max_depth:
            return "{...}"
        fields = []
        for k, v in list(props.items())[:15]:
            fields.append(f"{k}: {_flatten_schema(v, defs, depth + 1, max_depth)}")
        suffix = ", ..." if len(props) > 15 else ""
        return "{" + ", ".join(fields) + suffix + "}"

    if stype == "array":
        items = schema.get("items", {})
        return f"[{_flatten_schema(items, defs, depth + 1, max_depth)}]"

    if "enum" in schema:
        vals = schema["enum"][:5]
        return f"enum({', '.join(repr(v) for v in vals)})"

    if "oneOf" in schema or "anyOf" in schema:
        variants = schema.get("oneOf") or schema.get("anyOf") or []
        parts = [_flatten_schema(v, defs, depth + 1, max_depth) for v in variants[:3]]
        return " | ".join(parts)

    # Primitive
    fmt = schema.get("format", "")
    if fmt:
        return f"{stype}({fmt})"
    return stype or "any"


def _get_defs(spec: dict) -> dict:
    """Get schema definitions from OpenAPI 3 or Swagger 2."""
    components = spec.get("components") or {}
    schemas = components.get("schemas")
    if schemas:
        return schemas
    return spec.get("definitions") or {}


@mcp.tool()
@track_usage
async def get_api_spec(provider: str, service_name: str = "") -> str:
    """Get the cached OpenAPI spec overview for a public API.

    Returns: title, base URL, auth methods, and endpoint list.
    Use after find_public_api() to inspect an API before generating code.

    Args:
        provider: The API provider (e.g. "stripe.com", "googleapis.com")
        service_name: The service name if any (e.g. "youtube"). Empty string for single-service providers.

    Examples:
      get_api_spec("stripe.com")
      get_api_spec("googleapis.com", "youtube")
      get_api_spec("twilio.com", "api")
    """
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT provider, service_name, title, spec_json, spec_error, spec_url
                FROM public_apis
                WHERE provider = :provider AND service_name = :svc
                LIMIT 1
            """), {"provider": provider.strip(), "svc": service_name.strip()}).fetchone()

        if not row:
            return f"No API found for provider='{provider}', service_name='{service_name}'. Use find_public_api() to search first."

        m = row._mapping

        if m["spec_error"]:
            return f"Spec fetch failed for {m['title']}: {m['spec_error']}\nSpec URL: {m['spec_url'] or 'none'}"

        if not m["spec_json"]:
            return (
                f"Spec not yet cached for {m['title']}.\n"
                f"Spec URL: {m['spec_url'] or 'none'}\n"
                "The spec ingest job hasn't processed this API yet. "
                "You can fetch the spec URL directly with webfetch if needed."
            )

        spec = m["spec_json"]
        overview = _parse_spec_overview(spec)

        lines = []
        lines.append(f"API SPEC: {overview['title']} v{overview['version']}")
        lines.append(f"Spec: {overview['spec_version']}")
        lines.append("=" * 50)

        if overview["description"]:
            lines.append(f"\n{overview['description']}")

        if overview["base_url"]:
            lines.append(f"\nBase URL: {overview['base_url']}")

        if overview["auth_methods"]:
            lines.append(f"\nAuthentication ({len(overview['auth_methods'])} method{'s' if len(overview['auth_methods']) != 1 else ''}):")
            for am in overview["auth_methods"]:
                lines.append(f"  • {am}")

        lines.append(f"\nEndpoints ({overview['endpoint_count']} total):")

        for ep in overview["endpoints"][:50]:
            summary = f"  — {ep['summary']}" if ep["summary"] else ""
            lines.append(f"  {ep['method']:6s} {ep['path']}{summary}")

        if overview["endpoint_count"] > 50:
            lines.append(f"  ... and {overview['endpoint_count'] - 50} more")
            lines.append("  Use get_api_endpoints() with path_filter to drill into specific paths.")

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"get_api_spec failed: {e}")
        return "Error retrieving API spec. Please try again."


@mcp.tool()
@track_usage
async def get_api_endpoints(
    provider: str,
    service_name: str = "",
    path_filter: str = "",
) -> str:
    """Get detailed endpoint schemas for a public API.

    Returns request parameters, request body, and response schemas
    for endpoints matching the path filter. Use after get_api_spec()
    to get details on specific endpoints for code generation.

    Args:
        provider: The API provider (e.g. "stripe.com")
        service_name: The service name if any (e.g. "youtube")
        path_filter: Filter endpoints by path substring (e.g. "/charges", "/videos")

    Examples:
      get_api_endpoints("stripe.com", path_filter="/v1/charges")
      get_api_endpoints("googleapis.com", "youtube", path_filter="/videos")
    """
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT provider, service_name, title, spec_json
                FROM public_apis
                WHERE provider = :provider AND service_name = :svc
                  AND spec_json IS NOT NULL
                LIMIT 1
            """), {"provider": provider.strip(), "svc": service_name.strip()}).fetchone()

        if not row:
            return f"No cached spec for provider='{provider}', service_name='{service_name}'. Run get_api_spec() first."

        m = row._mapping
        spec = m["spec_json"]
        defs = _get_defs(spec)
        paths = spec.get("paths") or {}
        path_filter_lower = path_filter.strip().lower()

        lines = []
        key = m["provider"]
        if m["service_name"]:
            key += f":{m['service_name']}"
        lines.append(f"ENDPOINT DETAILS: {m['title']} ({key})")
        if path_filter:
            lines.append(f"Filter: {path_filter}")
        lines.append("=" * 50)

        count = 0
        for path, methods in paths.items():
            if path_filter_lower and path_filter_lower not in path.lower():
                continue
            if not isinstance(methods, dict):
                continue
            for method, op in methods.items():
                if method.startswith("x-") or method == "parameters" or not isinstance(op, dict):
                    continue
                if count >= 20:
                    lines.append(f"\n... capped at 20 endpoints. Narrow your path_filter.")
                    return "\n".join(lines)

                count += 1
                summary = op.get("summary") or op.get("description", "")
                lines.append(f"\n{'─' * 40}")
                lines.append(f"{method.upper()} {path}")
                if summary:
                    lines.append(f"  {summary[:200]}")

                # Parameters (path, query, header)
                params = op.get("parameters") or []
                path_params = methods.get("parameters") or []
                all_params = path_params + params
                if all_params:
                    lines.append("  Parameters:")
                    for p in all_params[:20]:
                        if not isinstance(p, dict):
                            continue
                        pname = p.get("name", "?")
                        pin = p.get("in", "?")
                        preq = "required" if p.get("required") else "optional"
                        ptype = _flatten_schema(p.get("schema", p), defs, max_depth=1)
                        pdesc = p.get("description", "")[:80]
                        lines.append(f"    {pname} ({pin}, {preq}): {ptype}")
                        if pdesc:
                            lines.append(f"      {pdesc}")

                # Request body (OpenAPI 3)
                req_body = op.get("requestBody")
                if req_body and isinstance(req_body, dict):
                    content = req_body.get("content") or {}
                    for ct, ct_val in content.items():
                        if not isinstance(ct_val, dict):
                            continue
                        schema = ct_val.get("schema", {})
                        lines.append(f"  Request body ({ct}):")
                        lines.append(f"    {_flatten_schema(schema, defs)}")
                        break

                # Response (show 200/201 success response)
                responses = op.get("responses") or {}
                for status in ("200", "201", "default"):
                    resp = responses.get(status)
                    if not resp or not isinstance(resp, dict):
                        continue
                    content = resp.get("content") or {}
                    for ct, ct_val in content.items():
                        if not isinstance(ct_val, dict):
                            continue
                        schema = ct_val.get("schema", {})
                        lines.append(f"  Response {status} ({ct}):")
                        lines.append(f"    {_flatten_schema(schema, defs)}")
                        break
                    if not content and "schema" in resp:
                        lines.append(f"  Response {status}:")
                        lines.append(f"    {_flatten_schema(resp['schema'], defs)}")
                    break

        if count == 0:
            if path_filter:
                return f"No endpoints matching '{path_filter}' in {m['title']}. Try a broader filter or omit path_filter."
            return f"No endpoints found in spec for {m['title']}."

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"get_api_endpoints failed: {e}")
        return "Error retrieving endpoint details. Please try again."


# ---------------------------------------------------------------------------
# Dependency graph intelligence
# ---------------------------------------------------------------------------


@mcp.tool()
@track_usage
async def get_dependencies(repo: str) -> str:
    """Get the dependency list for an indexed AI/ML repo.

    Shows direct runtime and dev dependencies from PyPI/npm.
    Use after find_ai_tool() to compare dependency weight across tools.

    Args:
        repo: The GitHub owner/repo (e.g. "langchain-ai/langchain", "fastapi/fastapi")

    Examples:
      get_dependencies("langchain-ai/langchain")
      get_dependencies("jlowin/fastmcp")
    """
    repo = repo.strip()
    if "/" not in repo:
        return "Please provide owner/repo format (e.g. 'langchain-ai/langchain')."

    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT r.id, r.full_name, r.pypi_package, r.npm_package,
                       r.dependency_count, r.deps_fetched_at
                FROM ai_repos r
                WHERE r.full_name ILIKE :name
                LIMIT 1
            """), {"name": repo}).fetchone()

        if not row:
            return f"Repo '{repo}' not found in the AI repo index. Use find_ai_tool() to search."

        m = row._mapping

        if not m["pypi_package"] and not m["npm_package"]:
            return (
                f"No published package detected for {m['full_name']}. "
                "Dependencies are only available for repos with detected PyPI/npm packages."
            )

        if not m["deps_fetched_at"]:
            pkgs = []
            if m["pypi_package"]:
                pkgs.append(f"PyPI: {m['pypi_package']}")
            if m["npm_package"]:
                pkgs.append(f"npm: {m['npm_package']}")
            return (
                f"Dependencies not yet fetched for {m['full_name']} ({', '.join(pkgs)}). "
                "The dependency ingest job hasn't processed this repo yet."
            )

        with engine.connect() as conn:
            deps = conn.execute(text("""
                SELECT dep_name, dep_spec, source, is_dev
                FROM package_deps
                WHERE repo_id = :rid
                ORDER BY is_dev, source, dep_name
            """), {"rid": m["id"]}).fetchall()

        lines = []
        lines.append(f"DEPENDENCIES: {m['full_name']}")
        pkgs = []
        if m["pypi_package"]:
            pkgs.append(f"PyPI: {m['pypi_package']}")
        if m["npm_package"]:
            pkgs.append(f"npm: {m['npm_package']}")
        lines.append(f"Packages: {', '.join(pkgs)}")
        lines.append("=" * 50)

        if not deps:
            lines.append("\nNo dependencies found (standalone package).")
            return "\n".join(lines)

        pypi_runtime = [d._mapping for d in deps if d._mapping["source"] == "pypi" and not d._mapping["is_dev"]]
        pypi_dev = [d._mapping for d in deps if d._mapping["source"] == "pypi" and d._mapping["is_dev"]]
        npm_runtime = [d._mapping for d in deps if d._mapping["source"] == "npm" and not d._mapping["is_dev"]]
        npm_dev = [d._mapping for d in deps if d._mapping["source"] == "npm" and d._mapping["is_dev"]]

        for label, group in [
            ("PyPI runtime", pypi_runtime),
            ("PyPI dev/optional", pypi_dev),
            ("npm runtime", npm_runtime),
            ("npm dev", npm_dev),
        ]:
            if not group:
                continue
            lines.append(f"\n{label} ({len(group)}):")
            for d in group:
                spec = f" {d['dep_spec']}" if d["dep_spec"] else ""
                lines.append(f"  • {d['dep_name']}{spec}")

        total_runtime = len(pypi_runtime) + len(npm_runtime)
        total_dev = len(pypi_dev) + len(npm_dev)
        lines.append(f"\nTotal: {total_runtime} runtime, {total_dev} dev/optional")

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"get_dependencies failed: {e}")
        return "Error retrieving dependencies. Please try again."


@mcp.tool()
@track_usage
async def find_dependents(package_name: str, source: str = "") -> str:
    """Find indexed AI/ML repos that depend on a given package.

    Reverse-lookup: "which repos in the index use this package?"
    Useful for understanding ecosystem adoption of a library.

    Args:
        package_name: Package name (e.g. "fastapi", "express", "langchain")
        source: Optional filter: "pypi" or "npm". Omit to search both.

    Examples:
      find_dependents("fastapi")
      find_dependents("express", source="npm")
      find_dependents("openai")
    """
    package_name = package_name.strip().lower()
    if not package_name:
        return "Please provide a package name."

    source = source.strip().lower()
    source_filter = "AND d.source = :src" if source in ("pypi", "npm") else ""
    params: dict = {"pkg": package_name}
    if source_filter:
        params["src"] = source

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT r.full_name, r.stars, r.language, r.domain, r.subcategory,
                       r.downloads_monthly, d.source, d.dep_spec, d.is_dev
                FROM package_deps d
                JOIN ai_repos r ON r.id = d.repo_id
                WHERE d.dep_name = :pkg
                  {source_filter}
                ORDER BY r.stars DESC
                LIMIT 30
            """), params).fetchall()

            if not rows:
                scope = f" ({source})" if source else ""
                return f"No indexed repos found that depend on '{package_name}'{scope}."

            total_repos = conn.execute(text("SELECT COUNT(*) FROM ai_repos")).scalar() or 0

            # Dependency count trend
            trend_rows = conn.execute(text("""
                SELECT dependent_count, snapshot_date
                FROM dep_velocity_snapshots
                WHERE dep_name = :pkg
                ORDER BY snapshot_date DESC
                LIMIT 10
            """), {"pkg": package_name}).fetchall()

            # Domain breakdown
            domain_counts: dict = {}
            for r in rows:
                d = r._mapping.get("domain") or "unknown"
                domain_counts[d] = domain_counts.get(d, 0) + 1

        lines = []
        lines.append(f"DEPENDENTS OF: {package_name}")
        if source:
            lines.append(f"Source: {source}")
        lines.append(f"Found {len(rows)} indexed repo{'s' if len(rows) != 1 else ''} (searched {total_repos:,} indexed repos)")

        # Trend
        if len(trend_rows) >= 2:
            latest = trend_rows[0]._mapping["dependent_count"]
            oldest = trend_rows[-1]._mapping["dependent_count"]
            delta = latest - oldest
            lines.append(f"Trend: {'+' if delta >= 0 else ''}{delta} dependents over {len(trend_rows)} snapshots")

        # Domain breakdown
        if len(domain_counts) > 1:
            sorted_domains = sorted(domain_counts.items(), key=lambda x: -x[1])
            domain_str = ", ".join(f"{d}: {c}" for d, c in sorted_domains[:6])
            lines.append(f"By domain: {domain_str}")

        lines.append("=" * 50)

        for i, r in enumerate(rows, 1):
            m = r._mapping
            stars = f"{m['stars']:,} stars" if m["stars"] else ""
            lang = m["language"] or ""
            domain = f"[{m['domain']}]" if m["domain"] else ""
            dev_marker = " (dev)" if m["is_dev"] else ""
            spec = f" {m['dep_spec']}" if m["dep_spec"] else ""
            dl = ""
            if m["downloads_monthly"] and m["downloads_monthly"] > 0:
                dl = f" | {_fmt_downloads(m['downloads_monthly'])}/mo"

            lines.append(f"\n{i}. {m['full_name']} {domain}")
            lines.append(f"   {stars}{dl} · {lang}")
            lines.append(f"   Depends: {package_name}{spec}{dev_marker} ({m['source']})")

        if len(rows) == 30:
            lines.append("\n... showing top 30 by stars. There may be more.")

        if len(rows) < 5:
            lines.append("\nNote: This reflects indexed coverage only, not real-world adoption.")

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"find_dependents failed: {e}")
        return "Error searching for dependents. Please try again."


# ---------------------------------------------------------------------------
# HuggingFace search (datasets + models)
# ---------------------------------------------------------------------------

HF_EMBED_DIM = 256


def _clean_hf_description(desc: str | None) -> str | None:
    """Strip markdown/HTML cruft from HuggingFace card descriptions."""
    if not desc:
        return None
    # Strip HTML tags
    cleaned = re.sub(r"<[^>]+>", "", desc)
    # Collapse markdown headings, extra whitespace
    cleaned = re.sub(r"#+\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else None


async def _search_hf_datasets(
    query: str, task: str = "", language: str = "",
    min_downloads: int = 0, limit: int = 5, offset: int = 0,
) -> str:
    """Core search logic for HuggingFace dataset discovery."""
    if not query or len(query) > 500:
        return "Please provide a search query (max 500 characters)."
    limit = min(max(1, limit), 20)
    offset = min(max(0, offset), 100)
    task = task.strip().lower()
    language = language.strip().lower()

    from math import log10
    from app.embeddings import is_enabled, embed_one

    lines = []
    seen_ids: set[int] = set()
    results: list[dict] = []

    # Build optional filters
    filters = []
    params_base: dict = {}
    if task:
        filters.append("AND :task = ANY(task_categories)")
        params_base["task"] = task
    if language:
        filters.append("AND :lang = ANY(languages)")
        params_base["lang"] = language
    if min_downloads > 0:
        filters.append("AND downloads >= :min_dl")
        params_base["min_dl"] = min_downloads
    filter_sql = " ".join(filters)

    try:
        # ---- Semantic search ----
        if is_enabled():
            vec = await embed_one(query, dimensions=HF_EMBED_DIM)
            if vec:
                with engine.connect() as conn:
                    rows = conn.execute(text(f"""
                        SELECT id, hf_id, pretty_name, description,
                               task_categories, languages, downloads, likes,
                               last_modified,
                               1 - (embedding <=> :vec) AS similarity
                        FROM hf_datasets
                        WHERE embedding IS NOT NULL
                        {filter_sql}
                        ORDER BY embedding <=> :vec
                        LIMIT :lim
                    """), {**params_base, "vec": str(vec), "lim": (offset + limit) * 3}).fetchall()

                    for r in rows:
                        m = r._mapping
                        results.append({
                            "id": m["id"],
                            "hf_id": m["hf_id"],
                            "pretty_name": m["pretty_name"],
                            "description": m["description"],
                            "task_categories": list(m["task_categories"]) if m["task_categories"] else [],
                            "languages": list(m["languages"]) if m["languages"] else [],
                            "downloads": m["downloads"] or 0,
                            "likes": m["likes"] or 0,
                            "last_modified": m["last_modified"],
                            "similarity": float(m["similarity"]),
                        })
                        seen_ids.add(m["id"])

        # ---- Keyword fallback ----
        keyword = f"%{query.strip()[:100]}%"
        with engine.connect() as conn:
            kw_rows = conn.execute(text(f"""
                SELECT id, hf_id, pretty_name, description,
                       task_categories, languages, downloads, likes,
                       last_modified
                FROM hf_datasets
                WHERE (hf_id ILIKE :kw OR pretty_name ILIKE :kw
                       OR description ILIKE :kw)
                {filter_sql}
                ORDER BY downloads DESC
                LIMIT :lim
            """), {**params_base, "kw": keyword, "lim": offset + limit}).fetchall()

            for r in kw_rows:
                m = r._mapping
                if m["id"] not in seen_ids:
                    results.append({
                        "id": m["id"],
                        "hf_id": m["hf_id"],
                        "pretty_name": m["pretty_name"],
                        "description": m["description"],
                        "task_categories": list(m["task_categories"]) if m["task_categories"] else [],
                        "languages": list(m["languages"]) if m["languages"] else [],
                        "downloads": m["downloads"] or 0,
                        "likes": m["likes"] or 0,
                        "last_modified": m["last_modified"],
                        "similarity": 0.5,
                    })
                    seen_ids.add(m["id"])

        if not results:
            with engine.connect() as conn:
                count = conn.execute(text("SELECT COUNT(*) FROM hf_datasets")).scalar()
            if count == 0:
                return "HF dataset index is empty — the first ingest hasn't run yet."
            scope_parts = []
            if task:
                scope_parts.append(f"task '{task}'")
            if language:
                scope_parts.append(f"language '{language}'")
            scope = f" ({', '.join(scope_parts)})" if scope_parts else ""
            return f"No datasets found matching '{query}'{scope}. Try broader terms."

        # ---- Rank: blend similarity, download popularity, and name match ----
        from math import log10
        for r in results:
            dl_score = log10(max(r["downloads"], 1) + 1) / 7.0
            like_score = log10(max(r["likes"], 1) + 1) / 5.0
            r["score"] = (0.6 * r["similarity"] + 0.25 * dl_score + 0.15 * like_score
                          + _name_boost(query, r["hf_id"], r["pretty_name"]))

        results.sort(key=lambda x: x["score"], reverse=True)
        page = results[offset:offset + limit]

        if not page and offset > 0:
            return f"No more results at offset {offset}."

        # ---- Format output ----
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM hf_datasets")).scalar()
        lines.append(f"DATASET SEARCH: \"{query}\"")
        scope_parts = []
        if task:
            scope_parts.append(f"task: {task}")
        if language:
            scope_parts.append(f"language: {language}")
        if scope_parts:
            lines.append(f"Filters: {', '.join(scope_parts)}")
        lines.append(f"Searching {total:,} indexed datasets")
        if offset > 0:
            lines.append(f"Showing results {offset + 1}–{offset + len(page)}")
        lines.append("=" * 50)

        for i, r in enumerate(page, offset + 1):
            lines.append("")
            name = r["pretty_name"] or r["hf_id"]
            dl_str = _fmt_downloads(r["downloads"])
            likes_str = f"♥ {r['likes']}" if r["likes"] > 0 else ""
            lines.append(f"{i}. {name}  (↓ {dl_str}{' | ' + likes_str if likes_str else ''})")
            lines.append(f"   ID: {r['hf_id']}")
            desc = _clean_hf_description(r["description"])
            if desc:
                lines.append(f"   {desc[:200]}")
            if r["task_categories"]:
                lines.append(f"   Tasks: {', '.join(r['task_categories'][:6])}")
            if r["languages"]:
                lines.append(f"   Languages: {', '.join(r['languages'][:8])}")
            lm = r.get("last_modified")
            if lm:
                try:
                    lines.append(f"   Last modified: {lm.strftime('%Y-%m-%d')}")
                except (AttributeError, ValueError):
                    pass
            lines.append(f"   https://huggingface.co/datasets/{r['hf_id']}")

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"_search_hf_datasets failed: {e}")
        return "Error searching datasets. Please try again."


@mcp.tool()
@track_usage
async def find_dataset(
    query: str, task: str = "", language: str = "",
    min_downloads: int = 0, limit: int = 5, offset: int = 0,
) -> str:
    """Find HuggingFace datasets by describing what you need in plain English.
    Searches indexed datasets from the HuggingFace Hub with download counts
    and task/language metadata.

    Optional filters:
      task: text-classification, translation, summarization, question-answering, etc.
      language: en, zh, fr, de, es, etc. (ISO 639-1 codes)
      min_downloads: minimum download count threshold

    Examples:
      find_dataset("sentiment analysis training data", task="text-classification")
      find_dataset("multilingual translation", language="zh")
      find_dataset("code generation instruction tuning")
      find_dataset("medical text", min_downloads=1000)
    """
    return await _search_hf_datasets(
        query=query, task=task, language=language,
        min_downloads=min_downloads, limit=limit, offset=offset,
    )


async def _search_hf_models(
    query: str, task: str = "", library: str = "",
    min_downloads: int = 0, limit: int = 5, offset: int = 0,
) -> str:
    """Core search logic for HuggingFace model discovery."""
    if not query or len(query) > 500:
        return "Please provide a search query (max 500 characters)."
    limit = min(max(1, limit), 20)
    offset = min(max(0, offset), 100)
    task = task.strip().lower()
    library = library.strip().lower()

    from math import log10
    from app.embeddings import is_enabled, embed_one

    lines = []
    seen_ids: set[int] = set()
    results: list[dict] = []

    # Build optional filters
    filters = []
    params_base: dict = {}
    if task:
        filters.append("AND pipeline_tag = :task")
        params_base["task"] = task
    if library:
        filters.append("AND library_name = :lib")
        params_base["lib"] = library
    if min_downloads > 0:
        filters.append("AND downloads >= :min_dl")
        params_base["min_dl"] = min_downloads
    filter_sql = " ".join(filters)

    try:
        # ---- Semantic search ----
        if is_enabled():
            vec = await embed_one(query, dimensions=HF_EMBED_DIM)
            if vec:
                with engine.connect() as conn:
                    rows = conn.execute(text(f"""
                        SELECT id, hf_id, pretty_name, description,
                               pipeline_tag, library_name, languages,
                               downloads, likes, last_modified,
                               1 - (embedding <=> :vec) AS similarity
                        FROM hf_models
                        WHERE embedding IS NOT NULL
                        {filter_sql}
                        ORDER BY embedding <=> :vec
                        LIMIT :lim
                    """), {**params_base, "vec": str(vec), "lim": (offset + limit) * 3}).fetchall()

                    for r in rows:
                        m = r._mapping
                        results.append({
                            "id": m["id"],
                            "hf_id": m["hf_id"],
                            "pretty_name": m["pretty_name"],
                            "description": m["description"],
                            "pipeline_tag": m["pipeline_tag"],
                            "library_name": m["library_name"],
                            "languages": list(m["languages"]) if m["languages"] else [],
                            "downloads": m["downloads"] or 0,
                            "likes": m["likes"] or 0,
                            "last_modified": m["last_modified"],
                            "similarity": float(m["similarity"]),
                        })
                        seen_ids.add(m["id"])

        # ---- Keyword fallback ----
        keyword = f"%{query.strip()[:100]}%"
        with engine.connect() as conn:
            kw_rows = conn.execute(text(f"""
                SELECT id, hf_id, pretty_name, description,
                       pipeline_tag, library_name, languages,
                       downloads, likes, last_modified
                FROM hf_models
                WHERE (hf_id ILIKE :kw OR pretty_name ILIKE :kw
                       OR description ILIKE :kw)
                {filter_sql}
                ORDER BY downloads DESC
                LIMIT :lim
            """), {**params_base, "kw": keyword, "lim": offset + limit}).fetchall()

            for r in kw_rows:
                m = r._mapping
                if m["id"] not in seen_ids:
                    results.append({
                        "id": m["id"],
                        "hf_id": m["hf_id"],
                        "pretty_name": m["pretty_name"],
                        "description": m["description"],
                        "pipeline_tag": m["pipeline_tag"],
                        "library_name": m["library_name"],
                        "languages": list(m["languages"]) if m["languages"] else [],
                        "downloads": m["downloads"] or 0,
                        "likes": m["likes"] or 0,
                        "last_modified": m["last_modified"],
                        "similarity": 0.5,
                    })
                    seen_ids.add(m["id"])

        if not results:
            with engine.connect() as conn:
                count = conn.execute(text("SELECT COUNT(*) FROM hf_models")).scalar()
            if count == 0:
                return "HF model index is empty — the first ingest hasn't run yet."
            scope_parts = []
            if task:
                scope_parts.append(f"task '{task}'")
            if library:
                scope_parts.append(f"library '{library}'")
            scope = f" ({', '.join(scope_parts)})" if scope_parts else ""
            return f"No models found matching '{query}'{scope}. Try broader terms."

        # ---- Rank: blend similarity, download popularity, and name match ----
        for r in results:
            dl_score = log10(max(r["downloads"], 1) + 1) / 9.0  # models have higher downloads
            like_score = log10(max(r["likes"], 1) + 1) / 5.0
            r["score"] = (0.6 * r["similarity"] + 0.25 * dl_score + 0.15 * like_score
                          + _name_boost(query, r["hf_id"], r["pretty_name"]))

        results.sort(key=lambda x: x["score"], reverse=True)
        page = results[offset:offset + limit]

        if not page and offset > 0:
            return f"No more results at offset {offset}."

        # ---- Format output ----
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM hf_models")).scalar()
        lines.append(f"MODEL SEARCH: \"{query}\"")
        scope_parts = []
        if task:
            scope_parts.append(f"task: {task}")
        if library:
            scope_parts.append(f"library: {library}")
        if scope_parts:
            lines.append(f"Filters: {', '.join(scope_parts)}")
        lines.append(f"Searching {total:,} indexed models")
        if offset > 0:
            lines.append(f"Showing results {offset + 1}–{offset + len(page)}")
        lines.append("=" * 50)

        for i, r in enumerate(page, offset + 1):
            lines.append("")
            name = r["pretty_name"] or r["hf_id"]
            dl_str = _fmt_downloads(r["downloads"])
            likes_str = f"♥ {r['likes']}" if r["likes"] > 0 else ""
            task_str = f" · {r['pipeline_tag']}" if r["pipeline_tag"] else ""
            lib_str = f" · {r['library_name']}" if r["library_name"] else ""
            lines.append(
                f"{i}. {name}  "
                f"(↓ {dl_str}{' | ' + likes_str if likes_str else ''}{task_str}{lib_str})"
            )
            lines.append(f"   ID: {r['hf_id']}")
            desc = _clean_hf_description(r["description"])
            if desc:
                lines.append(f"   {desc[:200]}")
            if r["languages"]:
                lines.append(f"   Languages: {', '.join(r['languages'][:8])}")
            lm = r.get("last_modified")
            if lm:
                try:
                    lines.append(f"   Last modified: {lm.strftime('%Y-%m-%d')}")
                except (AttributeError, ValueError):
                    pass
            lines.append(f"   https://huggingface.co/{r['hf_id']}")

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"_search_hf_models failed: {e}")
        return "Error searching models. Please try again."


@mcp.tool()
@track_usage
async def find_model(
    query: str, task: str = "", library: str = "",
    min_downloads: int = 0, limit: int = 5, offset: int = 0,
) -> str:
    """Find HuggingFace models by describing what you need in plain English.
    Searches indexed models from the HuggingFace Hub with download counts,
    pipeline tags, and library metadata.

    Optional filters:
      task: text-generation, text-classification, translation, image-classification,
            feature-extraction, fill-mask, question-answering, summarization, etc.
      library: transformers, diffusers, sentence-transformers, spacy, etc.
      min_downloads: minimum download count threshold

    Examples:
      find_model("code completion small model", task="text-generation")
      find_model("image segmentation", library="transformers")
      find_model("sentence embeddings for RAG", task="feature-extraction")
      find_model("text to speech", min_downloads=10000)
    """
    return await _search_hf_models(
        query=query, task=task, library=library,
        min_downloads=min_downloads, limit=limit, offset=offset,
    )


# ---------------------------------------------------------------------------
# Auth middleware & mount
# ---------------------------------------------------------------------------


# Simple in-memory rate limiter (per-IP, 60 requests/minute)
_RATE_LIMIT = 60
_RATE_WINDOW = 60
_rate_buckets: dict[str, list[float]] = defaultdict(list)


class TokenAuthMiddleware(BaseHTTPMiddleware):
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
        if not hmac.compare_digest(token, settings.API_TOKEN):
            return Response(status_code=401, content="Unauthorized")
        # Set request context for tool usage tracking
        import hashlib
        from app.mcp.tracking import set_request_context
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or ip
        user_agent = request.headers.get("User-Agent", "")
        session_key = hashlib.sha256(f"{client_ip}:{user_agent}".encode()).hexdigest()[:16]
        set_request_context(client_ip, user_agent, session_key)
        return await call_next(request)


# ---------------------------------------------------------------------------
# JSON-RPC tool registry — works across FastMCP versions
#
# Newer FastMCP (>=2.14) returns FunctionTool from @mcp.tool();
# older versions return the plain function. We handle both.
# ---------------------------------------------------------------------------

import inspect

_PY_TO_JSON = {str: "string", int: "integer", float: "number", bool: "boolean"}

# Full tool list — used by SSE transport (Claude Desktop / SDK).
# Includes editorial tools and legacy aliases for backward compatibility.
_TOOL_LIST = [
    about, more_tools, describe_schema, query, whats_new, project_pulse, lab_pulse,
    trending, hype_check, briefing,
    submit_feedback, upvote_feedback, list_feedback, amend_feedback,
    submit_correction, upvote_correction, list_corrections, amend_correction,
    propose_article, list_pitches, upvote_pitch, amend_pitch,
    submit_lab_event, list_lab_events, lab_models,
    lifecycle_map, hype_landscape, sniff_projects,
    accept_candidate, set_tier, movers, compare, related, market_map,
    radar, explain, topic, scout, hn_pulse, deep_dive,
    find_ai_tool, find_mcp_server, mcp_coverage, mcp_health, find_public_api,
    get_api_spec, get_api_endpoints,
    get_dependencies, find_dependents,
    find_dataset, find_model,
]

def _tool_name(t) -> str:
    return getattr(t, "name", None) or t.__name__


def _tool_fn(t):
    return getattr(t, "fn", t)


# Core tools — the only tools visible in JSON-RPC tools/list (Claude.ai).
# 12 tools that cover the main use cases. Everything else is accessible
# via more_tools() which returns a catalog, or by calling tools directly.
_CORE_TOOL_NAMES = {
    "about",            # orientation — start here
    "more_tools",       # gateway to 30+ advanced tools
    "find_ai_tool",     # search ~100K AI repos
    "find_mcp_server",  # search MCP servers
    "find_public_api",  # search REST APIs
    "trending",         # what's accelerating right now
    "project_pulse",    # deep dive on a project
    "whats_new",        # what shipped recently
    "topic",            # semantic search across ecosystem
    "query",            # raw SQL escape hatch
    "briefing",         # curated ecosystem intelligence
}

# Public tool list — used by JSON-RPC transport (Claude.ai web connector).
# Only core tools appear in tools/list. All other tools still work if called
# by name (they're in _TOOLS) — they just don't clutter the initial listing.
_TOOL_LIST_PUBLIC = [t for t in _TOOL_LIST if _tool_name(t) in _CORE_TOOL_NAMES]

# Lookup includes ALL tools (so SSE aliases and editorial tools still work via JSON-RPC
# if called directly — they just won't appear in tools/list for external users).
_TOOLS = {_tool_name(t): t for t in _TOOL_LIST}


def _tool_definitions(tools=None) -> list[dict]:
    """Build JSON-RPC tool definitions, using inspect as fallback for schemas."""
    defs = []
    for t in (tools or _TOOL_LIST):
        name = _tool_name(t)
        fn = _tool_fn(t)

        # FunctionTool exposes .parameters; plain functions need inspect
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


def mount_mcp(app):
    """Mount the MCP server on a FastAPI app.

    Two transports:
      - /mcp/stream  — Streamable HTTP (SSE) for Claude Desktop / SDK clients
      - /mcp         — Simple JSON-RPC POST for Claude.ai web connector
    """
    from fastapi.responses import JSONResponse

    # ---- Simple JSON-RPC POST transport (for Claude.ai) ----
    # Must be registered BEFORE the /mcp mount so FastAPI matches it
    # instead of falling through to the Starlette sub-app.

    def _check_token(request: Request):
        token = request.query_params.get("token", "")
        if not token:
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ") if auth.startswith("Bearer ") else ""
        if not hmac.compare_digest(token, settings.API_TOKEN):
            return None
        return token

    def _log_protocol_event(event_name: str, client_ip: str, user_agent: str):
        """Log MCP protocol events (initialize, tools/list) to tool_usage."""
        try:
            from app.models import ToolUsage
            session = SessionLocal()
            usage = ToolUsage(
                tool_name=event_name,
                params={},
                duration_ms=0,
                success=True,
                error_message=None,
                result_size=0,
                client_ip=client_ip or None,
                user_agent=user_agent[:500] if user_agent and len(user_agent) > 500 else (user_agent or None),
            )
            session.add(usage)
            session.commit()
            session.close()
        except Exception:
            logger.debug(f"Failed to log protocol event {event_name}", exc_info=True)

    @app.post("/mcp")
    async def mcp_json_rpc(request: Request):
        """Simple JSON-RPC endpoint for Claude.ai web connector."""
        import hashlib

        # Extract client info for tracking (before auth — needed for all paths)
        from app.mcp.tracking import set_request_context
        raw_ip = request.client.host if request.client else "unknown"
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or raw_ip
        user_agent = request.headers.get("User-Agent", "")
        session_key = hashlib.sha256(f"{client_ip}:{user_agent}".encode()).hexdigest()[:16]
        set_request_context(client_ip, user_agent, session_key)

        body = await request.json()
        method = body.get("method")
        params = body.get("params", {})
        req_id = body.get("id", 0)

        # Allow discovery methods without auth (initialize, tools/list,
        # notifications/initialized, prompts/list, resources/list).
        # This lets MCP scoring engines (Glama) and potential users
        # discover what the server offers before authenticating.
        _PUBLIC_METHODS = {
            "initialize", "notifications/initialized",
            "tools/list", "prompts/list",
            "resources/list", "resources/templates/list",
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
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "serverInfo": {"name": "pt-edge", "version": "1.0.0"},
                    "instructions": MCP_INSTRUCTIONS,
                },
            })

        if method == "tools/list":
            _log_protocol_event("mcp.tools_list", client_ip, user_agent)
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": _tool_definitions(_TOOL_LIST_PUBLIC)},
            })

        if method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            tool = _TOOLS.get(tool_name)
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

        # ---- Resources & Prompts ----

        if method == "resources/list":
            from app.mcp.resources import RESOURCES
            return JSONResponse({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"resources": RESOURCES},
            })

        if method == "resources/templates/list":
            from app.mcp.resources import RESOURCE_TEMPLATES
            return JSONResponse({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"resourceTemplates": RESOURCE_TEMPLATES},
            })

        if method == "resources/read":
            from app.mcp.resources import read_resource
            result = await read_resource(params.get("uri", ""))
            return JSONResponse({
                "jsonrpc": "2.0", "id": req_id,
                "result": result,
            })

        if method == "prompts/list":
            from app.mcp.prompts import PROMPTS
            return JSONResponse({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"prompts": PROMPTS},
            })

        if method == "prompts/get":
            from app.mcp.prompts import get_prompt
            result = await get_prompt(params.get("name", ""), params.get("arguments", {}))
            return JSONResponse({
                "jsonrpc": "2.0", "id": req_id,
                "result": result,
            })

        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        })

    # ---- Streamable HTTP transport (for Claude Desktop / SDK) ----
    # Trigger resource and prompt registration before mounting
    from app.mcp import resources as _resources  # noqa: F401
    from app.mcp import prompts as _prompts  # noqa: F401

    mcp_app = mcp.http_app(path="/stream")
    mcp_app.add_middleware(TokenAuthMiddleware)
    app.mount("/mcp", mcp_app)
    app.router.lifespan_context = mcp_app.router.lifespan_context
