"""Replace opportunity scoring with allocation engine

Revision ID: 065
Revises: 064
Create Date: 2026-03-30

Replaces mv_category_opportunity (ad-hoc whitespace heuristics) with
mv_allocation_scores: a dual-score model grounded in demand signals
(GSC + Umami) and leading velocity signals (GitHub trends).

Two scores per (domain, subcategory):
  - Established Heat Score (EHS): GSC impressions/clicks + Umami pageviews
  - Emergence Score (ES): GitHub star velocity + new repos + fork accel

Also creates:
  - umami_page_stats: staging table for Umami ETL
  - allocation_score_snapshots: daily tracking (replaces opportunity_snapshots)
  - v_deep_dive_queue: ranked editorial priority view
"""
from typing import Sequence, Union

from alembic import op

revision: str = "065"
down_revision: Union[str, None] = "064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MV_SQL = """
CREATE MATERIALIZED VIEW mv_allocation_scores AS
WITH
-- Base: one row per (domain, subcategory), min 2 repos
cats AS (
    SELECT
        domain,
        subcategory,
        COUNT(*) AS repo_count,
        COALESCE(SUM(stars), 0) AS total_stars,
        COALESCE(SUM(forks), 0) AS total_forks
    FROM ai_repos
    WHERE domain <> 'uncategorized'
      AND subcategory IS NOT NULL
      AND subcategory <> ''
    GROUP BY domain, subcategory
    HAVING COUNT(*) >= 2
),

-- Snapshot range
snapshot_range AS (
    SELECT
        MAX(snapshot_date) AS latest_date,
        MAX(snapshot_date) - 7 AS d7_cutoff
    FROM ai_repo_snapshots
),

-- GitHub velocity: 7d star delta and fork delta per category
cat_snap_latest AS (
    SELECT ar.domain, ar.subcategory,
        SUM(s.stars) AS total_stars,
        SUM(s.forks) AS total_forks
    FROM ai_repos ar
    JOIN ai_repo_snapshots s ON s.repo_id = ar.id
    CROSS JOIN snapshot_range sr
    WHERE s.snapshot_date = sr.latest_date
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),
cat_snap_7d AS (
    SELECT ar.domain, ar.subcategory,
        SUM(s.stars) AS total_stars,
        SUM(s.forks) AS total_forks
    FROM ai_repos ar
    JOIN ai_repo_snapshots s ON s.repo_id = ar.id
    WHERE s.snapshot_date = (
        SELECT MAX(snapshot_date) FROM ai_repo_snapshots
        WHERE snapshot_date <= (SELECT d7_cutoff FROM snapshot_range)
    )
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),
github_velocity AS (
    SELECT
        l.domain, l.subcategory,
        COALESCE(l.total_stars - s7.total_stars, 0) AS star_velocity_7d,
        COALESCE(l.total_forks - s7.total_forks, 0) AS fork_acceleration_7d
    FROM cat_snap_latest l
    LEFT JOIN cat_snap_7d s7 ON l.domain = s7.domain AND l.subcategory = s7.subcategory
),

-- New repos in last 7 days per category
new_repos AS (
    SELECT domain, subcategory, COUNT(*) AS new_repos_7d
    FROM ai_repos
    WHERE discovered_at >= NOW() - INTERVAL '7 days'
      AND subcategory IS NOT NULL AND subcategory <> ''
    GROUP BY domain, subcategory
),

-- GSC: 7d growth rates per category (maps page URLs to domain/subcategory)
gsc_current AS (
    SELECT
        CASE
            WHEN page LIKE '%/agents/categories/%' THEN 'agents'
            WHEN page LIKE '%/rag/categories/%' THEN 'rag'
            WHEN page LIKE '%/ai-coding/categories/%' THEN 'ai-coding'
            WHEN page LIKE '%/voice-ai/categories/%' THEN 'voice-ai'
            WHEN page LIKE '%/diffusion/categories/%' THEN 'diffusion'
            WHEN page LIKE '%/vector-db/categories/%' THEN 'vector-db'
            WHEN page LIKE '%/embeddings/categories/%' THEN 'embeddings'
            WHEN page LIKE '%/prompt-engineering/categories/%' THEN 'prompt-engineering'
            WHEN page LIKE '%/ml-frameworks/categories/%' THEN 'ml-frameworks'
            WHEN page LIKE '%/llm-tools/categories/%' THEN 'llm-tools'
            WHEN page LIKE '%/nlp/categories/%' THEN 'nlp'
            WHEN page LIKE '%/transformers/categories/%' THEN 'transformers'
            WHEN page LIKE '%/generative-ai/categories/%' THEN 'generative-ai'
            WHEN page LIKE '%/computer-vision/categories/%' THEN 'computer-vision'
            WHEN page LIKE '%/data-engineering/categories/%' THEN 'data-engineering'
            WHEN page LIKE '%/mlops/categories/%' THEN 'mlops'
            WHEN page LIKE '%/categories/%' THEN 'mcp'
            ELSE NULL
        END AS domain,
        REGEXP_REPLACE(
            REGEXP_REPLACE(page, '.*/categories/([^/]+)/?$', '\\1'),
            '^https://.*$', NULL
        ) AS subcategory,
        SUM(impressions) AS impressions,
        SUM(clicks) AS clicks,
        AVG(position) AS avg_position
    FROM gsc_search_data
    WHERE search_date >= CURRENT_DATE - 7
    GROUP BY 1, 2
    HAVING REGEXP_REPLACE(
        REGEXP_REPLACE(page, '.*/categories/([^/]+)/?$', '\\1'),
        '^https://.*$', NULL
    ) IS NOT NULL
),
gsc_previous AS (
    SELECT
        CASE
            WHEN page LIKE '%/agents/categories/%' THEN 'agents'
            WHEN page LIKE '%/rag/categories/%' THEN 'rag'
            WHEN page LIKE '%/ai-coding/categories/%' THEN 'ai-coding'
            WHEN page LIKE '%/voice-ai/categories/%' THEN 'voice-ai'
            WHEN page LIKE '%/diffusion/categories/%' THEN 'diffusion'
            WHEN page LIKE '%/vector-db/categories/%' THEN 'vector-db'
            WHEN page LIKE '%/embeddings/categories/%' THEN 'embeddings'
            WHEN page LIKE '%/prompt-engineering/categories/%' THEN 'prompt-engineering'
            WHEN page LIKE '%/ml-frameworks/categories/%' THEN 'ml-frameworks'
            WHEN page LIKE '%/llm-tools/categories/%' THEN 'llm-tools'
            WHEN page LIKE '%/nlp/categories/%' THEN 'nlp'
            WHEN page LIKE '%/transformers/categories/%' THEN 'transformers'
            WHEN page LIKE '%/generative-ai/categories/%' THEN 'generative-ai'
            WHEN page LIKE '%/computer-vision/categories/%' THEN 'computer-vision'
            WHEN page LIKE '%/data-engineering/categories/%' THEN 'data-engineering'
            WHEN page LIKE '%/mlops/categories/%' THEN 'mlops'
            WHEN page LIKE '%/categories/%' THEN 'mcp'
            ELSE NULL
        END AS domain,
        REGEXP_REPLACE(
            REGEXP_REPLACE(page, '.*/categories/([^/]+)/?$', '\\1'),
            '^https://.*$', NULL
        ) AS subcategory,
        SUM(impressions) AS impressions,
        SUM(clicks) AS clicks,
        AVG(position) AS avg_position
    FROM gsc_search_data
    WHERE search_date BETWEEN CURRENT_DATE - 14 AND CURRENT_DATE - 8
    GROUP BY 1, 2
    HAVING REGEXP_REPLACE(
        REGEXP_REPLACE(page, '.*/categories/([^/]+)/?$', '\\1'),
        '^https://.*$', NULL
    ) IS NOT NULL
),
gsc_stats AS (
    SELECT
        COALESCE(gc.domain, gp.domain) AS domain,
        COALESCE(gc.subcategory, gp.subcategory) AS subcategory,
        COALESCE(gc.impressions, 0) AS gsc_impressions_7d,
        COALESCE(gc.clicks, 0) AS gsc_clicks_7d,
        gc.avg_position AS gsc_avg_position,
        CASE WHEN COALESCE(gp.impressions, 0) > 0
            THEN (COALESCE(gc.impressions, 0) - gp.impressions)::numeric / gp.impressions
            ELSE NULL
        END AS gsc_impression_growth_7d,
        CASE WHEN COALESCE(gp.clicks, 0) > 0
            THEN (COALESCE(gc.clicks, 0) - gp.clicks)::numeric / gp.clicks
            ELSE NULL
        END AS gsc_click_growth_7d,
        CASE WHEN gp.avg_position IS NOT NULL AND gc.avg_position IS NOT NULL
            THEN gp.avg_position - gc.avg_position  -- positive = improved (lower position is better)
            ELSE NULL
        END AS gsc_position_improvement
    FROM gsc_current gc
    FULL OUTER JOIN gsc_previous gp
        ON gc.domain = gp.domain AND gc.subcategory = gp.subcategory
    WHERE COALESCE(gc.domain, gp.domain) IS NOT NULL
),

-- Umami: 7d pageviews per category (from ETL staging table)
umami_stats AS (
    SELECT
        domain,
        subcategory,
        SUM(pageviews) AS umami_pageviews_7d,
        AVG(unique_sessions) AS umami_avg_sessions
    FROM umami_page_stats
    WHERE stat_date >= CURRENT_DATE - 7
      AND subcategory IS NOT NULL
    GROUP BY domain, subcategory
),

-- Assemble and normalize via PERCENT_RANK
assembled AS (
    SELECT
        c.domain,
        c.subcategory,
        c.repo_count,
        c.total_stars,

        -- Raw component values
        COALESCE(gs.gsc_impression_growth_7d, 0) AS gsc_impression_growth_7d,
        COALESCE(gs.gsc_click_growth_7d, 0) AS gsc_click_growth_7d,
        COALESCE(gs.gsc_position_improvement, 0) AS gsc_position_improvement,
        COALESCE(gs.gsc_impressions_7d, 0) AS gsc_impressions_7d,
        COALESCE(gs.gsc_clicks_7d, 0) AS gsc_clicks_7d,
        gs.gsc_avg_position,
        COALESCE(um.umami_pageviews_7d, 0) AS umami_pageviews_7d,
        COALESCE(um.umami_avg_sessions, 0) AS umami_avg_sessions,
        COALESCE(gv.star_velocity_7d, 0) AS github_star_velocity_7d,
        COALESCE(nr.new_repos_7d, 0) AS github_new_repos_7d,
        COALESCE(gv.fork_acceleration_7d, 0) AS github_fork_acceleration_7d,
        -- GSC coverage: does this category have any GSC data?
        CASE WHEN COALESCE(gs.gsc_impressions_7d, 0) > 0 THEN 1.0 ELSE 0.0 END AS gsc_coverage_ratio

    FROM cats c
    LEFT JOIN github_velocity gv ON c.domain = gv.domain AND c.subcategory = gv.subcategory
    LEFT JOIN new_repos nr ON c.domain = nr.domain AND c.subcategory = nr.subcategory
    LEFT JOIN gsc_stats gs ON c.domain = gs.domain AND c.subcategory = gs.subcategory
    LEFT JOIN umami_stats um ON c.domain = um.domain AND c.subcategory = um.subcategory
),

-- EHS: Established Heat Score (0-100)
-- Weighted: GSC impression growth 25%, click growth 25%, position improvement 15%,
--           Umami pageviews 20%, Umami sessions 15%
ehs_scored AS (
    SELECT *,
        LEAST(100, ROUND(
            25 * PERCENT_RANK() OVER (ORDER BY gsc_impression_growth_7d)
          + 25 * PERCENT_RANK() OVER (ORDER BY gsc_click_growth_7d)
          + 15 * PERCENT_RANK() OVER (ORDER BY gsc_position_improvement)
          + 20 * PERCENT_RANK() OVER (ORDER BY umami_pageviews_7d)
          + 15 * PERCENT_RANK() OVER (ORDER BY umami_avg_sessions)
        ))::int AS ehs
    FROM assembled
),

-- ES: Emergence Score (0-100)
-- Weighted: star velocity 30%, new repos 25%, fork accel 15%,
--           absence of GSC coverage 30%
scored AS (
    SELECT *,
        LEAST(100, ROUND(
            30 * PERCENT_RANK() OVER (ORDER BY github_star_velocity_7d)
          + 25 * PERCENT_RANK() OVER (ORDER BY github_new_repos_7d)
          + 15 * PERCENT_RANK() OVER (ORDER BY github_fork_acceleration_7d)
          + 30 * (1 - gsc_coverage_ratio)
        ))::int AS es
    FROM ehs_scored
)

SELECT
    domain, subcategory, repo_count, total_stars,
    -- Established Heat Score
    ehs,
    gsc_impression_growth_7d, gsc_click_growth_7d, gsc_position_improvement,
    gsc_impressions_7d, gsc_clicks_7d, gsc_avg_position,
    umami_pageviews_7d, umami_avg_sessions,
    -- Emergence Score
    es,
    github_star_velocity_7d, github_new_repos_7d, github_fork_acceleration_7d,
    gsc_coverage_ratio,
    -- Confidence level
    CASE
        WHEN gsc_impressions_7d > 0 AND umami_pageviews_7d > 0 THEN 'full'
        WHEN gsc_impressions_7d > 0 THEN 'gsc-only'
        WHEN umami_pageviews_7d > 0 THEN 'umami-only'
        ELSE 'github-only'
    END AS confidence_level,
    -- Backward-compatible columns for existing deep dive templates
    GREATEST(ehs, es) AS opportunity_score,
    CASE
        WHEN GREATEST(ehs, es) >= 80 THEN 'prime'
        WHEN GREATEST(ehs, es) >= 60 THEN 'promising'
        WHEN GREATEST(ehs, es) >= 40 THEN 'growing'
        WHEN GREATEST(ehs, es) >= 20 THEN 'competitive'
        ELSE 'saturated'
    END AS opportunity_tier
FROM scored
"""


def upgrade() -> None:
    # 1. Create umami_page_stats staging table
    op.execute("""
        CREATE TABLE IF NOT EXISTS umami_page_stats (
            id SERIAL PRIMARY KEY,
            domain VARCHAR(50) NOT NULL,
            subcategory VARCHAR(100),
            stat_date DATE NOT NULL DEFAULT CURRENT_DATE,
            pageviews INT NOT NULL DEFAULT 0,
            unique_sessions INT NOT NULL DEFAULT 0
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_umami_stats_uniq "
        "ON umami_page_stats (domain, COALESCE(subcategory, ''), stat_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_umami_stats_date "
        "ON umami_page_stats (stat_date)"
    )

    # 2. Create allocation_score_snapshots table
    op.execute("""
        CREATE TABLE IF NOT EXISTS allocation_score_snapshots (
            id SERIAL PRIMARY KEY,
            domain VARCHAR(50) NOT NULL,
            subcategory VARCHAR(100) NOT NULL,
            snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
            ehs INT,
            es INT,
            gsc_impression_growth_7d NUMERIC(8,2),
            gsc_click_growth_7d NUMERIC(8,2),
            gsc_position_improvement NUMERIC(6,2),
            umami_pageviews_7d INT,
            umami_avg_sessions NUMERIC(5,2),
            github_star_velocity_7d INT,
            github_new_repos_7d INT,
            github_fork_acceleration_7d INT,
            gsc_coverage_ratio NUMERIC(5,4),
            repo_count INT,
            total_stars BIGINT,
            confidence_level VARCHAR(20),
            UNIQUE (domain, subcategory, snapshot_date)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_alloc_snap_date "
        "ON allocation_score_snapshots (snapshot_date)"
    )

    # 3. Drop old opportunity MV (keep opportunity_snapshots as archive)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_category_opportunity CASCADE")

    # 4. Create new allocation scores MV
    op.execute(_MV_SQL)
    op.execute(
        "CREATE UNIQUE INDEX idx_mv_alloc_scores_uniq "
        "ON mv_allocation_scores (domain, COALESCE(subcategory, ''))"
    )

    # 5. Create deep dive priority queue view
    op.execute("""
        CREATE OR REPLACE VIEW v_deep_dive_queue AS
        SELECT
            a.domain,
            a.subcategory,
            a.ehs,
            a.es,
            GREATEST(a.ehs, a.es) AS combined_score,
            a.repo_count,
            a.total_stars,
            a.confidence_level,
            a.gsc_impressions_7d,
            a.gsc_clicks_7d,
            a.github_star_velocity_7d,
            a.github_new_repos_7d,
            a.umami_pageviews_7d,
            CASE
                WHEN a.ehs >= a.es AND a.ehs >= 50 THEN 'established_heat'
                WHEN a.es >= 50 THEN 'emerging_signal'
                ELSE 'below_threshold'
            END AS queue
        FROM mv_allocation_scores a
        WHERE GREATEST(a.ehs, a.es) > 20
        ORDER BY GREATEST(a.ehs, a.es) DESC
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_deep_dive_queue CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_allocation_scores CASCADE")
    op.execute("DROP TABLE IF EXISTS allocation_score_snapshots CASCADE")
    op.execute("DROP TABLE IF EXISTS umami_page_stats CASCADE")
    # Note: does NOT recreate mv_category_opportunity — run 062 upgrade for that
