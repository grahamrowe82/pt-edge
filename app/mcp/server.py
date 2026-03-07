import json
import re
import logging
from datetime import date, datetime, timezone, timedelta

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


def _fmt_date(dt):
    """Format a datetime for display."""
    if dt is None:
        return "n/a"
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(dt, date):
        return dt.isoformat()
    return str(dt)


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


def _find_project(session: Session, identifier: str) -> Project | None:
    """Find a project by slug or name (case-insensitive)."""
    identifier = identifier.strip()
    # Try slug first
    project = session.query(Project).filter(
        func.lower(Project.slug) == identifier.lower()
    ).first()
    if project:
        return project
    # Try name
    project = session.query(Project).filter(
        func.lower(Project.name) == identifier.lower()
    ).first()
    return project


def _find_lab(session: Session, identifier: str) -> Lab | None:
    """Find a lab by slug or name (case-insensitive)."""
    identifier = identifier.strip()
    lab = session.query(Lab).filter(
        func.lower(Lab.slug) == identifier.lower()
    ).first()
    if lab:
        return lab
    lab = session.query(Lab).filter(
        func.lower(Lab.name) == identifier.lower()
    ).first()
    return lab


# ---------------------------------------------------------------------------
# Tool 1: about
# ---------------------------------------------------------------------------

@mcp.tool()
@track_usage
async def about() -> str:
    """What is this server, what does it track, and when was data last updated?"""
    lines = [
        "PT-EDGE -- AI Intelligence Server",
        "=" * 40,
        "",
        "This MCP server tracks the AI/ML ecosystem: open-source projects, labs,",
        "GitHub activity, package downloads, releases, Hacker News discussion,",
        "and practitioner corrections.",
        "",
        "TRACKED ENTITIES",
        "- Labs: AI research labs and companies (OpenAI, Anthropic, Meta, etc.)",
        "- Projects: open-source AI projects with GitHub + package metrics",
        "- Releases: version releases from GitHub, blogs, changelogs",
        "- HN Posts: Hacker News posts linked to tracked projects",
        "- Corrections: practitioner-submitted corrections to AI claims",
        "",
        "AVAILABLE TOOLS",
        "- about()              -- this overview",
        "- describe_schema()    -- database tables and columns",
        "- query(sql)           -- run read-only SQL",
        "- whats_new(days)      -- recent releases, trending projects, HN discussion",
        "- project_pulse(name)  -- deep dive on a single project",
        "- lab_pulse(name)      -- what a lab is shipping",
        "- trending(category, window) -- what's accelerating right now",
        "- hype_check(project)  -- stars vs downloads reality check",
        "- submit_correction()  -- submit a practitioner correction",
        "- upvote_correction()  -- confirm someone else's correction",
        "- list_corrections()   -- browse active corrections",
        "",
    ]

    # Data freshness
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
        session.close()

        if freshness_lines:
            lines.append("DATA FRESHNESS")
            lines.extend(freshness_lines)
        else:
            lines.append("DATA FRESHNESS: No syncs recorded yet.")
    except Exception as e:
        lines.append(f"DATA FRESHNESS: Could not query sync log ({e})")

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
        # --- Recent Releases ---
        releases = (
            session.query(Release, Project.name.label("project_name"), Lab.name.label("lab_name"))
            .outerjoin(Project, Release.project_id == Project.id)
            .outerjoin(Lab, Release.lab_id == Lab.id)
            .filter(Release.released_at >= cutoff)
            .order_by(Release.released_at.desc())
            .limit(30)
            .all()
        )

        lines.append("")
        lines.append("RECENT RELEASES")
        lines.append("-" * 30)
        if releases:
            for rel, proj_name, lab_name in releases:
                proj_label = proj_name or "unknown"
                lab_label = f" ({lab_name})" if lab_name else ""
                version_label = f" v{rel.version}" if rel.version else ""
                summary = f" -- {rel.summary[:120]}" if rel.summary else ""
                lines.append(
                    f"  {_fmt_date(rel.released_at)}  "
                    f"{proj_label}{lab_label}{version_label}{summary}"
                )
        else:
            lines.append("  No releases in this period.")

        # --- Trending Projects (from mv_momentum) ---
        lines.append("")
        lines.append("TRENDING PROJECTS (by star growth)")
        lines.append("-" * 30)
        try:
            with engine.connect() as conn:
                trending_rows = _safe_mv_query(conn, """
                    SELECT name, category, stars_now, stars_7d_delta, stars_30d_delta,
                           dl_monthly_now, dl_7d_delta
                    FROM mv_momentum
                    WHERE stars_7d_delta IS NOT NULL
                    ORDER BY stars_7d_delta DESC
                    LIMIT 10
                """)
                if trending_rows:
                    for r in trending_rows:
                        lines.append(
                            f"  {r['name']:<30} "
                            f"stars: {_fmt_number(r.get('stars_now'))} "
                            f"({_fmt_delta(r.get('stars_7d_delta'))} 7d) "
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
        proj = _find_project(session, project)
        if not proj:
            return f"Project not found: '{project}'. Use describe_schema() or query() to browse projects."

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
            lines.extend([
                f"  Stars:         {_fmt_number(gh.stars)}",
                f"  Forks:         {_fmt_number(gh.forks)}",
                f"  Open Issues:   {_fmt_number(gh.open_issues)}",
                f"  Watchers:      {_fmt_number(gh.watchers)}",
                f"  Commits (30d): {_fmt_number(gh.commits_30d)}",
                f"  Contributors:  {_fmt_number(gh.contributors)}",
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
                           dl_monthly_now
                    FROM mv_momentum
                    WHERE project_id = :pid
                """, {"pid": proj.id})
                if momentum:
                    m = momentum[0]
                    lines.extend([
                        f"  Stars 7d delta:       {_fmt_delta(m.get('stars_7d_delta'))}",
                        f"  Stars 30d delta:      {_fmt_delta(m.get('stars_30d_delta'))}",
                        f"  Downloads 7d delta:   {_fmt_delta(m.get('dl_7d_delta'))}",
                        f"  Downloads 30d delta:  {_fmt_delta(m.get('dl_30d_delta'))}",
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
                        f"  Hype Ratio:         {h.get('hype_ratio', 'n/a')}",
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
                version_label = f"v{rel.version}" if rel.version else ""
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
        lab_obj = _find_lab(session, lab)
        if not lab_obj:
            return f"Lab not found: '{lab}'. Use query() to browse labs."

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
            # Latest GitHub snapshot
            gh = (
                session.query(GitHubSnapshot)
                .filter(GitHubSnapshot.project_id == p.id)
                .order_by(GitHubSnapshot.snapshot_date.desc())
                .first()
            )
            # Latest download snapshot
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
                version_label = f"v{rel.version}" if rel.version else ""
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
                where_clause = "WHERE category = :cat"
                params["cat"] = category

            rows = _safe_mv_query(conn, f"""
                SELECT name, category, stars, forks, monthly_downloads,
                       stars_7d_delta, stars_30d_delta, dl_30d_delta,
                       hype_ratio, hype_bucket,
                       last_release_at, last_release_title,
                       days_since_release, commits_30d
                FROM mv_project_summary
                {where_clause}
                ORDER BY {delta_col} DESC NULLS LAST
                LIMIT 20
            """, params)

            if rows:
                # Header
                lines.append(
                    f"  {'#':<3} {'Project':<28} {'Category':<14} "
                    f"{'Stars':<10} {'7d':<8} {'30d':<8} "
                    f"{'DL/mo':<12} {'Hype':<10} {'Commits 30d':<12}"
                )
                lines.append("  " + "-" * 110)
                for i, r in enumerate(rows, 1):
                    lines.append(
                        f"  {i:<3} {str(r.get('name', '')):<28} "
                        f"{str(r.get('category', '')):<14} "
                        f"{_fmt_number(r.get('stars')):<10} "
                        f"{_fmt_delta(r.get('stars_7d_delta')):<8} "
                        f"{_fmt_delta(r.get('stars_30d_delta')):<8} "
                        f"{_fmt_number(r.get('monthly_downloads')):<12} "
                        f"{str(r.get('hype_bucket', 'n/a')):<10} "
                        f"{_fmt_number(r.get('commits_30d')):<12}"
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
        proj = _find_project(session, project)
        if not proj:
            return f"Project not found: '{project}'."

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
                f"  Hype Ratio:         {ratio}",
                f"  Bucket:             {bucket}",
                "",
            ])

            # Interpretation
            lines.append("INTERPRETATION")
            lines.append("-" * 30)
            bucket_lower = str(bucket).lower()
            if bucket_lower == "overhyped":
                lines.append(
                    "  This project has significantly more stars than downloads,")
                lines.append(
                    "  suggesting buzz exceeds actual adoption. Stars can reflect")
                lines.append(
                    "  interest or bookmarking rather than production use.")
            elif bucket_lower == "balanced":
                lines.append(
                    "  Stars and downloads are roughly in proportion.")
                lines.append(
                    "  This suggests healthy alignment between interest and adoption.")
            elif bucket_lower == "underhyped":
                lines.append(
                    "  This project has more downloads relative to its stars.")
                lines.append(
                    "  It may be a workhorse dependency that gets heavy use")
                lines.append(
                    "  without the corresponding GitHub attention.")
            else:
                lines.append(f"  Bucket '{bucket}' -- interpret with context.")

            if category_avg:
                lines.append("")
                lines.append("CATEGORY CONTEXT")
                lines.append("-" * 30)
                lines.append(
                    f"  Average hype ratio in '{proj.category}': "
                    f"{category_avg.get('avg_ratio', 'n/a')}"
                )
                lines.append(
                    f"  Projects in category: {category_avg.get('count', 'n/a')}"
                )
                try:
                    project_ratio = float(ratio)
                    avg_ratio = float(category_avg["avg_ratio"])
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
# Auth middleware & mount
# ---------------------------------------------------------------------------


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {settings.API_TOKEN}":
            return Response(status_code=401, content="Unauthorized")
        return await call_next(request)


def mount_mcp(app):
    """Mount the MCP server on a FastAPI app at /mcp."""
    mcp_app = mcp.http_app(path="/")
    mcp_app.add_middleware(BearerAuthMiddleware)
    app.mount("/mcp", mcp_app)
