"""Add category opportunity scoring

Revision ID: 062
Revises: 061
Create Date: 2026-03-30

Creates mv_category_opportunity materialized view scoring each
(domain, subcategory) on whitespace opportunity (0-100).
Sub-scores: demand, quality_gap, concentration (HHI), graveyard,
momentum, stadium. Weights shift as snapshot data accumulates.

Also creates opportunity_snapshots table for daily tracking.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "062"
down_revision: Union[str, None] = "061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All domain quality views for the UNION ALL
_QUALITY_VIEWS = [
    ("mv_mcp_quality", "mcp"),
    ("mv_agents_quality", "agents"),
    ("mv_rag_quality", "rag"),
    ("mv_ai_coding_quality", "ai-coding"),
    ("mv_voice_ai_quality", "voice-ai"),
    ("mv_diffusion_quality", "diffusion"),
    ("mv_vector_db_quality", "vector-db"),
    ("mv_embeddings_quality", "embeddings"),
    ("mv_prompt_eng_quality", "prompt-engineering"),
    ("mv_ml_frameworks_quality", "ml-frameworks"),
    ("mv_llm_tools_quality", "llm-tools"),
    ("mv_nlp_quality", "nlp"),
    ("mv_transformers_quality", "transformers"),
    ("mv_generative_ai_quality", "generative-ai"),
    ("mv_computer_vision_quality", "computer-vision"),
    ("mv_data_engineering_quality", "data-engineering"),
    ("mv_mlops_quality", "mlops"),
]


def _quality_union_sql():
    """Build UNION ALL across all domain quality views."""
    parts = []
    for view, domain in _QUALITY_VIEWS:
        parts.append(
            f"SELECT id, '{domain}' AS domain, subcategory, quality_score, "
            f"stars, downloads_monthly, commits_30d FROM {view}"
        )
    return " UNION ALL ".join(parts)


_MV_SQL = f"""
CREATE MATERIALIZED VIEW mv_category_opportunity AS
WITH
-- Base: one row per (domain, subcategory), min 2 repos
cats AS (
    SELECT
        domain,
        subcategory,
        COUNT(*) AS repo_count,
        COALESCE(SUM(stars), 0) AS total_stars,
        COALESCE(SUM(downloads_monthly), 0) AS total_downloads,
        COALESCE(SUM(forks), 0) AS total_forks,
        AVG(COALESCE(commits_30d, 0)) AS avg_commits_30d
    FROM ai_repos
    WHERE domain <> 'uncategorized'
      AND subcategory IS NOT NULL
      AND subcategory <> ''
    GROUP BY domain, subcategory
    HAVING COUNT(*) >= 2
),

-- Quality scores from all domain views
quality_union AS (
    {_quality_union_sql()}
),

-- Sub-score A: Demand (log-scale stars + downloads, percentile ranked)
demand_raw AS (
    SELECT domain, subcategory,
        LN(1 + total_stars) + LN(1 + total_downloads) AS raw_demand
    FROM cats
),
demand_ranked AS (
    SELECT domain, subcategory,
        ROUND(PERCENT_RANK() OVER (ORDER BY raw_demand) * 100)::int AS demand_score
    FROM demand_raw
),

-- Sub-score B: Quality gap (high demand / low quality = underserved)
quality_gap_raw AS (
    SELECT
        q.domain, q.subcategory,
        AVG(q.quality_score) AS avg_quality,
        CASE WHEN AVG(q.quality_score) > 0
            THEN LN(1 + COALESCE(SUM(q.stars), 0) + COALESCE(SUM(q.downloads_monthly), 0))
                 / (AVG(q.quality_score) / 100.0)
            ELSE 0
        END AS raw_gap
    FROM quality_union q
    WHERE q.subcategory IS NOT NULL AND q.subcategory <> ''
    GROUP BY q.domain, q.subcategory
),
quality_gap_ranked AS (
    SELECT domain, subcategory, avg_quality,
        ROUND(PERCENT_RANK() OVER (ORDER BY raw_gap) * 100)::int AS quality_gap_score
    FROM quality_gap_raw
),

-- Sub-score C: Concentration (HHI on stars)
hhi_calc AS (
    SELECT
        ar.domain, ar.subcategory,
        SUM(POWER(ar.stars::numeric / NULLIF(c.total_stars, 0), 2)) AS hhi
    FROM ai_repos ar
    JOIN cats c ON ar.domain = c.domain AND ar.subcategory = c.subcategory
    WHERE ar.stars > 0
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),
-- HHI × leader staleness = concentration opportunity
concentration_calc AS (
    SELECT
        h.domain, h.subcategory, h.hhi,
        -- Multiply by staleness factor: if avg commits < 5, category leaders may be stale
        ROUND(PERCENT_RANK() OVER (
            ORDER BY h.hhi * CASE WHEN c.avg_commits_30d < 5 THEN 1.5 ELSE 1.0 END
        ) * 100)::int AS concentration_score
    FROM hhi_calc h
    JOIN cats c ON h.domain = c.domain AND h.subcategory = c.subcategory
),

-- Sub-score D: Graveyard (abandoned high-star repos = proven demand, failed execution)
graveyard_calc AS (
    SELECT
        domain, subcategory,
        COUNT(*) FILTER (
            WHERE stars >= 1000
            AND (last_pushed_at < NOW() - INTERVAL '180 days' OR last_pushed_at IS NULL)
        ) AS graveyard_count,
        COALESCE(SUM(stars) FILTER (
            WHERE stars >= 1000
            AND (last_pushed_at < NOW() - INTERVAL '180 days' OR last_pushed_at IS NULL)
        ), 0) AS graveyard_star_total
    FROM ai_repos
    WHERE subcategory IS NOT NULL AND subcategory <> ''
    GROUP BY domain, subcategory
),
graveyard_ranked AS (
    SELECT domain, subcategory, graveyard_count, graveyard_star_total,
        CASE WHEN graveyard_count > 0
            THEN LEAST(100, ROUND(LN(1 + graveyard_star_total) * 8))::int
            ELSE 0
        END AS graveyard_score
    FROM graveyard_calc
),

-- Snapshot range for temporal signals
snapshot_range AS (
    SELECT
        MIN(snapshot_date) AS earliest_date,
        MAX(snapshot_date) AS latest_date,
        MAX(snapshot_date) - MIN(snapshot_date) AS days_span
    FROM ai_repo_snapshots
),

-- Category-level snapshot aggregates (latest and earliest dates)
cat_snap_latest AS (
    SELECT ar.domain, ar.subcategory,
        SUM(s.stars) AS total_stars,
        SUM(COALESCE(s.commits_30d, 0)) AS total_commits
    FROM ai_repos ar
    JOIN ai_repo_snapshots s ON s.repo_id = ar.id
    CROSS JOIN snapshot_range sr
    WHERE s.snapshot_date = sr.latest_date
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),
cat_snap_earliest AS (
    SELECT ar.domain, ar.subcategory,
        SUM(s.stars) AS total_stars,
        SUM(COALESCE(s.commits_30d, 0)) AS total_commits
    FROM ai_repos ar
    JOIN ai_repo_snapshots s ON s.repo_id = ar.id
    CROSS JOIN snapshot_range sr
    WHERE s.snapshot_date = sr.earliest_date
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),
-- 7d-ago category aggregates
cat_snap_7d AS (
    SELECT ar.domain, ar.subcategory,
        SUM(s.stars) AS total_stars
    FROM ai_repos ar
    JOIN ai_repo_snapshots s ON s.repo_id = ar.id
    CROSS JOIN snapshot_range sr
    WHERE sr.days_span >= 7
      AND s.snapshot_date = (
          SELECT MAX(snapshot_date) FROM ai_repo_snapshots
          WHERE snapshot_date <= sr.latest_date - 7
      )
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),
-- 30d-ago category aggregates
cat_snap_30d AS (
    SELECT ar.domain, ar.subcategory,
        SUM(s.stars) AS total_stars
    FROM ai_repos ar
    JOIN ai_repo_snapshots s ON s.repo_id = ar.id
    CROSS JOIN snapshot_range sr
    WHERE sr.days_span >= 30
      AND s.snapshot_date = (
          SELECT MAX(snapshot_date) FROM ai_repo_snapshots
          WHERE snapshot_date <= sr.latest_date - 30
      )
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),

-- Sub-score E: Momentum (category-level star velocity)
momentum_calc AS (
    SELECT
        l.domain, l.subcategory,
        CASE WHEN sr.days_span >= 7
            THEN l.total_stars - COALESCE(s7.total_stars, 0)
            ELSE NULL END AS stars_7d_delta,
        CASE WHEN sr.days_span >= 30
            THEN l.total_stars - COALESCE(s30.total_stars, 0)
            ELSE NULL END AS stars_30d_delta
    FROM cat_snap_latest l
    CROSS JOIN snapshot_range sr
    LEFT JOIN cat_snap_7d s7 ON l.domain = s7.domain AND l.subcategory = s7.subcategory
    LEFT JOIN cat_snap_30d s30 ON l.domain = s30.domain AND l.subcategory = s30.subcategory
),

-- Sub-score F: Stadium (star growth >> contributor growth)
stadium_calc AS (
    SELECT
        l.domain, l.subcategory,
        l.total_stars - COALESCE(e.total_stars, 0) AS star_delta,
        l.total_commits - COALESCE(e.total_commits, 0) AS commit_delta,
        CASE
            WHEN (l.total_stars - COALESCE(e.total_stars, 0)) > 0
             AND GREATEST(1, l.total_commits - COALESCE(e.total_commits, 0)) > 0
            THEN (l.total_stars - COALESCE(e.total_stars, 0))::numeric
                 / GREATEST(1, l.total_commits - COALESCE(e.total_commits, 0))
            ELSE NULL
        END AS stadium_ratio
    FROM cat_snap_latest l
    LEFT JOIN cat_snap_earliest e ON l.domain = e.domain AND l.subcategory = e.subcategory
),

-- Assemble all sub-scores
assembled AS (
    SELECT
        c.domain,
        c.subcategory,
        c.repo_count,
        c.total_stars,
        c.total_downloads,
        c.total_forks,

        -- Sub-scores
        COALESCE(dr.demand_score, 0) AS demand_score,
        COALESCE(qg.quality_gap_score, 0) AS quality_gap_score,
        ROUND(COALESCE(qg.avg_quality, 0))::int AS avg_quality_score,
        COALESCE(cn.concentration_score, 0) AS concentration_score,
        ROUND(COALESCE(cn.hhi, 0)::numeric, 4) AS hhi,
        COALESCE(gr.graveyard_score, 0) AS graveyard_score,
        COALESCE(gr.graveyard_count, 0) AS graveyard_count,

        -- Temporal sub-scores (null until data exists)
        mc.stars_7d_delta,
        mc.stars_30d_delta,
        CASE WHEN mc.stars_7d_delta IS NOT NULL
            THEN ROUND(PERCENT_RANK() OVER (ORDER BY mc.stars_7d_delta NULLS FIRST) * 100)::int
            ELSE NULL END AS momentum_score,
        st.stadium_ratio,
        CASE WHEN st.stadium_ratio IS NOT NULL
            THEN ROUND(PERCENT_RANK() OVER (ORDER BY st.stadium_ratio NULLS FIRST) * 100)::int
            ELSE NULL END AS stadium_score,

        -- Confidence level
        CASE
            WHEN mc.stars_30d_delta IS NOT NULL THEN 'full'
            WHEN mc.stars_7d_delta IS NOT NULL THEN 'short-term'
            ELSE 'structural'
        END AS confidence_level,
        mc.stars_7d_delta IS NOT NULL AS has_7d_baseline,
        mc.stars_30d_delta IS NOT NULL AS has_30d_baseline

    FROM cats c
    LEFT JOIN demand_ranked dr ON c.domain = dr.domain AND c.subcategory = dr.subcategory
    LEFT JOIN quality_gap_ranked qg ON c.domain = qg.domain AND c.subcategory = qg.subcategory
    LEFT JOIN concentration_calc cn ON c.domain = cn.domain AND c.subcategory = cn.subcategory
    LEFT JOIN graveyard_ranked gr ON c.domain = gr.domain AND c.subcategory = gr.subcategory
    LEFT JOIN momentum_calc mc ON c.domain = mc.domain AND c.subcategory = mc.subcategory
    LEFT JOIN stadium_calc st ON c.domain = st.domain AND c.subcategory = st.subcategory
),

-- Compute composite opportunity score with confidence-weighted formula
scored AS (
    SELECT *,
        LEAST(100, CASE confidence_level
            -- Structural only: no temporal data
            WHEN 'structural' THEN ROUND(
                demand_score * 0.25
                + quality_gap_score * 0.30
                + concentration_score * 0.20
                + graveyard_score * 0.25
            )
            -- Short-term: 7d momentum available
            WHEN 'short-term' THEN ROUND(
                demand_score * 0.20
                + quality_gap_score * 0.25
                + concentration_score * 0.15
                + graveyard_score * 0.15
                + COALESCE(momentum_score, 0) * 0.15
                + COALESCE(stadium_score, 0) * 0.10
            )
            -- Full: 30d+ data available
            ELSE ROUND(
                demand_score * 0.15
                + quality_gap_score * 0.20
                + concentration_score * 0.15
                + graveyard_score * 0.10
                + COALESCE(momentum_score, 0) * 0.20
                + COALESCE(stadium_score, 0) * 0.20
            )
        END)::int AS opportunity_score
    FROM assembled
)
SELECT
    domain, subcategory, repo_count, total_stars, total_downloads, total_forks,
    demand_score, quality_gap_score, avg_quality_score,
    concentration_score, hhi,
    graveyard_score, graveyard_count,
    momentum_score, stars_7d_delta, stars_30d_delta,
    stadium_score, stadium_ratio,
    confidence_level, has_7d_baseline, has_30d_baseline,
    opportunity_score,
    CASE
        WHEN opportunity_score >= 80 THEN 'prime'
        WHEN opportunity_score >= 60 THEN 'promising'
        WHEN opportunity_score >= 40 THEN 'growing'
        WHEN opportunity_score >= 20 THEN 'competitive'
        ELSE 'saturated'
    END AS opportunity_tier
FROM scored
"""


def upgrade() -> None:
    # Create the materialized view
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_category_opportunity CASCADE")
    op.execute(_MV_SQL)
    op.execute(
        "CREATE UNIQUE INDEX idx_mv_cat_opp_uniq "
        "ON mv_category_opportunity (domain, COALESCE(subcategory, ''))"
    )

    # Create the snapshot table
    op.execute("""
        CREATE TABLE IF NOT EXISTS opportunity_snapshots (
            id SERIAL PRIMARY KEY,
            domain VARCHAR(50) NOT NULL,
            subcategory VARCHAR(100) NOT NULL,
            snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
            opportunity_score INT,
            opportunity_tier VARCHAR(20),
            demand_score INT,
            quality_gap_score INT,
            concentration_score INT,
            stadium_score INT,
            momentum_score INT,
            graveyard_score INT,
            confidence_level VARCHAR(20),
            repo_count INT,
            total_stars BIGINT,
            UNIQUE (domain, subcategory, snapshot_date)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_opp_snap_date "
        "ON opportunity_snapshots (snapshot_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_opp_snap_domain "
        "ON opportunity_snapshots (domain, snapshot_date)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_category_opportunity CASCADE")
    op.execute("DROP TABLE IF EXISTS opportunity_snapshots CASCADE")
