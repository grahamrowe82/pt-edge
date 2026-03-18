"""Add dependency velocity snapshots and fork-to-star ratio

Revision ID: 041
Revises: 040
Create Date: 2026-03-18

New table: dep_velocity_snapshots for tracking reverse-dependency counts over time.
Extends mv_velocity with fork_star_ratio column.
Cascades to mv_project_summary.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "041"
down_revision: Union[str, None] = "040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Create dep_velocity_snapshots table ---
    op.execute("""
CREATE TABLE dep_velocity_snapshots (
    id SERIAL PRIMARY KEY,
    dep_name VARCHAR(200) NOT NULL,
    source VARCHAR(10) NOT NULL,
    dependent_count INTEGER NOT NULL,
    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
    UNIQUE (dep_name, source, snapshot_date)
)
    """)
    op.execute("CREATE INDEX idx_dep_velocity_pkg ON dep_velocity_snapshots (dep_name, source)")

    # --- 2. Drop dependent views top-down ---
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_project_summary CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_velocity CASCADE")

    # --- 3. Recreate mv_velocity with fork_star_ratio ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_velocity AS
WITH latest_gh AS (
    SELECT DISTINCT ON (project_id)
        project_id, commits_30d, contributors, stars, forks
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
)
SELECT
    p.id AS project_id,
    p.name,
    p.slug,
    p.category,
    COALESCE(gh.commits_30d, 0) AS commits_30d,
    COALESCE(gh.contributors, 0) AS contributors,
    COALESCE(gh.stars, 0) AS stars,
    COALESCE(gh.forks, 0) AS forks,
    CASE
        WHEN COALESCE(gh.contributors, 0) = 0 THEN NULL
        ELSE ROUND(COALESCE(gh.commits_30d, 0)::numeric / gh.contributors, 2)
    END AS commits_per_contributor,
    CASE
        WHEN COALESCE(gh.contributors, 0) >= 100 THEN true
        ELSE false
    END AS cpc_is_capped,
    CASE
        WHEN COALESCE(gh.commits_30d, 0) = 0 THEN 'dormant'
        WHEN COALESCE(gh.commits_30d, 0) <= 10 THEN 'slow'
        WHEN COALESCE(gh.commits_30d, 0) <= 50 THEN 'moderate'
        WHEN COALESCE(gh.commits_30d, 0) <= 200 THEN 'fast'
        ELSE 'hyperspeed'
    END AS velocity_band,
    CASE
        WHEN COALESCE(gh.stars, 0) > 0
        THEN ROUND(COALESCE(gh.forks, 0)::numeric / gh.stars, 4)
        ELSE NULL
    END AS fork_star_ratio
FROM projects p
LEFT JOIN latest_gh gh ON p.id = gh.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_velocity_project_id ON mv_velocity (project_id)")

    # --- 4. Recreate mv_project_summary with fork_star_ratio ---
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
    m.has_30d_baseline,
    vel.velocity_band,
    vel.commits_per_contributor,
    vel.cpc_is_capped,
    vel.fork_star_ratio,
    COALESCE(m.commits_7d_delta, 0) AS commits_7d_delta,
    COALESCE(m.commits_30d_delta, 0) AS commits_30d_delta
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
LEFT JOIN mv_velocity vel ON p.id = vel.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_project_summary_project_id ON mv_project_summary (project_id)")


def downgrade() -> None:
    # --- 1. Drop dep_velocity_snapshots ---
    op.execute("DROP TABLE IF EXISTS dep_velocity_snapshots CASCADE")

    # --- 2. Restore mv_velocity without fork_star_ratio ---
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_project_summary CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_velocity CASCADE")

    op.execute("""
CREATE MATERIALIZED VIEW mv_velocity AS
WITH latest_gh AS (
    SELECT DISTINCT ON (project_id)
        project_id, commits_30d, contributors
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
)
SELECT
    p.id AS project_id,
    p.name,
    p.slug,
    p.category,
    COALESCE(gh.commits_30d, 0) AS commits_30d,
    COALESCE(gh.contributors, 0) AS contributors,
    CASE
        WHEN COALESCE(gh.contributors, 0) = 0 THEN NULL
        ELSE ROUND(COALESCE(gh.commits_30d, 0)::numeric / gh.contributors, 2)
    END AS commits_per_contributor,
    CASE
        WHEN COALESCE(gh.contributors, 0) >= 100 THEN true
        ELSE false
    END AS cpc_is_capped,
    CASE
        WHEN COALESCE(gh.commits_30d, 0) = 0 THEN 'dormant'
        WHEN COALESCE(gh.commits_30d, 0) <= 10 THEN 'slow'
        WHEN COALESCE(gh.commits_30d, 0) <= 50 THEN 'moderate'
        WHEN COALESCE(gh.commits_30d, 0) <= 200 THEN 'fast'
        ELSE 'hyperspeed'
    END AS velocity_band
FROM projects p
LEFT JOIN latest_gh gh ON p.id = gh.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_velocity_project_id ON mv_velocity (project_id)")

    # --- 3. Restore mv_project_summary without fork_star_ratio ---
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
    m.has_30d_baseline,
    vel.velocity_band,
    vel.commits_per_contributor,
    vel.cpc_is_capped,
    COALESCE(m.commits_7d_delta, 0) AS commits_7d_delta,
    COALESCE(m.commits_30d_delta, 0) AS commits_30d_delta
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
LEFT JOIN mv_velocity vel ON p.id = vel.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_project_summary_project_id ON mv_project_summary (project_id)")
