"""Add development_pace to mv_velocity, fix browser-use pypi linkage

Revision ID: 048
Revises: 047
Create Date: 2026-03-27

Adds development_pace column to mv_velocity: 'human' (<=20 commits/contributor),
'machine-assisted' (20-50), 'machine-speed' (50+). Cascades to mv_project_summary.
Fixes browser-use pypi_package linkage for traction score adoption component.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "048"
down_revision: Union[str, None] = "047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Drop dependent views top-down ---
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_project_summary CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_traction_score CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_velocity CASCADE")

    # --- 2. Recreate mv_velocity with development_pace ---
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
    END AS fork_star_ratio,
    CASE
        WHEN COALESCE(gh.contributors, 0) = 0 THEN NULL
        WHEN ROUND(COALESCE(gh.commits_30d, 0)::numeric / gh.contributors, 2) <= 20 THEN 'human'
        WHEN ROUND(COALESCE(gh.commits_30d, 0)::numeric / gh.contributors, 2) <= 50 THEN 'machine-assisted'
        ELSE 'machine-speed'
    END AS development_pace
FROM projects p
LEFT JOIN latest_gh gh ON p.id = gh.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_velocity_project_id ON mv_velocity (project_id)")

    # --- 3. Recreate mv_traction_score (unchanged, depends on mv_velocity) ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_traction_score AS
WITH latest_gh AS (
    SELECT DISTINCT ON (project_id)
        project_id, stars, forks
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_dl AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
),
dep_counts AS (
    SELECT p.id AS project_id, COALESCE(a.dependency_count, 0) AS dependency_count
    FROM projects p
    LEFT JOIN ai_repos a ON a.id = p.ai_repo_id
),
raw_scores AS (
    SELECT
        p.id AS project_id,
        p.name,
        p.slug,
        LEAST(20, COALESCE(vel.fork_star_ratio, 0) * 100) AS fork_score,
        CASE
            WHEN COALESCE(gh.stars, 0) = 0 THEN 0
            ELSE LEAST(25, (COALESCE(dl.downloads_monthly, 0)::numeric / NULLIF(gh.stars, 0)) * 2.5)
        END AS adoption_score,
        CASE
            WHEN dc.dependency_count = 0 THEN 0
            ELSE LEAST(20, LN(dc.dependency_count + 1) * 5)
        END AS dependency_score,
        CASE
            WHEN COALESCE(vel.commits_30d, 0) = 0 THEN 0
            WHEN vel.commits_30d <= 10 THEN 5
            WHEN vel.commits_30d <= 50 THEN 10
            WHEN vel.commits_30d <= 200 THEN 15
            ELSE 20
        END AS velocity_score,
        CASE
            WHEN COALESCE(vel.contributors, 0) <= 1 THEN 0
            WHEN vel.contributors <= 5 THEN 5
            WHEN vel.contributors <= 20 THEN 10
            ELSE 15
        END AS contributor_score,
        COALESCE(vel.fork_star_ratio, 0) AS fork_star_ratio,
        COALESCE(dl.downloads_monthly, 0) AS monthly_downloads,
        COALESCE(gh.stars, 0) AS stars,
        dc.dependency_count,
        COALESCE(vel.contributors, 0) AS contributors,
        COALESCE(vel.commits_30d, 0) AS commits_30d,
        COALESCE(dt.dl_trend, 'stable') AS dl_trend
    FROM projects p
    LEFT JOIN latest_gh gh ON p.id = gh.project_id
    LEFT JOIN latest_dl dl ON p.id = dl.project_id
    LEFT JOIN mv_velocity vel ON p.id = vel.project_id
    LEFT JOIN dep_counts dc ON p.id = dc.project_id
    LEFT JOIN mv_download_trends dt ON p.id = dt.project_id
    WHERE p.is_active = true
)
SELECT
    project_id,
    name,
    slug,
    ROUND(fork_score + adoption_score + dependency_score + velocity_score + contributor_score)::int AS traction_score,
    fork_score,
    adoption_score,
    dependency_score,
    velocity_score,
    contributor_score,
    CASE
        WHEN fork_star_ratio > 0.15 AND dependency_count > 5 THEN 'infrastructure'
        WHEN contributors > 10 AND commits_30d > 20 THEN 'community-driven'
        WHEN stars > 1000 AND monthly_downloads < stars * 0.5 AND dependency_count < 3 THEN 'hype'
        WHEN monthly_downloads > stars * 5 AND stars < 5000 THEN 'stealth-adoption'
        WHEN contributors <= 1 AND commits_30d > 50 THEN 'company-driven'
        ELSE 'balanced'
    END AS traction_bucket,
    fork_star_ratio,
    monthly_downloads,
    stars,
    dependency_count,
    contributors,
    commits_30d,
    dl_trend
FROM raw_scores
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_traction_score_project_id ON mv_traction_score (project_id)")

    # --- 4. Recreate mv_project_summary with development_pace ---
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
    p.domain,
    p.stack_layer,
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
    vel.development_pace,
    COALESCE(m.commits_7d_delta, 0) AS commits_7d_delta,
    COALESCE(m.commits_30d_delta, 0) AS commits_30d_delta,
    COALESCE(m.contributors_30d_delta, 0) AS contributors_30d_delta,
    ts.traction_score,
    ts.traction_bucket,
    dt.dl_trend,
    dt.dl_weekly_velocity
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
LEFT JOIN mv_traction_score ts ON p.id = ts.project_id
LEFT JOIN mv_download_trends dt ON p.id = dt.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_project_summary_project_id ON mv_project_summary (project_id)")

    # --- 5. Fix browser-use pypi_package linkage ---
    op.execute("UPDATE projects SET pypi_package = 'browser-use' WHERE slug = 'browser-use' AND pypi_package IS NULL")


def downgrade() -> None:
    # --- 1. Drop dependent views ---
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_project_summary CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_traction_score CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_velocity CASCADE")

    # --- 2. Recreate mv_velocity (047 definition, without development_pace) ---
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

    # --- 3. Recreate mv_traction_score (047 definition) ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_traction_score AS
WITH latest_gh AS (
    SELECT DISTINCT ON (project_id)
        project_id, stars, forks
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_dl AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
),
dep_counts AS (
    SELECT p.id AS project_id, COALESCE(a.dependency_count, 0) AS dependency_count
    FROM projects p
    LEFT JOIN ai_repos a ON a.id = p.ai_repo_id
),
raw_scores AS (
    SELECT
        p.id AS project_id,
        p.name,
        p.slug,
        LEAST(20, COALESCE(vel.fork_star_ratio, 0) * 100) AS fork_score,
        CASE
            WHEN COALESCE(gh.stars, 0) = 0 THEN 0
            ELSE LEAST(25, (COALESCE(dl.downloads_monthly, 0)::numeric / NULLIF(gh.stars, 0)) * 2.5)
        END AS adoption_score,
        CASE
            WHEN dc.dependency_count = 0 THEN 0
            ELSE LEAST(20, LN(dc.dependency_count + 1) * 5)
        END AS dependency_score,
        CASE
            WHEN COALESCE(vel.commits_30d, 0) = 0 THEN 0
            WHEN vel.commits_30d <= 10 THEN 5
            WHEN vel.commits_30d <= 50 THEN 10
            WHEN vel.commits_30d <= 200 THEN 15
            ELSE 20
        END AS velocity_score,
        CASE
            WHEN COALESCE(vel.contributors, 0) <= 1 THEN 0
            WHEN vel.contributors <= 5 THEN 5
            WHEN vel.contributors <= 20 THEN 10
            ELSE 15
        END AS contributor_score,
        COALESCE(vel.fork_star_ratio, 0) AS fork_star_ratio,
        COALESCE(dl.downloads_monthly, 0) AS monthly_downloads,
        COALESCE(gh.stars, 0) AS stars,
        dc.dependency_count,
        COALESCE(vel.contributors, 0) AS contributors,
        COALESCE(vel.commits_30d, 0) AS commits_30d,
        COALESCE(dt.dl_trend, 'stable') AS dl_trend
    FROM projects p
    LEFT JOIN latest_gh gh ON p.id = gh.project_id
    LEFT JOIN latest_dl dl ON p.id = dl.project_id
    LEFT JOIN mv_velocity vel ON p.id = vel.project_id
    LEFT JOIN dep_counts dc ON p.id = dc.project_id
    LEFT JOIN mv_download_trends dt ON p.id = dt.project_id
    WHERE p.is_active = true
)
SELECT
    project_id,
    name,
    slug,
    ROUND(fork_score + adoption_score + dependency_score + velocity_score + contributor_score)::int AS traction_score,
    fork_score,
    adoption_score,
    dependency_score,
    velocity_score,
    contributor_score,
    CASE
        WHEN fork_star_ratio > 0.15 AND dependency_count > 5 THEN 'infrastructure'
        WHEN contributors > 10 AND commits_30d > 20 THEN 'community-driven'
        WHEN stars > 1000 AND monthly_downloads < stars * 0.5 AND dependency_count < 3 THEN 'hype'
        WHEN monthly_downloads > stars * 5 AND stars < 5000 THEN 'stealth-adoption'
        WHEN contributors <= 1 AND commits_30d > 50 THEN 'company-driven'
        ELSE 'balanced'
    END AS traction_bucket,
    fork_star_ratio,
    monthly_downloads,
    stars,
    dependency_count,
    contributors,
    commits_30d,
    dl_trend
FROM raw_scores
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_traction_score_project_id ON mv_traction_score (project_id)")

    # --- 4. Recreate mv_project_summary (047 definition, without development_pace) ---
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
    p.domain,
    p.stack_layer,
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
    COALESCE(m.commits_30d_delta, 0) AS commits_30d_delta,
    COALESCE(m.contributors_30d_delta, 0) AS contributors_30d_delta,
    ts.traction_score,
    ts.traction_bucket,
    dt.dl_trend,
    dt.dl_weekly_velocity
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
LEFT JOIN mv_traction_score ts ON p.id = ts.project_id
LEFT JOIN mv_download_trends dt ON p.id = dt.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_project_summary_project_id ON mv_project_summary (project_id)")

    # --- 5. Revert browser-use fix ---
    op.execute("UPDATE projects SET pypi_package = NULL WHERE slug = 'browser-use' AND pypi_package = 'browser-use'")
