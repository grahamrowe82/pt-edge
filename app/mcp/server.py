import difflib
import json
import re
import logging
from datetime import date, datetime, timezone, timedelta
from itertools import groupby

from fastapi import Request, Response
from fastmcp import FastMCP
from sqlalchemy import text, func
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.db import SessionLocal, engine, readonly_engine
from app.models import (
    Lab, Project, GitHubSnapshot, DownloadSnapshot,
    Release, HNPost, Correction, SyncLog, Methodology,
)
from app.mcp.tracking import track_usage
from app.settings import settings

logger = logging.getLogger(__name__)

mcp = FastMCP("pt-edge")

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
    """Format a delta, showing n/a when there is no historical baseline."""
    if not has_baseline:
        return "n/a (new)"
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


async def _semantic_project_search(query_text: str, limit: int = 5) -> list[dict]:
    """Find projects by semantic similarity. Returns [{slug, name, similarity}, ...]"""
    from app.embeddings import is_enabled, embed_one

    if not is_enabled():
        return []

    vec = await embed_one(query_text)
    if vec is None:
        return []

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

            results = []
            for r in rows:
                m = r._mapping
                sim = float(m["similarity"])
                if sim > 0.3:  # threshold — below this is noise
                    results.append({
                        "slug": m["slug"],
                        "name": m["name"],
                        "description": m["description"],
                        "category": m["category"],
                        "similarity": round(sim, 3),
                    })
            return results
    except Exception as e:
        logger.error(f"Semantic search error: {e}")
        return []


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
    semantic = await _semantic_project_search(identifier, limit=3)
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


def _group_releases(releases):
    """Group releases by lab + timestamp (within 1 minute). Returns list of display strings."""
    lines = []
    if not releases:
        lines.append("  No releases in this period.")
        return lines

    def _group_key(item):
        rel, proj_name, lab_name = item
        ts = rel.released_at.replace(second=0, microsecond=0) if rel.released_at else None
        return (lab_name or "", ts)

    sorted_releases = sorted(releases, key=_group_key)
    for key, group_iter in groupby(sorted_releases, _group_key):
        items = list(group_iter)
        lab_name, ts = key
        if len(items) >= 3 and lab_name:
            # Group as "Lab: N packages updated"
            first_rel = items[0][0]
            version = _fmt_version(first_rel.version)
            lines.append(
                f"  {_fmt_date(ts)}  "
                f"{lab_name}: {len(items)} packages updated{f' ({version})' if version else ''}"
            )
        else:
            for rel, proj_name, lab_n in items:
                proj_label = proj_name or "unknown"
                lab_label = f" ({lab_n})" if lab_n else ""
                version_label = f" {_fmt_version(rel.version)}" if rel.version else ""
                summary = f" -- {rel.summary[:120]}" if rel.summary else ""
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
    """What is PT-Edge, how does it work, and what can you do with it?"""
    lines = [
        "PT-EDGE -- AI Project Intelligence",
        "=" * 50,
        "",
        "PT-Edge makes Claude less wrong about the current state of AI development.",
        "It tracks ~100 open-source AI projects across 10 labs, collecting real-time",
        "signals from GitHub, PyPI, npm, and Hacker News.",
        "",
        "HOW IT WORKS",
        "-" * 30,
        "- Daily ingests pull GitHub stats, package downloads, releases, and HN posts",
        "- Materialized views compute derived metrics: momentum, hype ratio, tiers, lifecycle",
        "- MCP tools let you query this data naturally in conversation",
        "- Semantic search via embeddings enables conceptual queries (e.g. 'vector databases')",
        "- Corrections system lets practitioners push back on bad takes",
        "- Project sniffing auto-discovers new AI projects from HN and GitHub trending",
        "",
        "KEY CONCEPTS",
        "-" * 30,
        "- Hype Ratio: stars / monthly downloads. High = GitHub tourism. Low = invisible infrastructure.",
        "- Tiers: T1 Foundational (>10M downloads), T2 Major (>100K), T3 Notable (>10K), T4 Emerging",
        "- Lifecycle: emerging -> launching -> growing -> established -> fading -> dormant",
        "- Momentum: star and download deltas over 7d and 30d windows",
        "",
        "AVAILABLE TOOLS",
        "-" * 30,
        "Discovery & Overview:",
        "  about()                          -- this guide",
        "  whats_new(days=7)                -- releases, trending, HN discussion",
        "  trending(category, window)       -- top 20 by star growth",
        "  lifecycle_map(category, tier)     -- projects grouped by lifecycle stage",
        "  hype_landscape(category, limit)  -- top overhyped + underrated projects",
        "",
        "Deep Dives:",
        "  project_pulse(name)              -- everything about one project",
        "  lab_pulse(name)                  -- what a lab is shipping",
        "  hype_check(project)              -- stars vs downloads reality check",
        "",
        "Comparative Analysis:",
        "  compare(projects)                -- side-by-side metrics for 2-5 projects",
        "  movers(window, limit)            -- acceleration/deceleration detector",
        "  related(project)                 -- HN co-occurrence analysis",
        "  market_map()                     -- category concentration + power law",
        "",
        "Project Discovery:",
        "  radar()                          -- velocity alerts + HN buzz for unknowns",
        "  scout(category, limit)           -- fastest growing projects ranked by stars/day",
        "  deep_dive(identifier)            -- full project profile from cached data",
        "  sniff_projects(limit)            -- auto-discovered project candidates",
        "  accept_candidate(id, category)   -- promote a candidate to tracked",
        "  topic(query)                     -- what's happening with a topic across ecosystem",
        "",
        "Community:",
        "  submit_correction(topic, text)   -- flag something that's wrong",
        "  upvote_correction(id)            -- confirm someone else's correction",
        "  list_corrections(topic, status)  -- browse corrections",
        "",
        "Methodology:",
        "  explain(topic)                   -- how any tool/metric/algo works (deep)",
        "",
        "Power User:",
        "  describe_schema()                -- database tables and columns",
        "  query(sql)                       -- run read-only SQL",
        "  set_tier(project, tier)          -- editorial tier override",
        "",
    ]

    # Data freshness + coverage
    try:
        session = SessionLocal()
        syncs = session.query(SyncLog).filter(
            SyncLog.status == "success"
        ).order_by(SyncLog.finished_at.desc()).all()

        seen_types = set()
        freshness_lines = []
        for s in syncs:
            if s.sync_type not in seen_types:
                seen_types.add(s.sync_type)
                freshness_lines.append(
                    f"  {s.sync_type:<16} last synced {_fmt_date(s.finished_at)}  "
                    f"({s.records_written} records)"
                )

        if freshness_lines:
            lines.append("DATA FRESHNESS")
            lines.extend(freshness_lines)
        else:
            lines.append("DATA FRESHNESS: No syncs recorded yet.")

        # Coverage stats
        lines.append("")
        lines.append("DATA COVERAGE")
        lines.append("-" * 30)
        total = session.query(func.count(Project.id)).filter(Project.is_active == True).scalar() or 0
        with_gh = session.execute(text(
            "SELECT COUNT(DISTINCT project_id) FROM github_snapshots"
        )).scalar() or 0
        with_dl = session.execute(text(
            "SELECT COUNT(DISTINCT project_id) FROM download_snapshots"
        )).scalar() or 0
        snapshot_days = session.execute(text(
            "SELECT COUNT(DISTINCT snapshot_date) FROM github_snapshots"
        )).scalar() or 0
        candidates = session.execute(text(
            "SELECT COUNT(*) FROM project_candidates WHERE status = 'pending'"
        )).scalar() or 0

        lines.extend([
            f"  Projects tracked:    {total}",
            f"  With GitHub data:    {with_gh} ({round(100*with_gh/total)}%)" if total else "  With GitHub data:    0",
            f"  With download data:  {with_dl} ({round(100*with_dl/total)}%)" if total else "  With download data:  0",
            f"  Snapshot depth:      {snapshot_days} day(s)",
            f"  Pending candidates:  {candidates}",
        ])

        session.close()
    except Exception as e:
        lines.append(f"DATA FRESHNESS: Could not query ({e})")

    lines.extend([
        "",
        "BUILT BY",
        "-" * 30,
        "Graham Rowe — Phase Transitions newsletter",
        "Subscribe: phasetransitions.ai",
        "Contact: graham@phasetransitions.ai",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 2: describe_schema
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def describe_schema() -> str:
    """List all database tables with their columns and types."""
    sql = """
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql))
        tables: dict[str, list[str]] = {}
        for r in rows:
            m = r._mapping
            tname = m["table_name"]
            nullable = " (nullable)" if m["is_nullable"] == "YES" else ""
            col_line = f"  {m['column_name']:<30} {m['data_type']}{nullable}"
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
    """Execute a read-only SQL query. Only SELECT statements are allowed. Returns JSON array."""
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
    """What actually shipped recently? Releases, trending projects, and notable HN discussion."""
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
            .limit(50)
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
        lines.append("NOTABLE HN DISCUSSION")
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
    """Deep dive on a specific project. Accepts slug or name."""
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


# ---------------------------------------------------------------------------
# Tool 6: lab_pulse
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def lab_pulse(lab: str) -> str:
    """What is a specific lab shipping? Accepts slug or name."""
    session = SessionLocal()
    try:
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
        projects = (
            session.query(Project)
            .filter(Project.lab_id == lab_obj.id, Project.is_active == True)
            .order_by(Project.name)
            .all()
        )

        lines.append(f"PROJECTS ({len(projects)} active)")
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
            .limit(15)
        )
        releases = releases_query.all()

        lines.append("RECENT RELEASES")
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
                    accel = "Yes" if v.get("is_accelerating") else "No"
                    lines.extend([
                        f"  Releases (30d):             {v.get('releases_30d', 'n/a')}",
                        f"  Releases (90d):             {v.get('releases_90d', 'n/a')}",
                        f"  Avg days between releases:  {v.get('avg_days_between_releases', 'n/a')}",
                        f"  Accelerating:               {accel}",
                    ])
                else:
                    lines.append("  Velocity data not yet available.")
        except Exception:
            lines.append("  Velocity data not yet available.")

    finally:
        session.close()

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 7: trending
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def trending(category: str = None, window: str = "7d") -> str:
    """What's accelerating right now. Top 20 projects by star growth."""
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
                       s.lifecycle_stage
                FROM mv_project_summary s
                {where_clause}
                ORDER BY {delta_col} DESC NULLS LAST
                LIMIT 20
            """, params)

            if rows:
                lines.append(
                    f"  {'#':<3} {'Project':<24} {'Tier':<5} {'Stage':<12} {'Category':<10} "
                    f"{'Stars':<10} {'7d':<10} {'30d':<10} "
                    f"{'DL/mo':<12} {'Hype':<12}"
                )
                lines.append("  " + "-" * 120)
                for i, r in enumerate(rows, 1):
                    has_bl = r.get(baseline_col, False)
                    delta_7d = _fmt_delta_safe(r.get('stars_7d_delta'), r.get('has_7d_baseline', False))
                    delta_30d = _fmt_delta_safe(r.get('stars_30d_delta'), r.get('has_30d_baseline', False))
                    lines.append(
                        f"  {i:<3} {str(r.get('name', '')):<24} "
                        f"T{int(r.get('tier', 4)):<4} "
                        f"{str(r.get('lifecycle_stage', '')):<12} "
                        f"{str(r.get('category', '')):<10} "
                        f"{_fmt_number(r.get('stars')):<10} "
                        f"{delta_7d:<10} "
                        f"{delta_30d:<10} "
                        f"{_fmt_number(r.get('monthly_downloads')):<12} "
                        f"{str(r.get('hype_bucket', 'n/a')):<12}"
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
# Tool 9: submit_correction
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def submit_correction(
    topic: str, correction: str, context: str = None
) -> str:
    """Submit a practitioner correction about an AI topic or project."""
    # Input length limits
    if len(topic) > 300:
        return "Topic must be 300 characters or fewer."
    if len(correction) > 5000:
        return "Correction must be 5,000 characters or fewer."
    if context and len(context) > 2000:
        return "Context must be 2,000 characters or fewer."

    session = SessionLocal()
    try:
        c = Correction(
            topic=topic.strip(),
            correction=correction.strip(),
            context=context.strip() if context else None,
            status="active",
            upvotes=0,
        )
        session.add(c)
        session.commit()
        correction_id = c.id
        session.close()
        return (
            f"Correction submitted successfully.\n"
            f"  ID:    {correction_id}\n"
            f"  Topic: {topic}\n"
            f"  Text:  {correction[:200]}\n\n"
            f"Others can upvote this with upvote_correction({correction_id})."
        )
    except Exception as e:
        session.rollback()
        session.close()
        return f"Failed to submit correction: {e}"


# ---------------------------------------------------------------------------
# Tool 10: upvote_correction
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def upvote_correction(correction_id: int) -> str:
    """Confirm someone else's correction by upvoting it."""
    session = SessionLocal()
    try:
        # Rate limit: max 5 upvotes per correction per day
        recent = session.execute(text(
            "SELECT COUNT(*) FROM tool_usage "
            "WHERE tool_name = 'upvote_correction' "
            "AND params->>'correction_id' = :cid "
            "AND created_at > NOW() - INTERVAL '24 hours'"
        ), {"cid": str(correction_id)}).scalar()
        if recent and recent >= 5:
            session.close()
            return f"Rate limit: correction #{correction_id} has been upvoted {recent} times in the last 24 hours (max 5/day)."

        c = session.query(Correction).filter(Correction.id == correction_id).first()
        if not c:
            session.close()
            return f"Correction #{correction_id} not found."

        c.upvotes = (c.upvotes or 0) + 1
        session.commit()
        new_count = c.upvotes
        topic = c.topic
        session.close()
        return (
            f"Upvoted correction #{correction_id}.\n"
            f"  Topic:   {topic}\n"
            f"  Upvotes: {new_count}"
        )
    except Exception as e:
        session.rollback()
        session.close()
        return f"Failed to upvote correction: {e}"


# ---------------------------------------------------------------------------
# Tool 11: list_corrections
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def list_corrections(topic: str = None, status: str = "active") -> str:
    """Browse practitioner corrections. Optionally filter by topic and status."""
    session = SessionLocal()
    try:
        q = session.query(Correction).filter(Correction.status == status)

        if topic:
            q = q.filter(func.lower(Correction.topic).contains(topic.lower()))

        corrections = q.order_by(Correction.submitted_at.desc()).limit(50).all()

        if not corrections:
            filter_desc = f" for topic '{topic}'" if topic else ""
            return f"No {status} corrections found{filter_desc}."

        lines = [
            f"CORRECTIONS (status: {status})",
            "=" * 40,
        ]

        for c in corrections:
            lines.append("")
            lines.append(f"  [{c.id}] {c.topic}")
            lines.append(f"       {c.correction[:200]}")
            if c.context:
                lines.append(f"       Context: {c.context[:100]}")
            lines.append(
                f"       Upvotes: {c.upvotes}  |  "
                f"Submitted: {_fmt_date(c.submitted_at)}  |  "
                f"Tags: {', '.join(c.tags) if c.tags else 'none'}"
            )

        lines.append("")
        lines.append(f"Total: {len(corrections)} correction(s)")

    finally:
        session.close()

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 12: lifecycle_map
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def lifecycle_map(category: str = None, tier: int = None) -> str:
    """Groups all projects by lifecycle stage. Filter by category or tier."""
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

            for stage in stage_order:
                projects = grouped.get(stage, [])
                if not projects:
                    continue
                lines.append("")
                lines.append(f"{stage.upper()} ({len(projects)} projects)")
                lines.append(f"  {stage_descriptions.get(stage, '')}")
                lines.append("-" * 30)
                for r in projects:
                    lines.append(
                        f"  [T{int(r.get('tier', 4))}] {r.get('name', ''):<24} "
                        f"[{r.get('category', '')}]  "
                        f"stars: {_fmt_number(r.get('stars'))}  "
                        f"DL/mo: {_fmt_number(r.get('monthly_downloads'))}  "
                        f"commits: {_fmt_number(r.get('commits_30d'))}  "
                        f"releases: {r.get('releases_30d', 0)}/30d"
                    )

    except Exception as e:
        lines.append(f"  Error: {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 13: hype_landscape
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def hype_landscape(category: str = None, limit: int = 10) -> str:
    """Top overhyped + top underrated projects. Bulk hype comparison."""
    lines = ["HYPE LANDSCAPE", "=" * 40]

    try:
        with engine.connect() as conn:
            cat_filter = "AND category = :cat" if category else ""
            params: dict = {"lim": limit}
            if category:
                params["cat"] = category

            # Most overhyped (highest ratio)
            overhyped = _safe_mv_query(conn, f"""
                SELECT name, category, stars, monthly_downloads, hype_ratio, hype_bucket
                FROM mv_hype_ratio
                WHERE hype_ratio IS NOT NULL AND hype_ratio > 0 {cat_filter}
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

    except Exception as e:
        lines.append(f"  Error: {e}")

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

VALID_CATEGORIES = {"tool", "model", "framework", "library", "agent", "eval", "dataset", "infra"}


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
        _row("Stars 7d", "stars_7d_delta", lambda v: _fmt_delta_safe(v, True) if v is not None else "n/a")
        _row("Stars 30d", "stars_30d_delta", lambda v: _fmt_delta_safe(v, True) if v is not None else "n/a")
        _row("Hype Ratio", "hype_ratio", _fmt_ratio)
        _row("Hype Bucket", "hype_bucket")
        _row("Commits 30d", "commits_30d", _fmt_number)
        _row("Last Release", "last_release_title", lambda v: _fmt_version(str(v)) if v else "n/a")
        _row("Days Since Rel", "days_since_release", lambda v: str(int(v)) if v is not None else "n/a")

        # Add missing projects warning
        missing = [s for s in slugs if s not in by_slug]
        if missing:
            lines.append("")
            lines.append(f"Note: No summary data for: {', '.join(missing)}. Views may need refreshing.")

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

        return "\n".join(lines)

    except Exception as e:
        return f"Error generating radar: {e}"


# ---------------------------------------------------------------------------
# Tool 22: explain — deep methodology documentation
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
                    "Use submit_correction() to push back on anything.",
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
                    "Think we're wrong about something? Use submit_correction()",
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
            if is_enabled():
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

                    sem_matches = [
                        r._mapping for r in sem_rows
                        if float(r._mapping["similarity"]) > 0.3
                    ]
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

            return (
                f"No methodology entry found for '{topic}'. "
                f"Call explain() with no arguments to see all available topics."
            )

    except Exception as e:
        return f"Error querying methodology: {e}"


# ---------------------------------------------------------------------------
# Tool 23: topic
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def topic(query: str) -> str:
    """What's happening with a topic across the entire ecosystem?

    Searches tracked projects, candidates, and HN posts semantically.
    Use for conceptual queries like 'MCP', 'vector databases', 'code generation'.
    """
    lines = [
        f"TOPIC: {query}",
        "=" * 60,
    ]

    candidate_rows = []
    hn_posts = []

    # 1. TRACKED PROJECTS — semantic search
    semantic_results = await _semantic_project_search(query, limit=10)

    lines.append("")
    lines.append("TRACKED PROJECTS (by semantic similarity)")
    lines.append("-" * 40)

    if semantic_results:
        for r in semantic_results:
            desc = (r.get("description") or "")[:80]
            lines.append(
                f"  [{r['category']}] {r['name']:<28} "
                f"(similarity: {r['similarity']:.0%})  {desc}"
            )
    else:
        # Fallback to keyword search if no embeddings
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

    # Also search by topic array
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

            # Deduplicate against semantic results
            seen_slugs = {r["slug"] for r in semantic_results} if semantic_results else set()
            topic_matches = [
                r._mapping for r in topic_rows
                if r._mapping["slug"] not in seen_slugs
            ]

            if topic_matches:
                lines.append("")
                lines.append("PROJECTS WITH MATCHING TOPICS")
                lines.append("-" * 40)
                for m in topic_matches:
                    topics_str = ", ".join(m["topics"][:5]) if m["topics"] else ""
                    lines.append(
                        f"  [{m['category']}] {m['name']:<28} topics: {topics_str}"
                    )
    except Exception as e:
        logger.debug(f"Topic array search error: {e}")

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

    # 4. NARRATIVE SUMMARY
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
    Optional category keyword filters results (e.g. 'agent', 'database', 'mcp').
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
                SELECT p.name, p.slug, p.category, p.github_owner, p.github_repo,
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
                        p.name ILIKE '%' || :cat || '%'
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
        lines.append(
            f"  Use deep_dive('owner/repo') for a full profile on any result."
        )

        return "\n".join(lines)

    except Exception as e:
        return f"Error running scout: {e}"


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
                    f"Use search('keyword') to find projects, or scout() to see candidates."
                )

        return "\n".join(lines)

    except Exception as e:
        return f"Error running deep_dive: {e}"


# ---------------------------------------------------------------------------
# Auth middleware & mount
# ---------------------------------------------------------------------------


class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = request.query_params.get("token", "")
        if not token:
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ") if auth.startswith("Bearer ") else ""
        if token != settings.API_TOKEN:
            return Response(status_code=401, content="Unauthorized")
        return await call_next(request)


# ---------------------------------------------------------------------------
# JSON-RPC tool registry — works across FastMCP versions
#
# Newer FastMCP (>=2.14) returns FunctionTool from @mcp.tool();
# older versions return the plain function. We handle both.
# ---------------------------------------------------------------------------

import inspect

_PY_TO_JSON = {str: "string", int: "integer", float: "number", bool: "boolean"}

_TOOL_LIST = [
    about, describe_schema, query, whats_new, project_pulse, lab_pulse,
    trending, hype_check, submit_correction, upvote_correction,
    list_corrections, lifecycle_map, hype_landscape, sniff_projects,
    accept_candidate, set_tier, movers, compare, related, market_map,
    radar, explain, topic, scout, deep_dive,
]


def _tool_name(t) -> str:
    return getattr(t, "name", None) or t.__name__


def _tool_fn(t):
    return getattr(t, "fn", t)


_TOOLS = {_tool_name(t): t for t in _TOOL_LIST}


def _tool_definitions() -> list[dict]:
    """Build JSON-RPC tool definitions, using inspect as fallback for schemas."""
    defs = []
    for t in _TOOL_LIST:
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
        if token != settings.API_TOKEN:
            return None
        return token

    @app.post("/mcp")
    async def mcp_json_rpc(request: Request):
        """Simple JSON-RPC endpoint for Claude.ai web connector."""
        token = _check_token(request)
        if not token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        body = await request.json()
        method = body.get("method")
        params = body.get("params", {})
        req_id = body.get("id", 0)

        if method == "initialize":
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "pt-edge", "version": "1.0.0"},
                },
            })

        if method == "tools/list":
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": _tool_definitions()},
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
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {e}"}],
                        "isError": True,
                    },
                })

        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        })

    # ---- Streamable HTTP transport (for Claude Desktop / SDK) ----
    mcp_app = mcp.http_app(path="/stream")
    mcp_app.add_middleware(TokenAuthMiddleware)
    app.mount("/mcp", mcp_app)
    app.router.lifespan_context = mcp_app.router.lifespan_context
