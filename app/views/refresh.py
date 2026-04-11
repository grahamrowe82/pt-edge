import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.config.domains import DOMAIN_VIEW_MAP
from app.db import engine
from app.db import SessionLocal
from app.models import SyncLog

logger = logging.getLogger(__name__)

# Non-quality views in dependency order (before and after quality views)
_VIEWS_BEFORE_QUALITY = [
    "mv_dep_resolution",       # base: maps dep_name → repo_id (needed before quality views)
    "mv_momentum",             # base: no dependencies
    "mv_hype_ratio",           # base: no dependencies
    "mv_lab_velocity",         # base: no dependencies
    "mv_project_tier",         # base: no dependencies
    "mv_velocity",             # base: no dependencies
    "mv_download_trends",      # base: no MV dependencies (uses download_snapshots)
    "mv_lifecycle",            # depends on: mv_momentum
    "mv_traction_score",       # depends on: mv_velocity, mv_download_trends
    "mv_project_summary",      # depends on: mv_momentum, mv_hype_ratio, mv_project_tier, mv_velocity, mv_lifecycle, mv_traction_score, mv_download_trends
    "mv_usage_sessions",       # standalone: tool_usage only
    "mv_usage_daily_summary",  # depends on: mv_usage_sessions
    "mv_ai_repo_ecosystem",    # standalone: ai_repos stats by domain+subcategory
    "mv_nucleation_project",   # standalone: project-level nucleation signals
    "mv_nucleation_category",  # standalone: category creation velocity
]

_VIEWS_AFTER_QUALITY = [
    "mv_access_bot_demand",      # standalone: bot crawl demand from http_access_log
    "mv_allocation_scores",      # depends on: all quality views + ai_repo_snapshots + gsc + umami
    "mv_owner_demand",           # depends on: mv_access_bot_demand + ai_repos
    "mv_api_daily",              # standalone: api_usage daily rollup by transport/endpoint
    "mv_api_callers",            # standalone: per-caller profiles for lead identification
]

# Quality views are derived from the domain registry — no manual list needed.
VIEWS_IN_ORDER = (
    _VIEWS_BEFORE_QUALITY
    + sorted(DOMAIN_VIEW_MAP.values())  # standalone: one per domain
    + _VIEWS_AFTER_QUALITY
)


def refresh_all_views():
    """Refresh all materialized views in dependency order."""
    started_at = datetime.now(timezone.utc)
    refreshed = 0
    errors = []

    with engine.connect() as conn:
        for view_name in VIEWS_IN_ORDER:
            try:
                conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view_name}"))
                conn.commit()
                refreshed += 1
                logger.info(f"Refreshed {view_name}")
            except Exception as e:
                # CONCURRENTLY requires unique index; fall back to regular refresh
                conn.rollback()
                try:
                    conn.execute(text(f"REFRESH MATERIALIZED VIEW {view_name}"))
                    conn.commit()
                    refreshed += 1
                    logger.info(f"Refreshed {view_name} (non-concurrent)")
                except Exception as e2:
                    conn.rollback()
                    errors.append(f"{view_name}: {e2}")
                    logger.error(f"Failed to refresh {view_name}: {e2}")

    # Snapshot lifecycle stages for transition tracking
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO lifecycle_history (project_id, lifecycle_stage, snapshot_date)
                SELECT project_id, lifecycle_stage, CURRENT_DATE
                FROM mv_lifecycle
                ON CONFLICT (project_id, snapshot_date) DO UPDATE
                SET lifecycle_stage = EXCLUDED.lifecycle_stage
            """))
            conn.commit()
            logger.info("Snapshotted lifecycle stages to lifecycle_history")
    except Exception as e:
        logger.warning(f"Could not snapshot lifecycle stages: {e}")

    # Snapshot MCP quality scores for historical tracking
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO mcp_quality_snapshots
                    (repo_id, snapshot_date, quality_score, quality_tier,
                     maintenance_score, adoption_score, maturity_score,
                     community_score, risk_flags)
                SELECT id, CURRENT_DATE, quality_score, quality_tier,
                       maintenance_score, adoption_score, maturity_score,
                       community_score, risk_flags
                FROM mv_mcp_quality
                ON CONFLICT (repo_id, snapshot_date) DO UPDATE SET
                    quality_score = EXCLUDED.quality_score,
                    quality_tier = EXCLUDED.quality_tier,
                    maintenance_score = EXCLUDED.maintenance_score,
                    adoption_score = EXCLUDED.adoption_score,
                    maturity_score = EXCLUDED.maturity_score,
                    community_score = EXCLUDED.community_score,
                    risk_flags = EXCLUDED.risk_flags
            """))
            conn.commit()
            logger.info("Snapshotted MCP quality scores")
    except Exception as e:
        logger.warning(f"Could not snapshot MCP quality scores: {e}")

    # Snapshot quality scores for all non-MCP domains (derived from registry)
    for domain, view in (
        (d, v) for d, v in DOMAIN_VIEW_MAP.items() if d != "mcp"
    ):
        try:
            with engine.connect() as conn:
                conn.execute(text(f"""
                    INSERT INTO quality_snapshots
                        (repo_id, domain, snapshot_date, quality_score, quality_tier,
                         maintenance_score, adoption_score, maturity_score,
                         community_score, risk_flags)
                    SELECT id, :domain, CURRENT_DATE, quality_score, quality_tier,
                           maintenance_score, adoption_score, maturity_score,
                           community_score, risk_flags
                    FROM {view}
                    ON CONFLICT (repo_id, snapshot_date) DO UPDATE SET
                        quality_score = EXCLUDED.quality_score,
                        quality_tier = EXCLUDED.quality_tier,
                        maintenance_score = EXCLUDED.maintenance_score,
                        adoption_score = EXCLUDED.adoption_score,
                        maturity_score = EXCLUDED.maturity_score,
                        community_score = EXCLUDED.community_score,
                        risk_flags = EXCLUDED.risk_flags
                """), {"domain": domain})
                conn.commit()
                logger.info(f"Snapshotted {domain} quality scores")
        except Exception as e:
            logger.warning(f"Could not snapshot {domain} quality scores: {e}")

    # Snapshot ai_repo metrics for historical tracking
    try:
        import time as _time
        t0 = _time.time()
        with engine.connect() as conn:
            result = conn.execute(text("""
                INSERT INTO ai_repo_snapshots
                    (repo_id, snapshot_date, stars, forks, downloads_monthly, commits_30d)
                SELECT id, CURRENT_DATE, stars, forks, downloads_monthly, commits_30d
                FROM ai_repos
                ON CONFLICT (repo_id, snapshot_date) DO UPDATE SET
                    stars = EXCLUDED.stars,
                    forks = EXCLUDED.forks,
                    downloads_monthly = EXCLUDED.downloads_monthly,
                    commits_30d = EXCLUDED.commits_30d
            """))
            conn.commit()
            elapsed = _time.time() - t0
            logger.info(f"Snapshotted {result.rowcount} ai_repo metrics in {elapsed:.1f}s")
    except Exception as e:
        logger.warning(f"Could not snapshot ai_repo metrics: {e}")

    # Snapshot allocation scores
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                INSERT INTO allocation_score_snapshots
                    (domain, subcategory, snapshot_date, ehs, es,
                     gsc_impression_growth_7d, gsc_click_growth_7d,
                     gsc_position_improvement,
                     umami_pageviews_7d, umami_avg_sessions,
                     github_star_velocity_7d, github_new_repos_7d,
                     github_fork_acceleration_7d, gsc_coverage_ratio,
                     repo_count, total_stars, confidence_level,
                     surprise_ratio, position_strength,
                     ctr_vs_benchmark, domain_impressions_7d,
                     hn_posts_7d, hn_points_7d,
                     newsletter_mentions_7d, releases_7d, summary_ratio)
                SELECT domain, subcategory, CURRENT_DATE, ehs, es,
                       gsc_impression_growth_7d, gsc_click_growth_7d,
                       gsc_position_improvement,
                       umami_pageviews_7d, umami_avg_sessions,
                       github_star_velocity_7d, github_new_repos_7d,
                       github_fork_acceleration_7d, gsc_coverage_ratio,
                       repo_count, total_stars, confidence_level,
                       surprise_ratio, position_strength,
                       ctr_vs_benchmark, domain_impressions_7d,
                       hn_posts_7d, hn_points_7d,
                       newsletter_mentions_7d, releases_7d, summary_ratio
                FROM mv_allocation_scores
                ON CONFLICT (domain, subcategory, snapshot_date) DO UPDATE SET
                    ehs = EXCLUDED.ehs,
                    es = EXCLUDED.es,
                    gsc_impression_growth_7d = EXCLUDED.gsc_impression_growth_7d,
                    gsc_click_growth_7d = EXCLUDED.gsc_click_growth_7d,
                    gsc_position_improvement = EXCLUDED.gsc_position_improvement,
                    umami_pageviews_7d = EXCLUDED.umami_pageviews_7d,
                    umami_avg_sessions = EXCLUDED.umami_avg_sessions,
                    github_star_velocity_7d = EXCLUDED.github_star_velocity_7d,
                    github_new_repos_7d = EXCLUDED.github_new_repos_7d,
                    github_fork_acceleration_7d = EXCLUDED.github_fork_acceleration_7d,
                    gsc_coverage_ratio = EXCLUDED.gsc_coverage_ratio,
                    repo_count = EXCLUDED.repo_count,
                    total_stars = EXCLUDED.total_stars,
                    confidence_level = EXCLUDED.confidence_level,
                    surprise_ratio = EXCLUDED.surprise_ratio,
                    position_strength = EXCLUDED.position_strength,
                    ctr_vs_benchmark = EXCLUDED.ctr_vs_benchmark,
                    domain_impressions_7d = EXCLUDED.domain_impressions_7d,
                    hn_posts_7d = EXCLUDED.hn_posts_7d,
                    hn_points_7d = EXCLUDED.hn_points_7d,
                    newsletter_mentions_7d = EXCLUDED.newsletter_mentions_7d,
                    releases_7d = EXCLUDED.releases_7d,
                    summary_ratio = EXCLUDED.summary_ratio
            """))
            conn.commit()
            logger.info(f"Snapshotted {result.rowcount} allocation scores")
    except Exception as e:
        logger.warning(f"Could not snapshot allocation scores: {e}")

    # Log sync
    session = SessionLocal()
    try:
        log = SyncLog(
            sync_type="views",
            status="success" if not errors else "partial",
            records_written=refreshed,
            error_message="; ".join(errors) if errors else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        session.add(log)
        session.commit()
    finally:
        session.close()

    return {"refreshed": refreshed, "errors": errors}
