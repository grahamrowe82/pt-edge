"""Structured data access for the REST API. Returns Python dicts, not text."""

import logging
from datetime import datetime, date, timezone, timedelta

from sqlalchemy import text

from app.db import readonly_engine, SessionLocal
from app.models import Project, Lab, Release, HNPost, GitHubSnapshot, DownloadSnapshot, Briefing, CommercialProject, Methodology

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


def get_transitions(days: int = 30) -> list[dict]:
    with readonly_engine.connect() as conn:
        rows = conn.execute(
            text("""
                WITH ranked AS (
                    SELECT project_id, lifecycle_stage, snapshot_date,
                           ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY snapshot_date DESC) AS rn
                    FROM lifecycle_history
                    WHERE snapshot_date >= CURRENT_DATE - :days
                ),
                transitions AS (
                    SELECT curr.project_id,
                           prev.lifecycle_stage AS previous_stage,
                           curr.lifecycle_stage AS current_stage,
                           prev.snapshot_date AS previous_date,
                           curr.snapshot_date AS current_date
                    FROM ranked curr
                    JOIN ranked prev ON curr.project_id = prev.project_id
                    WHERE curr.rn = 1 AND prev.rn = 2
                      AND curr.lifecycle_stage != prev.lifecycle_stage
                )
                SELECT t.*, p.name, p.slug, p.category
                FROM transitions t
                JOIN projects p ON t.project_id = p.id
                ORDER BY t.current_date DESC
            """),
            {"days": days},
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


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
            "stack_layer": proj.stack_layer,
            "domain": proj.domain,
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

            momentum_contrib = _safe_mv_query(conn, """
                SELECT contributors_30d_delta
                FROM mv_momentum WHERE project_id = :pid
            """, {"pid": proj.id})

            velocity = _safe_mv_query(conn, """
                SELECT velocity_band, commits_per_contributor, cpc_is_capped, contributors, fork_star_ratio
                FROM mv_velocity WHERE project_id = :pid
            """, {"pid": proj.id})

            if tier_rows:
                result["tier"] = tier_rows[0].get("tier")
            if lc_rows:
                result["lifecycle_stage"] = lc_rows[0].get("lifecycle_stage")
            if momentum:
                result["momentum"] = momentum[0]
            if hype:
                result["hype"] = hype[0]
            if velocity:
                vel_data = velocity[0]
                if momentum_contrib:
                    vel_data["contributors_30d_delta"] = momentum_contrib[0].get("contributors_30d_delta")
                result["velocity"] = vel_data

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

        # LLM-generated brief
        with readonly_engine.connect() as conn:
            brief_rows = _safe_mv_query(conn, """
                SELECT title, summary, evidence, generated_at
                FROM project_briefs WHERE project_id = :pid
            """, {"pid": proj.id})
            if brief_rows:
                result["brief"] = brief_rows[0]

        return result
    finally:
        session.close()


def search_projects(q: str = None, category: str = None, stack_layer: str = None, domain: str = None, limit: int = 20) -> list[dict]:
    session = SessionLocal()
    try:
        query = session.query(Project)
        if q:
            query = query.filter(
                (Project.name.ilike(f"%{q}%")) | (Project.slug.ilike(f"%{q}%"))
            )
        if category:
            query = query.filter(Project.category == category)
        if stack_layer:
            query = query.filter(Project.stack_layer == stack_layer)
        if domain:
            query = query.filter(Project.domain == domain)
        query = query.order_by(Project.name).limit(limit)
        rows = query.all()
        return [
            {
                "slug": p.slug,
                "name": p.name,
                "category": p.category,
                "description": p.description,
                "lab": p.lab.name if p.lab else None,
                "stack_layer": p.stack_layer,
                "domain": p.domain,
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
        mv_vel = {}
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
            for r in _safe_mv_query(conn, """
                SELECT project_id, velocity_band, commits_per_contributor, cpc_is_capped, contributors, fork_star_ratio
                FROM mv_velocity WHERE project_id = ANY(:pids)
            """, {"pids": project_ids}):
                mv_vel[int(r["project_id"])] = {k: v for k, v in r.items() if k != "project_id"}

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
                "stack_layer": proj.stack_layer,
                "domain": proj.domain,
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
            if proj.id in mv_vel:
                result["velocity"] = mv_vel[proj.id]
            if proj.id in rel_map:
                result["recent_releases"] = rel_map[proj.id]
            results.append(result)
        return results
    finally:
        session.close()


def get_trending(category: str = None, stack_layer: str = None, domain: str = None, window: str = "7d", limit: int = 20) -> list[dict]:
    delta_col = "stars_7d_delta" if window == "7d" else "stars_30d_delta"
    conditions = []
    params: dict = {}
    if category:
        conditions.append("s.category = :cat")
        params["cat"] = category
    if stack_layer:
        conditions.append("s.stack_layer = :stack_layer")
        params["stack_layer"] = stack_layer
    if domain:
        conditions.append("s.domain = :domain")
        params["domain"] = domain
    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with readonly_engine.connect() as conn:
        rows = _safe_mv_query(conn, f"""
            SELECT s.slug, s.name, s.category, s.stack_layer, s.domain,
                   s.stars, s.forks, s.monthly_downloads,
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


def get_velocity(category: str = None, stack_layer: str = None, domain: str = None, band: str = None, sort: str = "commits_30d", limit: int = 20) -> list[dict]:
    conditions = []
    params: dict = {"lim": limit}
    if category:
        conditions.append("s.category = :cat")
        params["cat"] = category
    if stack_layer:
        conditions.append("s.stack_layer = :stack_layer")
        params["stack_layer"] = stack_layer
    if domain:
        conditions.append("s.domain = :domain")
        params["domain"] = domain
    if band:
        conditions.append("vel.velocity_band = :band")
        params["band"] = band

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sort_map = {
        "commits_30d": "s.commits_30d DESC NULLS LAST",
        "commits_delta": "s.commits_30d_delta DESC NULLS LAST",
        "cpc": "vel.commits_per_contributor DESC NULLS LAST",
    }
    order = sort_map.get(sort, sort_map["commits_30d"])

    with readonly_engine.connect() as conn:
        rows = _safe_mv_query(conn, f"""
            SELECT s.slug, s.name, s.category, s.stack_layer, s.domain,
                   s.stars, s.commits_30d,
                   s.commits_7d_delta, s.commits_30d_delta,
                   s.contributors_30d_delta,
                   vel.velocity_band, vel.commits_per_contributor, vel.cpc_is_capped,
                   vel.contributors, vel.fork_star_ratio,
                   s.lifecycle_stage, COALESCE(s.tier, 4) AS tier
            FROM mv_project_summary s
            JOIN mv_velocity vel ON s.project_id = vel.project_id
            {where_clause}
            ORDER BY {order}
            LIMIT :lim
        """, params)
    return rows


def get_contributor_trending(stack_layer: str = None, limit: int = 20) -> list[dict]:
    conditions = ["s.contributors_30d_delta > 0"]
    params: dict = {"lim": limit}
    if stack_layer:
        conditions.append("s.stack_layer = :stack_layer")
        params["stack_layer"] = stack_layer

    where_clause = "WHERE " + " AND ".join(conditions)

    with readonly_engine.connect() as conn:
        rows = _safe_mv_query(conn, f"""
            SELECT s.slug, s.name, s.category, s.stack_layer, s.domain,
                   s.stars, s.commits_30d, s.contributors_30d_delta,
                   vel.contributors, vel.velocity_band,
                   s.lifecycle_stage, COALESCE(s.tier, 4) AS tier
            FROM mv_project_summary s
            LEFT JOIN mv_velocity vel ON s.project_id = vel.project_id
            {where_clause}
            ORDER BY s.contributors_30d_delta DESC NULLS LAST
            LIMIT :lim
        """, params)
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

        # Lifecycle transitions
        transitions = get_transitions(days=days)[:10]

        return {"releases": releases, "trending": trending, "hn": hn, "transitions": transitions}
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


def get_dependents(package_name: str, source: str = None, include_dev: bool = False, limit: int = 20) -> dict:
    with readonly_engine.connect() as conn:
        # Summary counts
        summary = conn.execute(
            text("""
                SELECT COUNT(DISTINCT pd.repo_id) as dependent_count,
                       COUNT(DISTINCT pd.repo_id) FILTER (WHERE pd.source = 'pypi') as pypi_count,
                       COUNT(DISTINCT pd.repo_id) FILTER (WHERE pd.source = 'npm') as npm_count
                FROM package_deps pd WHERE pd.dep_name = :pkg
            """),
            {"pkg": package_name},
        ).fetchone()

        # Dependent repos
        rows = conn.execute(
            text("""
                SELECT ar.full_name, ar.stars, ar.domain, ar.language,
                       pd.dep_spec, pd.source, pd.is_dev
                FROM package_deps pd
                JOIN ai_repos ar ON pd.repo_id = ar.id
                WHERE pd.dep_name = :pkg
                  AND (:source IS NULL OR pd.source = :source)
                  AND (:include_dev OR pd.is_dev = false)
                ORDER BY ar.stars DESC
                LIMIT :limit
            """),
            {"pkg": package_name, "source": source, "include_dev": include_dev, "limit": limit},
        ).fetchall()

    s = summary._mapping if summary else {}
    result = {
        "package_name": package_name,
        "dependent_count": s.get("dependent_count", 0),
        "by_source": {
            "pypi": s.get("pypi_count", 0),
            "npm": s.get("npm_count", 0),
        },
        "dependents": [
            {
                "repo": r._mapping["full_name"],
                "stars": r._mapping["stars"],
                "domain": r._mapping["domain"],
                "language": r._mapping["language"],
                "dep_spec": r._mapping["dep_spec"],
                "source": r._mapping["source"],
                "is_dev": r._mapping["is_dev"],
            }
            for r in rows
        ],
    }

    # Domain spread
    with readonly_engine.connect() as conn:
        domain_rows = conn.execute(
            text("""
                SELECT ar.domain, COUNT(DISTINCT pd.repo_id) AS repo_count
                FROM package_deps pd
                JOIN ai_repos ar ON pd.repo_id = ar.id
                WHERE pd.dep_name = :pkg
                  AND (:source IS NULL OR pd.source = :source)
                  AND ar.domain IS NOT NULL
                GROUP BY ar.domain
                ORDER BY repo_count DESC
            """),
            {"pkg": package_name, "source": source},
        ).fetchall()

    if domain_rows:
        result["domain_spread"] = {
            "domain_count": len(domain_rows),
            "domains": [
                {"domain": r._mapping["domain"], "repo_count": r._mapping["repo_count"]}
                for r in domain_rows
            ],
        }

    # Velocity: compare two most recent snapshots
    with readonly_engine.connect() as conn:
        velocity_rows = _safe_mv_query(conn, """
            SELECT dependent_count, snapshot_date
            FROM dep_velocity_snapshots
            WHERE dep_name = :pkg AND source = :src
            ORDER BY snapshot_date DESC
            LIMIT 2
        """, {"pkg": package_name, "src": source or "pypi"})

    if velocity_rows:
        latest = velocity_rows[0]
        velocity = {
            "dependent_count": latest["dependent_count"],
            "previous_count": None,
            "delta": None,
            "snapshot_date": latest["snapshot_date"],
        }
        if len(velocity_rows) > 1:
            prev = velocity_rows[1]
            velocity["previous_count"] = prev["dependent_count"]
            velocity["delta"] = int(latest["dependent_count"]) - int(prev["dependent_count"])
        result["velocity"] = velocity

    return result


def get_commercial_projects(category: str = None, limit: int = 20) -> list[dict]:
    session = SessionLocal()
    try:
        query = session.query(CommercialProject)
        if category:
            query = query.filter(CommercialProject.category == category)
        query = query.order_by(CommercialProject.name).limit(limit)
        rows = query.all()
        return [
            {
                "slug": p.slug,
                "name": p.name,
                "url": p.url,
                "category": p.category,
                "description": p.description,
                "pricing_model": p.pricing_model,
                "last_verified_at": _serialize(p.last_verified_at) if p.last_verified_at else None,
                "source": "curated",
            }
            for p in rows
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


def get_methodology_list(category: str = None) -> list[dict]:
    session = SessionLocal()
    try:
        query = session.query(Methodology)
        if category:
            query = query.filter(Methodology.category == category)
        query = query.order_by(Methodology.category, Methodology.topic)
        rows = query.all()
        return [
            {
                "topic": m.topic,
                "category": m.category,
                "title": m.title,
                "summary": m.summary,
                "updated_at": _serialize(m.updated_at) if m.updated_at else None,
            }
            for m in rows
        ]
    finally:
        session.close()


def get_methodology_detail(topic: str) -> dict | None:
    session = SessionLocal()
    try:
        m = session.query(Methodology).filter(Methodology.topic == topic).first()
        if not m:
            return None
        return {
            "topic": m.topic,
            "category": m.category,
            "title": m.title,
            "summary": m.summary,
            "detail": m.detail,
            "updated_at": _serialize(m.updated_at) if m.updated_at else None,
        }
    finally:
        session.close()


def get_dep_trending(source: str = None, limit: int = 20, min_dependents: int = 3) -> list[dict]:
    conditions = ["latest.rn = 1", "prev.rn = 2"]
    params: dict = {"lim": limit, "min_dep": min_dependents}
    if source:
        conditions.append("latest.source = :src")
        params["src"] = source

    where = "WHERE " + " AND ".join(conditions)

    with readonly_engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                WITH ranked AS (
                    SELECT dep_name, source, dependent_count, snapshot_date,
                           ROW_NUMBER() OVER (PARTITION BY dep_name, source ORDER BY snapshot_date DESC) AS rn
                    FROM dep_velocity_snapshots
                ),
                domain_counts AS (
                    SELECT pd.dep_name, COUNT(DISTINCT ar.domain) AS domain_count
                    FROM package_deps pd
                    JOIN ai_repos ar ON pd.repo_id = ar.id
                    WHERE ar.domain IS NOT NULL
                    GROUP BY pd.dep_name
                )
                SELECT latest.dep_name, latest.source,
                       latest.dependent_count,
                       prev.dependent_count AS previous_count,
                       latest.dependent_count - prev.dependent_count AS dep_delta,
                       latest.snapshot_date,
                       dc.domain_count
                FROM ranked latest
                JOIN ranked prev ON latest.dep_name = prev.dep_name AND latest.source = prev.source
                LEFT JOIN domain_counts dc ON latest.dep_name = dc.dep_name
                {where}
                  AND latest.dependent_count >= :min_dep
                ORDER BY dep_delta DESC
                LIMIT :lim
            """),
            params,
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_project_brief(slug: str) -> dict | None:
    """Get the LLM-generated brief for a single project."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT pb.title, pb.summary, pb.evidence, pb.generated_at, pb.updated_at
                FROM project_briefs pb
                JOIN projects p ON pb.project_id = p.id
                WHERE p.slug = :slug
            """),
            {"slug": slug},
        ).fetchall()
    if not rows:
        return None
    return _row_to_dict(rows[0])


def get_project_briefs_list(domain: str = None, tier: int = None, limit: int = 50) -> list[dict]:
    """List project briefs with optional domain/tier filters."""
    conditions = []
    params: dict = {"lim": limit}
    if domain:
        conditions.append("s.domain = :domain")
        params["domain"] = domain
    if tier is not None:
        conditions.append("COALESCE(s.tier, 4) = :tier")
        params["tier"] = tier
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with readonly_engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT s.slug, s.name, s.domain, COALESCE(s.tier, 4) AS tier,
                       pb.title, pb.summary, pb.evidence, pb.generated_at
                FROM project_briefs pb
                JOIN mv_project_summary s ON pb.project_id = s.project_id
                {where}
                ORDER BY s.stars DESC NULLS LAST
                LIMIT :lim
            """),
            params,
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_domain_brief(domain: str) -> dict | None:
    """Get the LLM-generated landscape brief for a domain."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT domain, title, summary, evidence, generated_at, updated_at
                FROM domain_briefs
                WHERE domain = :domain
            """),
            {"domain": domain},
        ).fetchall()
    if not rows:
        return None
    return _row_to_dict(rows[0])


def get_papers(q: str = None, project_slug: str = None, year: int = None, limit: int = 20) -> list[dict]:
    with readonly_engine.connect() as conn:
        conditions = []
        params: dict = {"limit": limit}

        if q:
            conditions.append("p.title ILIKE :q")
            params["q"] = f"%{q}%"
        if project_slug:
            conditions.append("proj.slug = :slug")
            params["slug"] = project_slug
        if year:
            conditions.append("p.year = :year")
            params["year"] = year

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        rows = conn.execute(
            text(f"""
                SELECT p.semantic_scholar_id, p.arxiv_id, p.doi, p.title,
                       p.authors, p.abstract, p.venue, p.year,
                       p.publication_date, p.citation_count, p.open_access_url,
                       proj.slug AS project_slug, proj.name AS project_name
                FROM papers p
                LEFT JOIN projects proj ON p.project_id = proj.id
                {where}
                ORDER BY p.citation_count DESC
                LIMIT :limit
            """),
            params,
        ).fetchall()

    return [_row_to_dict(r) for r in rows]
