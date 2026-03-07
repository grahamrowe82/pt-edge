"""Fix lifecycle dormant condition, add distribution-type-aware tiers

Revision ID: 003
Revises: 002
Create Date: 2026-03-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Add distribution_type and hf_model_id columns to projects ---
    op.add_column(
        "projects",
        sa.Column("distribution_type", sa.String(20), nullable=True, server_default="package"),
    )
    op.add_column(
        "projects",
        sa.Column("hf_model_id", sa.String(200), nullable=True),
    )

    # --- 2. Drop dependent views (order matters: summary depends on lifecycle and tier) ---
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_project_summary CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_lifecycle CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_project_tier CASCADE")

    # --- 3. Recreate mv_lifecycle with fixed dormant condition and unknown stage ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_lifecycle AS
WITH latest_gh AS (
    SELECT DISTINCT ON (project_id)
        project_id, stars, commits_30d, last_commit_at, snapshot_date
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_dl AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
),
release_stats AS (
    SELECT
        project_id,
        COUNT(*) AS total_releases,
        COUNT(*) FILTER (WHERE released_at >= NOW() - INTERVAL '30 days') AS releases_30d,
        COUNT(*) FILTER (WHERE released_at >= NOW() - INTERVAL '90 days') AS releases_90d,
        MAX(released_at) AS last_release_at,
        MIN(released_at) AS first_release_at
    FROM releases
    WHERE project_id IS NOT NULL
    GROUP BY project_id
),
hn_activity AS (
    SELECT
        project_id,
        COUNT(*) AS hn_posts_30d
    FROM hn_posts
    WHERE posted_at >= NOW() - INTERVAL '30 days'
      AND project_id IS NOT NULL
    GROUP BY project_id
)
SELECT
    p.id AS project_id,
    p.name,
    p.category,
    CASE
        WHEN gh.project_id IS NULL AND dl.project_id IS NULL
            THEN 'unknown'
        WHEN (gh.last_commit_at IS NULL OR gh.last_commit_at < NOW() - INTERVAL '180 days')
            AND (rs.last_release_at IS NULL OR rs.last_release_at < NOW() - INTERVAL '365 days')
            AND COALESCE(dl.downloads_monthly, 0) < 10000
            THEN 'dormant'
        WHEN (COALESCE(m.stars_7d_delta, 0) < 0 AND m.has_7d_baseline)
            OR (gh.last_commit_at IS NOT NULL AND gh.last_commit_at < NOW() - INTERVAL '60 days')
            OR (rs.last_release_at IS NOT NULL AND rs.last_release_at < NOW() - INTERVAL '180 days'
                AND COALESCE(rs.total_releases, 0) > 0)
            THEN 'fading'
        WHEN COALESCE(gh.stars, 0) > 10000
            AND COALESCE(dl.downloads_monthly, 0) > 100000
            AND COALESCE(gh.commits_30d, 0) > 0
            THEN 'established'
        WHEN COALESCE(m.stars_7d_delta, 0) > 0
            AND COALESCE(rs.releases_30d, 0) >= 1
            THEN 'growing'
        WHEN rs.first_release_at IS NOT NULL
            AND rs.first_release_at >= NOW() - INTERVAL '90 days'
            THEN 'launching'
        WHEN COALESCE(rs.total_releases, 0) < 3
            AND COALESCE(gh.stars, 0) < 5000
            THEN 'emerging'
        ELSE 'growing'
    END AS lifecycle_stage,
    COALESCE(gh.stars, 0) AS stars,
    COALESCE(dl.downloads_monthly, 0) AS monthly_downloads,
    COALESCE(gh.commits_30d, 0) AS commits_30d,
    COALESCE(rs.total_releases, 0) AS total_releases,
    COALESCE(rs.releases_30d, 0) AS releases_30d,
    rs.last_release_at,
    rs.first_release_at,
    gh.last_commit_at,
    COALESCE(hn.hn_posts_30d, 0) AS hn_posts_30d
FROM projects p
LEFT JOIN latest_gh gh ON p.id = gh.project_id
LEFT JOIN latest_dl dl ON p.id = dl.project_id
LEFT JOIN release_stats rs ON p.id = rs.project_id
LEFT JOIN mv_momentum m ON p.id = m.project_id
LEFT JOIN hn_activity hn ON p.id = hn.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_lifecycle_project_id ON mv_lifecycle (project_id)")

    # --- 4. Recreate mv_project_tier with distribution-type-aware logic ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_project_tier AS
WITH latest_gh AS (
    SELECT DISTINCT ON (project_id)
        project_id, stars
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_dl AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
)
SELECT
    p.id AS project_id,
    p.name,
    p.tier_override,
    COALESCE(gh.stars, 0) AS stars,
    COALESCE(dl.downloads_monthly, 0) AS monthly_downloads,
    CASE
        WHEN p.tier_override IS NOT NULL THEN p.tier_override
        WHEN COALESCE(p.distribution_type, 'package') IN ('binary', 'hosted', 'extension', 'model') THEN
            CASE
                WHEN COALESCE(gh.stars, 0) > 50000 THEN 1
                WHEN COALESCE(gh.stars, 0) > 20000 THEN 2
                WHEN COALESCE(gh.stars, 0) > 5000 THEN 3
                ELSE 4
            END
        WHEN COALESCE(dl.downloads_monthly, 0) > 10000000
            OR (COALESCE(gh.stars, 0) > 50000 AND COALESCE(dl.downloads_monthly, 0) > 1000000)
            THEN 1
        WHEN COALESCE(dl.downloads_monthly, 0) > 100000 OR COALESCE(gh.stars, 0) > 20000
            THEN 2
        WHEN COALESCE(dl.downloads_monthly, 0) > 10000 OR COALESCE(gh.stars, 0) > 5000
            THEN 3
        ELSE 4
    END AS tier,
    CASE
        WHEN p.tier_override IS NOT NULL THEN true ELSE false
    END AS is_override
FROM projects p
LEFT JOIN latest_gh gh ON p.id = gh.project_id
LEFT JOIN latest_dl dl ON p.id = dl.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_project_tier_project_id ON mv_project_tier (project_id)")

    # --- 5. Recreate mv_project_summary (same as 002, joining updated views) ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_project_summary AS
WITH latest_gh AS (
    SELECT DISTINCT ON (project_id)
        project_id, stars, forks, commits_30d, last_commit_at
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_dl AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_release AS (
    SELECT DISTINCT ON (project_id)
        project_id, released_at AS last_release_at, title AS last_release_title
    FROM releases
    WHERE project_id IS NOT NULL
    ORDER BY project_id, released_at DESC
),
correction_counts AS (
    SELECT
        topic,
        COUNT(*) AS correction_count
    FROM corrections
    WHERE status = 'active'
    GROUP BY topic
)
SELECT
    p.id AS project_id,
    p.name,
    p.slug,
    p.category,
    l.name AS lab_name,
    COALESCE(gh.stars, 0) AS stars,
    COALESCE(gh.forks, 0) AS forks,
    COALESCE(dl.downloads_monthly, 0) AS monthly_downloads,
    COALESCE(m.stars_7d_delta, 0) AS stars_7d_delta,
    COALESCE(m.stars_30d_delta, 0) AS stars_30d_delta,
    COALESCE(m.dl_30d_delta, 0) AS dl_30d_delta,
    hr.hype_ratio,
    hr.hype_bucket,
    lr.last_release_at,
    lr.last_release_title,
    EXTRACT(DAY FROM NOW() - lr.last_release_at)::int AS days_since_release,
    gh.last_commit_at,
    COALESCE(gh.commits_30d, 0) AS commits_30d,
    COALESCE(cc.correction_count, 0) AS correction_count,
    COALESCE(tier.tier, 4) AS tier,
    tier.is_override AS tier_is_override,
    lc.lifecycle_stage,
    m.has_7d_baseline,
    m.has_30d_baseline
FROM projects p
LEFT JOIN labs l ON p.lab_id = l.id
LEFT JOIN latest_gh gh ON p.id = gh.project_id
LEFT JOIN latest_dl dl ON p.id = dl.project_id
LEFT JOIN mv_momentum m ON p.id = m.project_id
LEFT JOIN mv_hype_ratio hr ON p.id = hr.project_id
LEFT JOIN latest_release lr ON p.id = lr.project_id
LEFT JOIN correction_counts cc ON LOWER(cc.topic) = LOWER(p.slug)
LEFT JOIN mv_project_tier tier ON p.id = tier.project_id
LEFT JOIN mv_lifecycle lc ON p.id = lc.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_project_summary_project_id ON mv_project_summary (project_id)")


def downgrade() -> None:
    # --- Drop the recreated views ---
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_project_summary CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_lifecycle CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_project_tier CASCADE")

    # --- Remove columns ---
    op.drop_column("projects", "hf_model_id")
    op.drop_column("projects", "distribution_type")

    # --- Recreate original mv_project_tier from 002 ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_project_tier AS
WITH latest_gh AS (
    SELECT DISTINCT ON (project_id)
        project_id, stars
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_dl AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
)
SELECT
    p.id AS project_id,
    p.name,
    p.tier_override,
    COALESCE(gh.stars, 0) AS stars,
    COALESCE(dl.downloads_monthly, 0) AS monthly_downloads,
    CASE
        WHEN p.tier_override IS NOT NULL THEN p.tier_override
        WHEN COALESCE(dl.downloads_monthly, 0) > 10000000
            OR (COALESCE(gh.stars, 0) > 50000 AND COALESCE(dl.downloads_monthly, 0) > 1000000)
            THEN 1
        WHEN COALESCE(dl.downloads_monthly, 0) > 100000 OR COALESCE(gh.stars, 0) > 20000
            THEN 2
        WHEN COALESCE(dl.downloads_monthly, 0) > 10000 OR COALESCE(gh.stars, 0) > 5000
            THEN 3
        ELSE 4
    END AS tier,
    CASE
        WHEN p.tier_override IS NOT NULL THEN true ELSE false
    END AS is_override
FROM projects p
LEFT JOIN latest_gh gh ON p.id = gh.project_id
LEFT JOIN latest_dl dl ON p.id = dl.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_project_tier_project_id ON mv_project_tier (project_id)")

    # --- Recreate original mv_lifecycle from 002 ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_lifecycle AS
WITH latest_gh AS (
    SELECT DISTINCT ON (project_id)
        project_id, stars, commits_30d, last_commit_at, snapshot_date
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_dl AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
),
release_stats AS (
    SELECT
        project_id,
        COUNT(*) AS total_releases,
        COUNT(*) FILTER (WHERE released_at >= NOW() - INTERVAL '30 days') AS releases_30d,
        COUNT(*) FILTER (WHERE released_at >= NOW() - INTERVAL '90 days') AS releases_90d,
        MAX(released_at) AS last_release_at,
        MIN(released_at) AS first_release_at
    FROM releases
    WHERE project_id IS NOT NULL
    GROUP BY project_id
),
hn_activity AS (
    SELECT
        project_id,
        COUNT(*) AS hn_posts_30d
    FROM hn_posts
    WHERE posted_at >= NOW() - INTERVAL '30 days'
      AND project_id IS NOT NULL
    GROUP BY project_id
)
SELECT
    p.id AS project_id,
    p.name,
    p.category,
    CASE
        WHEN (gh.last_commit_at IS NULL OR gh.last_commit_at < NOW() - INTERVAL '180 days')
            AND (rs.last_release_at IS NULL OR rs.last_release_at < NOW() - INTERVAL '365 days')
            THEN 'dormant'
        WHEN (COALESCE(m.stars_7d_delta, 0) < 0 AND m.has_7d_baseline)
            OR (gh.last_commit_at IS NOT NULL AND gh.last_commit_at < NOW() - INTERVAL '60 days')
            OR (rs.last_release_at IS NOT NULL AND rs.last_release_at < NOW() - INTERVAL '180 days'
                AND COALESCE(rs.total_releases, 0) > 0)
            THEN 'fading'
        WHEN COALESCE(gh.stars, 0) > 10000
            AND COALESCE(dl.downloads_monthly, 0) > 100000
            AND COALESCE(gh.commits_30d, 0) > 0
            THEN 'established'
        WHEN COALESCE(m.stars_7d_delta, 0) > 0
            AND COALESCE(rs.releases_30d, 0) >= 1
            THEN 'growing'
        WHEN rs.first_release_at IS NOT NULL
            AND rs.first_release_at >= NOW() - INTERVAL '90 days'
            THEN 'launching'
        WHEN COALESCE(rs.total_releases, 0) < 3
            AND COALESCE(gh.stars, 0) < 5000
            THEN 'emerging'
        ELSE 'growing'
    END AS lifecycle_stage,
    COALESCE(gh.stars, 0) AS stars,
    COALESCE(dl.downloads_monthly, 0) AS monthly_downloads,
    COALESCE(gh.commits_30d, 0) AS commits_30d,
    COALESCE(rs.total_releases, 0) AS total_releases,
    COALESCE(rs.releases_30d, 0) AS releases_30d,
    rs.last_release_at,
    rs.first_release_at,
    gh.last_commit_at,
    COALESCE(hn.hn_posts_30d, 0) AS hn_posts_30d
FROM projects p
LEFT JOIN latest_gh gh ON p.id = gh.project_id
LEFT JOIN latest_dl dl ON p.id = dl.project_id
LEFT JOIN release_stats rs ON p.id = rs.project_id
LEFT JOIN mv_momentum m ON p.id = m.project_id
LEFT JOIN hn_activity hn ON p.id = hn.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_lifecycle_project_id ON mv_lifecycle (project_id)")

    # --- Recreate original mv_project_summary from 002 ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_project_summary AS
WITH latest_gh AS (
    SELECT DISTINCT ON (project_id)
        project_id, stars, forks, commits_30d, last_commit_at
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_dl AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_release AS (
    SELECT DISTINCT ON (project_id)
        project_id, released_at AS last_release_at, title AS last_release_title
    FROM releases
    WHERE project_id IS NOT NULL
    ORDER BY project_id, released_at DESC
),
correction_counts AS (
    SELECT
        topic,
        COUNT(*) AS correction_count
    FROM corrections
    WHERE status = 'active'
    GROUP BY topic
)
SELECT
    p.id AS project_id,
    p.name,
    p.slug,
    p.category,
    l.name AS lab_name,
    COALESCE(gh.stars, 0) AS stars,
    COALESCE(gh.forks, 0) AS forks,
    COALESCE(dl.downloads_monthly, 0) AS monthly_downloads,
    COALESCE(m.stars_7d_delta, 0) AS stars_7d_delta,
    COALESCE(m.stars_30d_delta, 0) AS stars_30d_delta,
    COALESCE(m.dl_30d_delta, 0) AS dl_30d_delta,
    hr.hype_ratio,
    hr.hype_bucket,
    lr.last_release_at,
    lr.last_release_title,
    EXTRACT(DAY FROM NOW() - lr.last_release_at)::int AS days_since_release,
    gh.last_commit_at,
    COALESCE(gh.commits_30d, 0) AS commits_30d,
    COALESCE(cc.correction_count, 0) AS correction_count,
    COALESCE(tier.tier, 4) AS tier,
    tier.is_override AS tier_is_override,
    lc.lifecycle_stage,
    m.has_7d_baseline,
    m.has_30d_baseline
FROM projects p
LEFT JOIN labs l ON p.lab_id = l.id
LEFT JOIN latest_gh gh ON p.id = gh.project_id
LEFT JOIN latest_dl dl ON p.id = dl.project_id
LEFT JOIN mv_momentum m ON p.id = m.project_id
LEFT JOIN mv_hype_ratio hr ON p.id = hr.project_id
LEFT JOIN latest_release lr ON p.id = lr.project_id
LEFT JOIN correction_counts cc ON LOWER(cc.topic) = LOWER(p.slug)
LEFT JOIN mv_project_tier tier ON p.id = tier.project_id
LEFT JOIN mv_lifecycle lc ON p.id = lc.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_project_summary_project_id ON mv_project_summary (project_id)")
