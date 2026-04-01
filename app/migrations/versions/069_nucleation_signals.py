"""Add nucleation signal infrastructure

Revision ID: 069
Revises: 068
Create Date: 2026-04-01

Surfaces patterns forming in the AI ecosystem that haven't been named yet.
Two materialized views:
  - mv_nucleation_project: per-repo cross-signal nucleation score
  - mv_nucleation_category: per-(domain, subcategory) creation velocity
One regular view:
  - v_nucleation_report: unified report joining both MVs

Also adds missing index on hn_posts.posted_at (benefits existing
mv_allocation_scores as well).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "069"
down_revision: Union[str, None] = "068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MV_PROJECT_SQL = """
CREATE MATERIALIZED VIEW mv_nucleation_project AS
WITH
-- Snapshot bounds (graceful degradation when < 7 days exist)
-- Falls back to earliest available snapshot when 7d baseline doesn't exist
snapshot_bounds AS (
    SELECT
        MAX(snapshot_date) AS latest,
        MAX(snapshot_date) - 7 AS target_7d,
        MIN(snapshot_date) AS earliest
    FROM ai_repo_snapshots
),
baseline_date AS (
    SELECT COALESCE(
        (SELECT MAX(snapshot_date) FROM ai_repo_snapshots
         WHERE snapshot_date <= (SELECT target_7d FROM snapshot_bounds)),
        (SELECT earliest FROM snapshot_bounds)
    ) AS d7
),

-- Star delta per repo (uses earliest snapshot as fallback baseline)
star_delta AS (
    SELECT
        s_now.repo_id,
        s_now.stars AS stars_now,
        s_now.stars - COALESCE(s_prev.stars, 0) AS star_delta_7d
    FROM ai_repo_snapshots s_now
    CROSS JOIN snapshot_bounds sb
    LEFT JOIN baseline_date bd ON TRUE
    LEFT JOIN ai_repo_snapshots s_prev
        ON s_prev.repo_id = s_now.repo_id
        AND s_prev.snapshot_date = bd.d7
    WHERE s_now.snapshot_date = sb.latest
      AND sb.latest <> bd.d7  -- need at least 2 different dates
),

-- Z-score within subcategory
star_zscore AS (
    SELECT
        sd.repo_id,
        sd.star_delta_7d,
        CASE
            WHEN STDDEV(sd.star_delta_7d)
                 OVER (PARTITION BY ar.domain, ar.subcategory) > 0
            THEN (sd.star_delta_7d
                  - AVG(sd.star_delta_7d)
                    OVER (PARTITION BY ar.domain, ar.subcategory))
                 / STDDEV(sd.star_delta_7d)
                   OVER (PARTITION BY ar.domain, ar.subcategory)
            ELSE 0
        END AS star_velocity_zscore
    FROM star_delta sd
    JOIN ai_repos ar ON ar.id = sd.repo_id
    WHERE ar.subcategory IS NOT NULL AND ar.subcategory <> ''
),

-- HN signal per repo (last 7 days)
hn_signal AS (
    SELECT
        ar.id AS repo_id,
        COUNT(DISTINCT hp.id) AS hn_posts_7d,
        COALESCE(SUM(hp.points), 0) AS hn_points_7d
    FROM ai_repos ar
    JOIN projects p ON p.ai_repo_id = ar.id
    JOIN hn_posts hp ON hp.project_id = p.id
    WHERE hp.posted_at >= NOW() - INTERVAL '7 days'
    GROUP BY ar.id
),

-- Newsletter signal per repo (last 7 days)
newsletter_signal AS (
    SELECT
        ar.id AS repo_id,
        COUNT(*) AS newsletter_mentions_7d,
        COUNT(DISTINCT nm.feed_slug) AS newsletter_feeds_7d
    FROM newsletter_mentions nm,
         jsonb_array_elements(nm.mentions) AS m
    JOIN projects p ON p.id = (m->>'project_id')::int
    JOIN ai_repos ar ON p.ai_repo_id = ar.id
    WHERE nm.published_at >= NOW() - INTERVAL '7 days'
      AND m->>'project_id' IS NOT NULL
    GROUP BY ar.id
),

-- Release activity per repo (last 7 days)
release_signal AS (
    SELECT
        ar.id AS repo_id,
        COUNT(*) AS releases_7d
    FROM releases r
    JOIN projects p ON r.project_id = p.id
    JOIN ai_repos ar ON p.ai_repo_id = ar.id
    WHERE r.released_at >= NOW() - INTERVAL '7 days'
    GROUP BY ar.id
),

-- Assemble all signals per repo
assembled AS (
    SELECT
        ar.id,
        ar.full_name,
        ar.name,
        ar.domain,
        ar.subcategory,
        ar.stars,
        ar.commits_30d,
        COALESCE(sz.star_delta_7d, 0) AS star_delta_7d,
        COALESCE(sz.star_velocity_zscore, 0) AS star_velocity_zscore,
        COALESCE(hs.hn_posts_7d, 0) AS hn_posts_7d,
        COALESCE(hs.hn_points_7d, 0) AS hn_points_7d,
        COALESCE(ns.newsletter_mentions_7d, 0) AS newsletter_mentions_7d,
        COALESCE(ns.newsletter_feeds_7d, 0) AS newsletter_feeds_7d,
        COALESCE(rs.releases_7d, 0) AS releases_7d
    FROM ai_repos ar
    LEFT JOIN star_zscore sz ON sz.repo_id = ar.id
    LEFT JOIN hn_signal hs ON hs.repo_id = ar.id
    LEFT JOIN newsletter_signal ns ON ns.repo_id = ar.id
    LEFT JOIN release_signal rs ON rs.repo_id = ar.id
    WHERE ar.domain <> 'uncategorized'
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
      AND (
          COALESCE(sz.star_delta_7d, 0) > 0
          OR COALESCE(hs.hn_posts_7d, 0) > 0
          OR COALESCE(ns.newsletter_mentions_7d, 0) > 0
          OR COALESCE(rs.releases_7d, 0) > 0
          OR COALESCE(ar.commits_30d, 0) > 0
      )
),

-- Score using PERCENT_RANK per component
scored AS (
    SELECT *,
        LEAST(100, ROUND(
            35 * PERCENT_RANK() OVER (ORDER BY star_velocity_zscore)
          + 20 * PERCENT_RANK() OVER (ORDER BY hn_points_7d)
          + 15 * PERCENT_RANK() OVER (ORDER BY newsletter_feeds_7d)
          + 15 * PERCENT_RANK() OVER (ORDER BY releases_7d)
          + 15 * PERCENT_RANK() OVER (ORDER BY COALESCE(commits_30d, 0))
        ))::int AS nucleation_score
    FROM assembled
)

SELECT
    id, full_name, name, domain, subcategory, stars, commits_30d,
    star_delta_7d, star_velocity_zscore,
    hn_posts_7d, hn_points_7d,
    newsletter_mentions_7d, newsletter_feeds_7d,
    releases_7d,
    nucleation_score,
    -- narrative_gap: unusual GitHub signal with zero media coverage
    CASE
        WHEN star_velocity_zscore >= 1.5
             AND hn_posts_7d = 0
             AND newsletter_mentions_7d = 0
        THEN TRUE
        ELSE FALSE
    END AS narrative_gap
FROM scored
"""

_MV_CATEGORY_SQL = """
CREATE MATERIALIZED VIEW mv_nucleation_category AS
WITH
-- New repos discovered in trailing windows
new_7d AS (
    SELECT domain, subcategory,
           COUNT(*) AS new_repos_7d,
           COALESCE(SUM(stars), 0) AS new_repo_stars_7d
    FROM ai_repos
    WHERE discovered_at >= NOW() - INTERVAL '7 days'
      AND subcategory IS NOT NULL AND subcategory <> ''
    GROUP BY domain, subcategory
),
new_14d AS (
    SELECT domain, subcategory,
           COUNT(*) AS new_repos_14d
    FROM ai_repos
    WHERE discovered_at >= NOW() - INTERVAL '14 days'
      AND subcategory IS NOT NULL AND subcategory <> ''
    GROUP BY domain, subcategory
),

-- HN coverage per subcategory (7d)
hn_cat AS (
    SELECT ar.domain, ar.subcategory,
           COUNT(DISTINCT hp.id) AS hn_posts_7d,
           COALESCE(SUM(hp.points), 0) AS hn_points_7d
    FROM hn_posts hp
    JOIN projects p ON hp.project_id = p.id
    JOIN ai_repos ar ON p.ai_repo_id = ar.id
    WHERE hp.posted_at >= NOW() - INTERVAL '7 days'
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),

-- Newsletter coverage per subcategory (7d)
nl_cat AS (
    SELECT ar.domain, ar.subcategory,
           COUNT(*) AS newsletter_mentions_7d
    FROM newsletter_mentions nm,
         jsonb_array_elements(nm.mentions) AS m
    JOIN projects p ON p.id = (m->>'project_id')::int
    JOIN ai_repos ar ON p.ai_repo_id = ar.id
    WHERE nm.published_at >= NOW() - INTERVAL '7 days'
      AND m->>'project_id' IS NOT NULL
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),

assembled AS (
    SELECT
        COALESCE(n7.domain, n14.domain) AS domain,
        COALESCE(n7.subcategory, n14.subcategory) AS subcategory,
        COALESCE(n7.new_repos_7d, 0) AS new_repos_7d,
        COALESCE(n14.new_repos_14d, 0) AS new_repos_14d,
        COALESCE(n7.new_repo_stars_7d, 0) AS new_repo_stars_7d,
        -- Acceleration: is the 7d rate faster than the prior 7d?
        CASE
            WHEN COALESCE(n14.new_repos_14d, 0) - COALESCE(n7.new_repos_7d, 0) > 0
            THEN COALESCE(n7.new_repos_7d, 0)::numeric
                 / (COALESCE(n14.new_repos_14d, 0) - COALESCE(n7.new_repos_7d, 0))
            ELSE NULL
        END AS acceleration,
        COALESCE(hc.hn_posts_7d, 0) + COALESCE(hc.hn_points_7d, 0) AS hn_coverage_7d,
        COALESCE(nc.newsletter_mentions_7d, 0) AS newsletter_coverage_7d
    FROM new_7d n7
    FULL OUTER JOIN new_14d n14
        ON n7.domain = n14.domain AND n7.subcategory = n14.subcategory
    LEFT JOIN hn_cat hc
        ON COALESCE(n7.domain, n14.domain) = hc.domain
        AND COALESCE(n7.subcategory, n14.subcategory) = hc.subcategory
    LEFT JOIN nl_cat nc
        ON COALESCE(n7.domain, n14.domain) = nc.domain
        AND COALESCE(n7.subcategory, n14.subcategory) = nc.subcategory
    WHERE COALESCE(n7.new_repos_7d, 0) + COALESCE(n14.new_repos_14d, 0) > 0
)

SELECT
    domain, subcategory,
    new_repos_7d, new_repos_14d, new_repo_stars_7d,
    acceleration,
    hn_coverage_7d, newsletter_coverage_7d,
    -- creation_without_buzz: builders active, media silent
    CASE
        WHEN new_repos_7d >= 3
             AND hn_coverage_7d = 0
             AND newsletter_coverage_7d = 0
        THEN TRUE
        ELSE FALSE
    END AS creation_without_buzz
FROM assembled
"""

_VIEW_REPORT_SQL = """
CREATE OR REPLACE VIEW v_nucleation_report AS

-- Section 1: Top projects by nucleation score
SELECT
    'project'::text AS section,
    np.name AS label,
    np.full_name AS detail,
    np.domain,
    np.subcategory,
    np.nucleation_score AS score,
    np.narrative_gap AS gap_flag,
    np.star_delta_7d,
    np.star_velocity_zscore,
    np.hn_posts_7d,
    np.hn_points_7d,
    np.newsletter_mentions_7d,
    np.newsletter_feeds_7d,
    np.releases_7d,
    np.stars,
    NULL::int AS new_repos_7d,
    NULL::numeric AS acceleration
FROM mv_nucleation_project np
WHERE np.nucleation_score >= 30

UNION ALL

-- Section 2: Top categories by creation velocity
SELECT
    'category'::text AS section,
    nc.subcategory AS label,
    nc.domain AS detail,
    nc.domain,
    nc.subcategory,
    LEAST(100, COALESCE(
        nc.new_repos_7d * COALESCE(nc.acceleration, 1), 0
    ))::int AS score,
    nc.creation_without_buzz AS gap_flag,
    NULL::int AS star_delta_7d,
    NULL::numeric AS star_velocity_zscore,
    NULL::int AS hn_posts_7d,
    NULL::int AS hn_points_7d,
    NULL::int AS newsletter_mentions_7d,
    NULL::int AS newsletter_feeds_7d,
    NULL::int AS releases_7d,
    NULL::int AS stars,
    nc.new_repos_7d,
    nc.acceleration
FROM mv_nucleation_category nc
WHERE nc.new_repos_7d >= 1
"""


def upgrade() -> None:
    # 1. Add missing index on hn_posts.posted_at
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_hn_posts_posted_at "
        "ON hn_posts (posted_at)"
    )

    # 2. Create project-level nucleation MV
    op.execute(_MV_PROJECT_SQL)
    op.execute(
        "CREATE UNIQUE INDEX idx_mv_nucleation_project_id "
        "ON mv_nucleation_project (id)"
    )

    # 3. Create category-level nucleation MV
    op.execute(_MV_CATEGORY_SQL)
    op.execute(
        "CREATE UNIQUE INDEX idx_mv_nucleation_cat_uniq "
        "ON mv_nucleation_category (domain, COALESCE(subcategory, ''))"
    )

    # 4. Create unified report view
    op.execute(_VIEW_REPORT_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_nucleation_report CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_nucleation_category CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_nucleation_project CASCADE")
    op.execute("DROP INDEX IF EXISTS ix_hn_posts_posted_at")
