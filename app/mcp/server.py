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

from app.db import SessionLocal, engine
from app.models import (
    Lab, Project, GitHubSnapshot, DownloadSnapshot,
    Release, HNPost, Correction, SyncLog,
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


def _find_project_or_suggest(session: Session, identifier: str) -> tuple[Project | None, list[str]]:
    """Find a project by slug or name. Returns (project, suggestions) with fuzzy fallback."""
    identifier = identifier.strip()
    # Exact slug match
    project = session.query(Project).filter(
        func.lower(Project.slug) == identifier.lower()
    ).first()
    if project:
        return project, []
    # Exact name match
    project = session.query(Project).filter(
        func.lower(Project.name) == identifier.lower()
    ).first()
    if project:
        return project, []
    # Substring fallback
    matches = session.query(Project).filter(
        (Project.slug.ilike(f"%{identifier}%")) |
        (Project.name.ilike(f"%{identifier}%"))
    ).limit(5).all()
    if len(matches) == 1:
        return matches[0], []
    if matches:
        return None, [m.slug for m in matches]
    # Edit-distance fallback for typos (e.g., "langchan" → "langchain")
    all_slugs = [r[0] for r in session.query(Project.slug).all()]
    close = difflib.get_close_matches(identifier.lower(), [s.lower() for s in all_slugs], n=3, cutoff=0.6)
    if close:
        matches = session.query(Project).filter(func.lower(Project.slug).in_(close)).all()
        if len(matches) == 1:
            return matches[0], []
        return None, [m.slug for m in matches]
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
        "  sniff_projects(limit)            -- auto-discovered project candidates",
        "  accept_candidate(id, category)   -- promote a candidate to tracked",
        "",
        "Community:",
        "  submit_correction(topic, text)   -- flag something that's wrong",
        "  upvote_correction(id)            -- confirm someone else's correction",
        "  list_corrections(topic, status)  -- browse corrections",
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
    if not re.match(r"(?i)^\s*SELECT\b", sql_stripped):
        return json.dumps({"error": "Only SELECT queries are allowed."})

    # Block dangerous patterns
    forbidden = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE)\b",
        re.IGNORECASE,
    )
    if forbidden.search(sql_stripped):
        return json.dumps({"error": "Query contains forbidden keywords."})

    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql_stripped))
            rows = [_row_to_dict(r) for r in result.fetchmany(1000)]
            return json.dumps(rows, default=_serialize)
    except Exception as e:
        return json.dumps({"error": str(e)[:1000]})


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
        proj, suggestions = _find_project_or_suggest(session, project)
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
        proj, suggestions = _find_project_or_suggest(session, project)
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

@mcp.tool()
@track_usage
async def accept_candidate(candidate_id: int, category: str = "tool", lab_slug: str = None) -> str:
    """Promote a candidate to a tracked project."""
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
        proj, suggestions = _find_project_or_suggest(session, project)
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
            proj, suggestions = _find_project_or_suggest(session, name)
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
        proj, suggestions = _find_project_or_suggest(session, project)
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


def mount_mcp(app):
    """Mount the MCP server on a FastAPI app at /mcp/stream."""
    mcp_app = mcp.http_app(path="/stream")
    mcp_app.add_middleware(TokenAuthMiddleware)
    app.mount("/mcp", mcp_app)
    app.router.lifespan_context = mcp_app.router.lifespan_context
