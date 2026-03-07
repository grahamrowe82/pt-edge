"""Add tiers, lifecycle stages, and project candidate sniffing

Revision ID: 002
Revises: 001_initial
Create Date: 2026-03-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "002"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Drop dependent views first (order matters) ---
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_project_summary CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_momentum CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_hype_ratio CASCADE")

    # --- 2. Add tier_override column to projects ---
    op.add_column("projects", sa.Column("tier_override", sa.Integer(), nullable=True))

    # --- 3. Create project_candidates table ---
    op.create_table(
        "project_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("github_url", sa.Text(), nullable=False),
        sa.Column("github_owner", sa.String(100), nullable=True),
        sa.Column("github_repo", sa.String(200), nullable=True),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("stars", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(50), nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_detail", sa.Text(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("github_url", name="uq_project_candidates_github_url"),
    )

    # --- 4. Recreate mv_momentum with has_7d_baseline and has_30d_baseline ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_momentum AS
WITH latest AS (
    SELECT DISTINCT ON (project_id)
        project_id, snapshot_date, stars
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
prev_7d AS (
    SELECT DISTINCT ON (gs.project_id)
        gs.project_id, gs.stars
    FROM github_snapshots gs
    JOIN latest l ON gs.project_id = l.project_id
    WHERE gs.snapshot_date <= l.snapshot_date - 7
    ORDER BY gs.project_id, gs.snapshot_date DESC
),
prev_30d AS (
    SELECT DISTINCT ON (gs.project_id)
        gs.project_id, gs.stars
    FROM github_snapshots gs
    JOIN latest l ON gs.project_id = l.project_id
    WHERE gs.snapshot_date <= l.snapshot_date - 30
    ORDER BY gs.project_id, gs.snapshot_date DESC
),
dl_latest AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
),
dl_prev_7d AS (
    SELECT DISTINCT ON (ds.project_id)
        ds.project_id, ds.downloads_monthly
    FROM download_snapshots ds
    JOIN (SELECT DISTINCT ON (project_id) project_id, snapshot_date FROM download_snapshots ORDER BY project_id, snapshot_date DESC) l
        ON ds.project_id = l.project_id
    WHERE ds.snapshot_date <= l.snapshot_date - 7
    ORDER BY ds.project_id, ds.snapshot_date DESC
),
dl_prev_30d AS (
    SELECT DISTINCT ON (ds.project_id)
        ds.project_id, ds.downloads_monthly
    FROM download_snapshots ds
    JOIN (SELECT DISTINCT ON (project_id) project_id, snapshot_date FROM download_snapshots ORDER BY project_id, snapshot_date DESC) l
        ON ds.project_id = l.project_id
    WHERE ds.snapshot_date <= l.snapshot_date - 30
    ORDER BY ds.project_id, ds.snapshot_date DESC
)
SELECT
    p.id AS project_id,
    p.name,
    p.category,
    COALESCE(l.stars, 0) AS stars_now,
    COALESCE(p7.stars, 0) AS stars_7d_ago,
    COALESCE(p30.stars, 0) AS stars_30d_ago,
    COALESCE(l.stars, 0) - COALESCE(p7.stars, 0) AS stars_7d_delta,
    COALESCE(l.stars, 0) - COALESCE(p30.stars, 0) AS stars_30d_delta,
    COALESCE(dl.downloads_monthly, 0) AS dl_monthly_now,
    COALESCE(dl7.downloads_monthly, 0) AS dl_monthly_7d_ago,
    COALESCE(dl30.downloads_monthly, 0) AS dl_monthly_30d_ago,
    COALESCE(dl.downloads_monthly, 0) - COALESCE(dl7.downloads_monthly, 0) AS dl_7d_delta,
    COALESCE(dl.downloads_monthly, 0) - COALESCE(dl30.downloads_monthly, 0) AS dl_30d_delta,
    CASE WHEN p7.stars IS NOT NULL THEN true ELSE false END AS has_7d_baseline,
    CASE WHEN p30.stars IS NOT NULL THEN true ELSE false END AS has_30d_baseline
FROM projects p
LEFT JOIN latest l ON p.id = l.project_id
LEFT JOIN prev_7d p7 ON p.id = p7.project_id
LEFT JOIN prev_30d p30 ON p.id = p30.project_id
LEFT JOIN dl_latest dl ON p.id = dl.project_id
LEFT JOIN dl_prev_7d dl7 ON p.id = dl7.project_id
LEFT JOIN dl_prev_30d dl30 ON p.id = dl30.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_momentum_project_id ON mv_momentum (project_id)")

    # --- 5. Recreate mv_hype_ratio with new bucket thresholds ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_hype_ratio AS
WITH latest_stars AS (
    SELECT DISTINCT ON (project_id)
        project_id, stars
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_downloads AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
)
SELECT
    p.id AS project_id,
    p.name,
    p.category,
    COALESCE(s.stars, 0) AS stars,
    COALESCE(d.downloads_monthly, 0) AS monthly_downloads,
    CASE
        WHEN COALESCE(d.downloads_monthly, 0) > 0
        THEN ROUND(COALESCE(s.stars, 0)::numeric / d.downloads_monthly, 4)
        ELSE NULL
    END AS hype_ratio,
    CASE
        WHEN COALESCE(d.downloads_monthly, 0) = 0 THEN 'no_downloads'
        WHEN CAST(COALESCE(s.stars, 0) AS NUMERIC) / d.downloads_monthly > 10.0 THEN 'hype'
        WHEN CAST(COALESCE(s.stars, 0) AS NUMERIC) / d.downloads_monthly > 1.0 THEN 'star_heavy'
        WHEN CAST(COALESCE(s.stars, 0) AS NUMERIC) / d.downloads_monthly > 0.01 THEN 'balanced'
        ELSE 'quiet_adoption'
    END AS hype_bucket
FROM projects p
LEFT JOIN latest_stars s ON p.id = s.project_id
LEFT JOIN latest_downloads d ON p.id = d.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_hype_ratio_project_id ON mv_hype_ratio (project_id)")

    # --- 6. Create mv_project_tier ---
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

    # --- 7. Create mv_lifecycle (depends on mv_momentum) ---
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

    # --- 8. Recreate mv_project_summary with tier and lifecycle joins ---
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
    # --- Drop new views ---
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_project_summary CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_lifecycle CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_project_tier CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_hype_ratio CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_momentum CASCADE")

    # --- Drop project_candidates table ---
    op.drop_table("project_candidates")

    # --- Remove tier_override column from projects ---
    op.drop_column("projects", "tier_override")

    # --- Recreate original mv_momentum from 001 ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_momentum AS
WITH latest AS (
    SELECT DISTINCT ON (project_id)
        project_id, snapshot_date, stars
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
prev_7d AS (
    SELECT DISTINCT ON (gs.project_id)
        gs.project_id, gs.stars
    FROM github_snapshots gs
    JOIN latest l ON gs.project_id = l.project_id
    WHERE gs.snapshot_date <= l.snapshot_date - 7
    ORDER BY gs.project_id, gs.snapshot_date DESC
),
prev_30d AS (
    SELECT DISTINCT ON (gs.project_id)
        gs.project_id, gs.stars
    FROM github_snapshots gs
    JOIN latest l ON gs.project_id = l.project_id
    WHERE gs.snapshot_date <= l.snapshot_date - 30
    ORDER BY gs.project_id, gs.snapshot_date DESC
),
dl_latest AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
),
dl_prev_7d AS (
    SELECT DISTINCT ON (ds.project_id)
        ds.project_id, ds.downloads_monthly
    FROM download_snapshots ds
    JOIN (SELECT DISTINCT ON (project_id) project_id, snapshot_date FROM download_snapshots ORDER BY project_id, snapshot_date DESC) l
        ON ds.project_id = l.project_id
    WHERE ds.snapshot_date <= l.snapshot_date - 7
    ORDER BY ds.project_id, ds.snapshot_date DESC
),
dl_prev_30d AS (
    SELECT DISTINCT ON (ds.project_id)
        ds.project_id, ds.downloads_monthly
    FROM download_snapshots ds
    JOIN (SELECT DISTINCT ON (project_id) project_id, snapshot_date FROM download_snapshots ORDER BY project_id, snapshot_date DESC) l
        ON ds.project_id = l.project_id
    WHERE ds.snapshot_date <= l.snapshot_date - 30
    ORDER BY ds.project_id, ds.snapshot_date DESC
)
SELECT
    p.id AS project_id,
    p.name,
    p.category,
    COALESCE(l.stars, 0) AS stars_now,
    COALESCE(p7.stars, 0) AS stars_7d_ago,
    COALESCE(p30.stars, 0) AS stars_30d_ago,
    COALESCE(l.stars, 0) - COALESCE(p7.stars, 0) AS stars_7d_delta,
    COALESCE(l.stars, 0) - COALESCE(p30.stars, 0) AS stars_30d_delta,
    COALESCE(dl.downloads_monthly, 0) AS dl_monthly_now,
    COALESCE(dl7.downloads_monthly, 0) AS dl_monthly_7d_ago,
    COALESCE(dl30.downloads_monthly, 0) AS dl_monthly_30d_ago,
    COALESCE(dl.downloads_monthly, 0) - COALESCE(dl7.downloads_monthly, 0) AS dl_7d_delta,
    COALESCE(dl.downloads_monthly, 0) - COALESCE(dl30.downloads_monthly, 0) AS dl_30d_delta
FROM projects p
LEFT JOIN latest l ON p.id = l.project_id
LEFT JOIN prev_7d p7 ON p.id = p7.project_id
LEFT JOIN prev_30d p30 ON p.id = p30.project_id
LEFT JOIN dl_latest dl ON p.id = dl.project_id
LEFT JOIN dl_prev_7d dl7 ON p.id = dl7.project_id
LEFT JOIN dl_prev_30d dl30 ON p.id = dl30.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_momentum_project_id ON mv_momentum (project_id)")

    # --- Recreate original mv_hype_ratio from 001 ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_hype_ratio AS
WITH latest_stars AS (
    SELECT DISTINCT ON (project_id)
        project_id, stars
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_downloads AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
)
SELECT
    p.id AS project_id,
    p.name,
    p.category,
    COALESCE(s.stars, 0) AS stars,
    COALESCE(d.downloads_monthly, 0) AS monthly_downloads,
    CASE
        WHEN COALESCE(d.downloads_monthly, 0) > 0
        THEN ROUND(COALESCE(s.stars, 0)::numeric / d.downloads_monthly, 4)
        ELSE NULL
    END AS hype_ratio,
    CASE
        WHEN COALESCE(d.downloads_monthly, 0) = 0 THEN 'no_downloads'
        WHEN COALESCE(s.stars, 0)::numeric / d.downloads_monthly > 1.0 THEN 'hype'
        WHEN COALESCE(s.stars, 0)::numeric / d.downloads_monthly > 0.1 THEN 'balanced'
        ELSE 'quiet_adoption'
    END AS hype_bucket
FROM projects p
LEFT JOIN latest_stars s ON p.id = s.project_id
LEFT JOIN latest_downloads d ON p.id = d.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_hype_ratio_project_id ON mv_hype_ratio (project_id)")

    # --- Recreate original mv_project_summary from 001 ---
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
    COALESCE(cc.correction_count, 0) AS correction_count
FROM projects p
LEFT JOIN labs l ON p.lab_id = l.id
LEFT JOIN latest_gh gh ON p.id = gh.project_id
LEFT JOIN latest_dl dl ON p.id = dl.project_id
LEFT JOIN mv_momentum m ON p.id = m.project_id
LEFT JOIN mv_hype_ratio hr ON p.id = hr.project_id
LEFT JOIN latest_release lr ON p.id = lr.project_id
LEFT JOIN correction_counts cc ON LOWER(cc.topic) = LOWER(p.slug)
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_project_summary_project_id ON mv_project_summary (project_id)")
