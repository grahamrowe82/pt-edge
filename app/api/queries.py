"""Structured data access for the REST API. Returns Python dicts, not text."""

import logging
from datetime import datetime, date, timezone, timedelta

from sqlalchemy import text

from app.db import readonly_engine, SessionLocal
from app.models import Project, Lab, Release, HNPost, GitHubSnapshot, DownloadSnapshot, Briefing

logger = logging.getLogger(__name__)


def _serialize(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if hasattr(obj, "__float__"):
        return float(obj)
    return str(obj)


def _row_to_dict(row):
    d = dict(row._mapping)
    return {k: _serialize(v) if v is not None else None for k, v in d.items()}


def _safe_mv_query(conn, sql, params=None):
    try:
        result = conn.execute(text(sql), params or {})
        return [_row_to_dict(r) for r in result]
    except Exception as e:
        if "does not exist" in str(e) or "relation" in str(e).lower():
            logger.debug(f"Materialized view not available: {e}")
            conn.rollback()
            return []
        raise


def get_project(slug: str) -> dict | None:
    session = SessionLocal()
    try:
        proj = session.query(Project).filter(Project.slug == slug).first()
        if not proj:
            return None

        lab_name = proj.lab.name if proj.lab else None
        result = {
            "slug": proj.slug,
            "name": proj.name,
            "category": proj.category,
            "description": proj.description,
            "url": proj.url,
            "lab": lab_name,
            "github": f"{proj.github_owner}/{proj.github_repo}" if proj.github_owner else None,
            "pypi_package": proj.pypi_package,
            "npm_package": proj.npm_package,
            "is_active": proj.is_active,
        }

        # Latest GitHub snapshot
        gh = (
            session.query(GitHubSnapshot)
            .filter(GitHubSnapshot.project_id == proj.id)
            .order_by(GitHubSnapshot.snapshot_date.desc())
            .first()
        )
        if gh:
            result["github_metrics"] = {
                "stars": gh.stars,
                "forks": gh.forks,
                "open_issues": gh.open_issues,
                "watchers": gh.watchers,
                "commits_30d": gh.commits_30d,
                "contributors": gh.contributors,
                "last_commit_at": _serialize(gh.last_commit_at) if gh.last_commit_at else None,
                "license": gh.license,
                "snapshot_date": _serialize(gh.snapshot_date),
            }

        # Latest download snapshot
        dl = (
            session.query(DownloadSnapshot)
            .filter(DownloadSnapshot.project_id == proj.id)
            .order_by(DownloadSnapshot.snapshot_date.desc())
            .first()
        )
        if dl:
            result["downloads"] = {
                "source": dl.source,
                "daily": dl.downloads_daily,
                "weekly": dl.downloads_weekly,
                "monthly": dl.downloads_monthly,
                "snapshot_date": _serialize(dl.snapshot_date),
            }

        # Materialized view data
        with readonly_engine.connect() as conn:
            tier_rows = _safe_mv_query(conn, "SELECT tier, is_override FROM mv_project_tier WHERE project_id = :pid", {"pid": proj.id})
            lc_rows = _safe_mv_query(conn, "SELECT lifecycle_stage FROM mv_lifecycle WHERE project_id = :pid", {"pid": proj.id})
            momentum = _safe_mv_query(conn, """
                SELECT stars_7d_delta, stars_30d_delta, dl_7d_delta, dl_30d_delta,
                       dl_monthly_now, has_7d_baseline, has_30d_baseline
                FROM mv_momentum WHERE project_id = :pid
            """, {"pid": proj.id})
            hype = _safe_mv_query(conn, """
                SELECT stars, monthly_downloads, hype_ratio, hype_bucket
                FROM mv_hype_ratio WHERE project_id = :pid
            """, {"pid": proj.id})

            if tier_rows:
                result["tier"] = tier_rows[0].get("tier")
            if lc_rows:
                result["lifecycle_stage"] = lc_rows[0].get("lifecycle_stage")
            if momentum:
                result["momentum"] = momentum[0]
            if hype:
                result["hype"] = hype[0]

        # Recent releases
        releases = (
            session.query(Release)
            .filter(Release.project_id == proj.id)
            .order_by(Release.released_at.desc())
            .limit(5)
            .all()
        )
        if releases:
            result["recent_releases"] = [
                {
                    "version": r.version,
                    "title": r.title,
                    "released_at": _serialize(r.released_at) if r.released_at else None,
                }
                for r in releases
            ]

        return result
    finally:
        session.close()


def search_projects(q: str = None, category: str = None, limit: int = 20) -> list[dict]:
    session = SessionLocal()
    try:
        query = session.query(Project)
        if q:
            query = query.filter(
                (Project.name.ilike(f"%{q}%")) | (Project.slug.ilike(f"%{q}%"))
            )
        if category:
            query = query.filter(Project.category == category)
        query = query.order_by(Project.name).limit(limit)
        rows = query.all()
        return [
            {
                "slug": p.slug,
                "name": p.name,
                "category": p.category,
                "description": p.description,
                "lab": p.lab.name if p.lab else None,
            }
            for p in rows
        ]
    finally:
        session.close()


def get_projects_bulk(slugs: list[str]) -> list[dict]:
    slugs = slugs[:20]
    session = SessionLocal()
    try:
        projects = (
            session.query(Project)
            .filter(Project.slug.in_(slugs))
            .all()
        )
        if not projects:
            return []

        project_ids = [p.id for p in projects]

        # Batch-fetch latest GH snapshots (one per project via DISTINCT ON)
        gh_map = {}
        gh_rows = session.execute(
            text("""
                SELECT DISTINCT ON (project_id)
                       project_id, stars, forks, open_issues, watchers,
                       commits_30d, contributors, last_commit_at, license, snapshot_date
                FROM github_snapshots
                WHERE project_id = ANY(:pids)
                ORDER BY project_id, snapshot_date DESC
            """),
            {"pids": project_ids},
        ).fetchall()
        for r in gh_rows:
            gh_map[r._mapping["project_id"]] = {
                k: _serialize(v) if v is not None and k in ("last_commit_at", "snapshot_date") else v
                for k, v in dict(r._mapping).items() if k != "project_id"
            }

        # Batch-fetch latest DL snapshots
        dl_map = {}
        dl_rows = session.execute(
            text("""
                SELECT DISTINCT ON (project_id)
                       project_id, source, downloads_daily, downloads_weekly,
                       downloads_monthly, snapshot_date
                FROM download_snapshots
                WHERE project_id = ANY(:pids)
                ORDER BY project_id, snapshot_date DESC
            """),
            {"pids": project_ids},
        ).fetchall()
        for r in dl_rows:
            m = dict(r._mapping)
            pid = m.pop("project_id")
            dl_map[pid] = {
                "source": m["source"],
                "daily": m["downloads_daily"],
                "weekly": m["downloads_weekly"],
                "monthly": m["downloads_monthly"],
                "snapshot_date": _serialize(m["snapshot_date"]),
            }

        # Batch-fetch MV data
        mv_tier = {}
        mv_lc = {}
        mv_momentum = {}
        mv_hype = {}
        with readonly_engine.connect() as conn:
            for r in _safe_mv_query(conn, "SELECT project_id, tier, is_override FROM mv_project_tier WHERE project_id = ANY(:pids)", {"pids": project_ids}):
                mv_tier[int(r["project_id"])] = r
            for r in _safe_mv_query(conn, "SELECT project_id, lifecycle_stage FROM mv_lifecycle WHERE project_id = ANY(:pids)", {"pids": project_ids}):
                mv_lc[int(r["project_id"])] = r
            for r in _safe_mv_query(conn, """
                SELECT project_id, stars_7d_delta, stars_30d_delta, dl_7d_delta, dl_30d_delta,
                       dl_monthly_now, has_7d_baseline, has_30d_baseline
                FROM mv_momentum WHERE project_id = ANY(:pids)
            """, {"pids": project_ids}):
                mv_momentum[int(r["project_id"])] = {k: v for k, v in r.items() if k != "project_id"}
            for r in _safe_mv_query(conn, """
                SELECT project_id, stars, monthly_downloads, hype_ratio, hype_bucket
                FROM mv_hype_ratio WHERE project_id = ANY(:pids)
            """, {"pids": project_ids}):
                mv_hype[int(r["project_id"])] = {k: v for k, v in r.items() if k != "project_id"}

        # Batch-fetch recent releases (last 5 per project)
        rel_map: dict[int, list] = {}
        rel_rows = session.execute(
            text("""
                SELECT * FROM (
                    SELECT project_id, version, title, released_at,
                           ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY released_at DESC) AS rn
                    FROM releases
                    WHERE project_id = ANY(:pids)
                ) sub WHERE rn <= 5
                ORDER BY project_id, released_at DESC
            """),
            {"pids": project_ids},
        ).fetchall()
        for r in rel_rows:
            m = r._mapping
            pid = m["project_id"]
            rel_map.setdefault(pid, []).append({
                "version": m["version"],
                "title": m["title"],
                "released_at": _serialize(m["released_at"]) if m["released_at"] else None,
            })

        # Assemble results in request order
        slug_to_proj = {p.slug: p for p in projects}
        results = []
        for slug in slugs:
            proj = slug_to_proj.get(slug)
            if not proj:
                continue
            result = {
                "slug": proj.slug,
                "name": proj.name,
                "category": proj.category,
                "description": proj.description,
                "url": proj.url,
                "lab": proj.lab.name if proj.lab else None,
                "github": f"{proj.github_owner}/{proj.github_repo}" if proj.github_owner else None,
                "pypi_package": proj.pypi_package,
                "npm_package": proj.npm_package,
                "is_active": proj.is_active,
            }
            if proj.id in gh_map:
                result["github_metrics"] = gh_map[proj.id]
            if proj.id in dl_map:
                result["downloads"] = dl_map[proj.id]
            if proj.id in mv_tier:
                result["tier"] = mv_tier[proj.id].get("tier")
            if proj.id in mv_lc:
                result["lifecycle_stage"] = mv_lc[proj.id].get("lifecycle_stage")
            if proj.id in mv_momentum:
                result["momentum"] = mv_momentum[proj.id]
            if proj.id in mv_hype:
                result["hype"] = mv_hype[proj.id]
            if proj.id in rel_map:
                result["recent_releases"] = rel_map[proj.id]
            results.append(result)
        return results
    finally:
        session.close()


def get_trending(category: str = None, window: str = "7d", limit: int = 20) -> list[dict]:
    delta_col = "stars_7d_delta" if window == "7d" else "stars_30d_delta"
    where_clause = ""
    params: dict = {}
    if category:
        where_clause = "WHERE s.category = :cat"
        params["cat"] = category

    with readonly_engine.connect() as conn:
        rows = _safe_mv_query(conn, f"""
            SELECT s.slug, s.name, s.category, s.stars, s.forks, s.monthly_downloads,
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
            LIMIT :lim
        """, {**params, "lim": limit})
    return rows


def get_whats_new(days: int = 7) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    session = SessionLocal()
    try:
        # Releases
        releases_raw = (
            session.query(Release, Project.name.label("project_name"), Project.slug.label("project_slug"))
            .outerjoin(Project, Release.project_id == Project.id)
            .filter(Release.released_at >= cutoff)
            .order_by(Release.released_at.desc())
            .limit(20)
            .all()
        )
        releases = [
            {
                "project_name": r.project_name,
                "project_slug": r.project_slug,
                "version": r.Release.version,
                "title": r.Release.title,
                "released_at": _serialize(r.Release.released_at) if r.Release.released_at else None,
            }
            for r in releases_raw
        ]

        # Trending
        with readonly_engine.connect() as conn:
            trending = _safe_mv_query(conn, """
                SELECT m.name, m.category, m.stars_now, m.stars_7d_delta,
                       m.dl_monthly_now, m.has_7d_baseline,
                       COALESCE(t.tier, 4) AS tier
                FROM mv_momentum m
                LEFT JOIN mv_project_tier t ON m.project_id = t.project_id
                WHERE m.stars_7d_delta IS NOT NULL
                ORDER BY m.stars_7d_delta DESC
                LIMIT 10
            """)

        # HN
        hn_posts = (
            session.query(HNPost)
            .filter(HNPost.posted_at >= cutoff)
            .order_by(HNPost.points.desc())
            .limit(10)
            .all()
        )
        hn = [
            {
                "title": p.title,
                "url": p.url,
                "points": p.points,
                "num_comments": p.num_comments,
                "posted_at": _serialize(p.posted_at) if p.posted_at else None,
                "hn_id": p.hn_id,
            }
            for p in hn_posts
        ]

        return {"releases": releases, "trending": trending, "hn": hn}
    finally:
        session.close()


def get_lab(slug: str) -> dict | None:
    session = SessionLocal()
    try:
        lab = session.query(Lab).filter(Lab.slug == slug).first()
        if not lab:
            return None

        projects = [
            {
                "slug": p.slug,
                "name": p.name,
                "category": p.category,
                "description": p.description,
            }
            for p in lab.projects
        ]

        # Recent releases from lab's projects
        project_ids = [p.id for p in lab.projects]
        releases = []
        if project_ids:
            releases_raw = (
                session.query(Release, Project.name.label("project_name"))
                .join(Project, Release.project_id == Project.id)
                .filter(Release.project_id.in_(project_ids))
                .order_by(Release.released_at.desc())
                .limit(10)
                .all()
            )
            releases = [
                {
                    "project_name": r.project_name,
                    "version": r.Release.version,
                    "title": r.Release.title,
                    "released_at": _serialize(r.Release.released_at) if r.Release.released_at else None,
                }
                for r in releases_raw
            ]

        return {
            "slug": lab.slug,
            "name": lab.name,
            "url": lab.url,
            "github_org": lab.github_org,
            "projects": projects,
            "recent_releases": releases,
        }
    finally:
        session.close()


def get_hn_posts(q: str = None, days: int = 30, limit: int = 20) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    session = SessionLocal()
    try:
        query = session.query(HNPost).filter(HNPost.posted_at >= cutoff)
        if q:
            query = query.filter(HNPost.title.ilike(f"%{q}%"))
        query = query.order_by(HNPost.points.desc()).limit(limit)
        posts = query.all()
        return [
            {
                "title": p.title,
                "url": p.url,
                "points": p.points,
                "num_comments": p.num_comments,
                "posted_at": _serialize(p.posted_at) if p.posted_at else None,
                "hn_id": p.hn_id,
            }
            for p in posts
        ]
    finally:
        session.close()


def get_briefings(domain: str = None) -> list[dict]:
    session = SessionLocal()
    try:
        query = session.query(Briefing)
        if domain:
            query = query.filter(Briefing.domain == domain)
        query = query.order_by(Briefing.domain, Briefing.slug)
        rows = query.all()
        return [
            {
                "slug": b.slug,
                "domain": b.domain,
                "title": b.title,
                "summary": b.summary,
                "verified_at": _serialize(b.verified_at) if b.verified_at else None,
            }
            for b in rows
        ]
    finally:
        session.close()


def get_briefing(slug: str) -> dict | None:
    session = SessionLocal()
    try:
        b = session.query(Briefing).filter(Briefing.slug == slug).first()
        if not b:
            return None
        return {
            "slug": b.slug,
            "domain": b.domain,
            "title": b.title,
            "summary": b.summary,
            "detail": b.detail,
            "evidence": b.evidence,
            "verified_at": _serialize(b.verified_at) if b.verified_at else None,
            "updated_at": _serialize(b.updated_at) if b.updated_at else None,
        }
    finally:
        session.close()
