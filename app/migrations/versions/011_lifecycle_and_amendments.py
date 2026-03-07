"""Fix lifecycle fading logic, change ELSE to stable, add amendments columns

Revision ID: 011
Revises: 010
Create Date: 2026-03-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Add amendments columns ---
    op.add_column("corrections", sa.Column("amendments", sa.Text, nullable=True))
    op.add_column("article_pitches", sa.Column("amendments", sa.Text, nullable=True))

    # --- 2. Drop dependent views (order matters: summary depends on lifecycle) ---
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_project_summary CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_lifecycle CASCADE")

    # --- 3. Recreate mv_lifecycle with fixed fading + stable fallback ---
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
        -- 1. Unknown (no data at all)
        WHEN gh.project_id IS NULL AND dl.project_id IS NULL
            THEN 'unknown'

        -- 2. Dormant (dead project)
        WHEN (gh.last_commit_at IS NULL OR gh.last_commit_at < NOW() - INTERVAL '180 days')
            AND (rs.last_release_at IS NULL OR rs.last_release_at < NOW() - INTERVAL '365 days')
            AND COALESCE(dl.downloads_monthly, 0) < 10000
            THEN 'dormant'

        -- 3a. Fading — stalled: was active, now no commits and no recent releases
        WHEN COALESCE(gh.commits_30d, 0) = 0
            AND COALESCE(rs.total_releases, 0) > 0
            AND COALESCE(rs.releases_30d, 0) = 0
            AND rs.last_release_at < NOW() - INTERVAL '90 days'
            THEN 'fading'

        -- 3b. Fading — declining stars or stale commits/releases
        WHEN (COALESCE(m.stars_7d_delta, 0) < 0 AND m.has_7d_baseline)
            OR (gh.last_commit_at IS NOT NULL AND gh.last_commit_at < NOW() - INTERVAL '60 days')
            OR (rs.last_release_at IS NOT NULL AND rs.last_release_at < NOW() - INTERVAL '180 days'
                AND COALESCE(rs.total_releases, 0) > 0)
            THEN 'fading'

        -- 4. Established (mature, stable, active)
        WHEN COALESCE(gh.stars, 0) > 10000
            AND COALESCE(dl.downloads_monthly, 0) > 100000
            AND COALESCE(gh.commits_30d, 0) > 0
            THEN 'established'

        -- 5. Growing (actively developing + releasing)
        WHEN COALESCE(m.stars_7d_delta, 0) > 0
            AND COALESCE(rs.releases_30d, 0) >= 1
            THEN 'growing'

        -- 6. Launching (new, <90 days old)
        WHEN rs.first_release_at IS NOT NULL
            AND rs.first_release_at >= NOW() - INTERVAL '90 days'
            THEN 'launching'

        -- 7. Emerging (prototype stage)
        WHEN COALESCE(rs.total_releases, 0) < 3
            AND COALESCE(gh.stars, 0) < 5000
            THEN 'emerging'

        -- 8. Fallback — unknown trajectory is not "growing"
        ELSE 'stable'
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

    # --- 4. Recreate mv_project_summary (depends on mv_lifecycle) ---
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
    # Drop recreated views
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_project_summary CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_lifecycle CASCADE")

    # Remove amendments columns
    op.drop_column("article_pitches", "amendments")
    op.drop_column("corrections", "amendments")

    # Recreate original mv_lifecycle from 010 (same as 003)
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

    # Recreate original mv_project_summary
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
