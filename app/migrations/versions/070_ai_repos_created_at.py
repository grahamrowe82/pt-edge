"""Add created_at (GitHub repo creation date) to ai_repos

Revision ID: 070
Revises: 069
Create Date: 2026-04-01

Adds created_at column to ai_repos and backfills from projects.repo_created_at.
Rebuilds all 17 quality MVs to use COALESCE(created_at, discovered_at) for age_days
instead of just discovered_at — fixes maturity score for repos discovered late.
Rebuilds nucleation MVs to use created_at for creation velocity.
Cascades through mv_allocation_scores and v_deep_dive_queue.
"""
from string import Template
from typing import Sequence, Union

from alembic import op

revision: str = "070"
down_revision: Union[str, None] = "069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All 17 quality views and their domain filters
ALL_QUALITY_VIEWS = [
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

# Quality MV template — identical to migration 058 except ages CTE uses
# COALESCE(created_at, discovered_at) instead of just discovered_at
_QUALITY_VIEW_SQL = Template("""
CREATE MATERIALIZED VIEW $view_name AS
WITH
dep_counts AS (
    SELECT ar.id AS repo_id, COUNT(DISTINCT pd.repo_id) AS reverse_dep_count
    FROM ai_repos ar
    LEFT JOIN package_deps pd ON (
        (pd.dep_name = ar.pypi_package AND ar.pypi_package IS NOT NULL)
        OR (pd.dep_name = ar.npm_package AND ar.npm_package IS NOT NULL))
    WHERE ar.domain = '$domain'
    GROUP BY ar.id
),
ages AS (
    SELECT id AS repo_id,
           EXTRACT(DAY FROM NOW() - COALESCE(created_at, discovered_at))::int AS age_days
    FROM ai_repos WHERE domain = '$domain'
),
scored AS (
    SELECT
        ar.id, ar.full_name, ar.name, ar.description, ar.ai_summary,
        ar.stars, ar.forks, ar.language, ar.license, ar.archived,
        ar.category, ar.subcategory, ar.last_pushed_at, ar.pypi_package, ar.npm_package,
        ar.downloads_monthly, ar.dependency_count, ar.commits_30d,
        COALESCE(dc.reverse_dep_count, 0) AS reverse_dep_count,
        CASE WHEN ar.archived THEN 0 ELSE
            LEAST(12, CASE
                WHEN COALESCE(ar.commits_30d, 0) = 0 THEN 0
                WHEN ar.commits_30d <= 5 THEN 3 WHEN ar.commits_30d <= 20 THEN 7
                WHEN ar.commits_30d <= 50 THEN 10 ELSE 12 END)
            + CASE
                WHEN ar.last_pushed_at IS NULL THEN 0
                WHEN ar.last_pushed_at >= NOW() - INTERVAL '30 days' THEN 13
                WHEN ar.last_pushed_at >= NOW() - INTERVAL '90 days' THEN 10
                WHEN ar.last_pushed_at >= NOW() - INTERVAL '180 days' THEN 6
                WHEN ar.last_pushed_at >= NOW() - INTERVAL '365 days' THEN 2
                ELSE 0 END
        END AS maintenance_score,
        LEAST(10, CASE WHEN COALESCE(ar.stars, 0) = 0 THEN 0
            ELSE GREATEST(0, (LN(ar.stars + 1) * 2)::int) END)
        + LEAST(10, CASE WHEN COALESCE(ar.downloads_monthly, 0) = 0 THEN 0
            ELSE GREATEST(0, LN(ar.downloads_monthly + 1)::int) END)
        + LEAST(5, COALESCE(dc.reverse_dep_count, 0))
        AS adoption_score,
        CASE WHEN ar.license IS NOT NULL AND ar.license != '' THEN 8 ELSE 0 END
        + CASE WHEN ar.pypi_package IS NOT NULL OR ar.npm_package IS NOT NULL THEN 9 ELSE 0 END
        + LEAST(8, CASE
            WHEN COALESCE(ag.age_days, 0) = 0 THEN 0
            WHEN ag.age_days < 30 THEN 1 WHEN ag.age_days < 90 THEN 3
            WHEN ag.age_days < 180 THEN 5 WHEN ag.age_days < 365 THEN 7
            ELSE 8 END)
        AS maturity_score,
        LEAST(15, CASE WHEN COALESCE(ar.forks, 0) = 0 THEN 0
            ELSE GREATEST(0, (LN(ar.forks + 1) * 3)::int) END)
        + LEAST(10, CASE WHEN COALESCE(ar.stars, 0) = 0 THEN 0
            ELSE LEAST(10, ROUND(COALESCE(ar.forks, 0)::numeric / NULLIF(ar.stars, 0) * 50))::int END)
        AS community_score
    FROM ai_repos ar
    LEFT JOIN dep_counts dc ON ar.id = dc.repo_id
    LEFT JOIN ages ag ON ar.id = ag.repo_id
    WHERE ar.domain = '$domain'
)
SELECT id, full_name, name, description, ai_summary, stars, forks, language, license, archived,
    category, subcategory, last_pushed_at, pypi_package, npm_package, downloads_monthly,
    dependency_count, commits_30d, reverse_dep_count,
    maintenance_score, adoption_score, maturity_score, community_score,
    LEAST(100, maintenance_score + adoption_score + maturity_score + community_score) AS quality_score,
    CASE
        WHEN LEAST(100, maintenance_score + adoption_score + maturity_score + community_score) >= 70 THEN 'verified'
        WHEN LEAST(100, maintenance_score + adoption_score + maturity_score + community_score) >= 50 THEN 'established'
        WHEN LEAST(100, maintenance_score + adoption_score + maturity_score + community_score) >= 30 THEN 'emerging'
        ELSE 'experimental'
    END AS quality_tier,
    (
        CASE WHEN archived THEN ARRAY['archived'] ELSE ARRAY[]::text[] END
        || CASE WHEN license IS NULL OR license = '' THEN ARRAY['no_license'] ELSE ARRAY[]::text[] END
        || CASE WHEN last_pushed_at < NOW() - INTERVAL '180 days' OR last_pushed_at IS NULL
                THEN ARRAY['stale_6m'] ELSE ARRAY[]::text[] END
        || CASE WHEN pypi_package IS NULL AND npm_package IS NULL
                THEN ARRAY['no_package'] ELSE ARRAY[]::text[] END
        || CASE WHEN COALESCE(dependency_count, 0) = 0 AND reverse_dep_count = 0
                THEN ARRAY['no_dependents'] ELSE ARRAY[]::text[] END
    ) AS risk_flags
FROM scored
""")


def upgrade() -> None:
    # ── 1. Add created_at column ──────────────────────────────────────────
    op.execute("ALTER TABLE ai_repos ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_repos_created_at ON ai_repos (created_at)")

    # ── 2. Backfill from projects.repo_created_at ─────────────────────────
    op.execute("""
        UPDATE ai_repos ar
        SET created_at = p.repo_created_at
        FROM projects p
        WHERE p.ai_repo_id = ar.id
          AND p.repo_created_at IS NOT NULL
          AND ar.created_at IS NULL
    """)

    # ── 3. Rebuild all 17 quality MVs with fixed ages CTE ─────────────────
    # Must drop mv_allocation_scores and v_deep_dive_queue first (they depend
    # on quality MVs), then rebuild them after.
    op.execute("DROP VIEW IF EXISTS v_deep_dive_queue CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_allocation_scores CASCADE")

    for view_name, domain in ALL_QUALITY_VIEWS:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view_name} CASCADE")
        op.execute(_QUALITY_VIEW_SQL.substitute(view_name=view_name, domain=domain))
        op.execute(f"CREATE UNIQUE INDEX idx_{view_name}_id ON {view_name} (id)")

    # ── 4. Rebuild mv_allocation_scores (unchanged SQL from 067) ──────────
    # Import the SQL from migration 067 would be fragile; use pg_catalog to
    # confirm it doesn't exist, then recreate from the canonical definition.
    _rebuild_allocation_scores()

    # ── 5. Rebuild nucleation MVs with created_at ─────────────────────────
    op.execute("DROP VIEW IF EXISTS v_nucleation_report CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_nucleation_project CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_nucleation_category CASCADE")
    _rebuild_nucleation_project()
    _rebuild_nucleation_category()
    _rebuild_nucleation_report()


def downgrade() -> None:
    # Rebuild nucleation MVs without created_at (from 069)
    op.execute("DROP VIEW IF EXISTS v_nucleation_report CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_nucleation_category CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_nucleation_project CASCADE")

    # Rebuild quality MVs with old ages CTE (discovered_at only)
    op.execute("DROP VIEW IF EXISTS v_deep_dive_queue CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_allocation_scores CASCADE")
    for view_name, _ in ALL_QUALITY_VIEWS:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view_name} CASCADE")

    # Drop column
    op.execute("DROP INDEX IF EXISTS ix_ai_repos_created_at")
    op.execute("ALTER TABLE ai_repos DROP COLUMN IF EXISTS created_at")
    # Note: does NOT recreate 069/067 versions — run those upgrades for that


# ═══════════════════════════════════════════════════════════════════════════
# Helper functions for rebuilding dependent MVs
# ═══════════════════════════════════════════════════════════════════════════

def _rebuild_allocation_scores():
    """Recreate mv_allocation_scores — unchanged from migration 067."""
    # Allocation MV SQL inlined from migration 067 — unchanged, but must be
    # rebuilt because it depends on quality MVs which were just rebuilt.
    _DOMAIN_CASE = """
        CASE
            WHEN page LIKE '%/agents/%' THEN 'agents'
            WHEN page LIKE '%/rag/%' THEN 'rag'
            WHEN page LIKE '%/ai-coding/%' THEN 'ai-coding'
            WHEN page LIKE '%/voice-ai/%' THEN 'voice-ai'
            WHEN page LIKE '%/diffusion/%' THEN 'diffusion'
            WHEN page LIKE '%/vector-db/%' THEN 'vector-db'
            WHEN page LIKE '%/embeddings/%' THEN 'embeddings'
            WHEN page LIKE '%/prompt-engineering/%' THEN 'prompt-engineering'
            WHEN page LIKE '%/ml-frameworks/%' THEN 'ml-frameworks'
            WHEN page LIKE '%/llm-tools/%' THEN 'llm-tools'
            WHEN page LIKE '%/nlp/%' THEN 'nlp'
            WHEN page LIKE '%/transformers/%' THEN 'transformers'
            WHEN page LIKE '%/generative-ai/%' THEN 'generative-ai'
            WHEN page LIKE '%/computer-vision/%' THEN 'computer-vision'
            WHEN page LIKE '%/data-engineering/%' THEN 'data-engineering'
            WHEN page LIKE '%/mlops/%' THEN 'mlops'
            ELSE 'mcp'
        END"""

    _SUBCAT_EXTRACT = """REGEXP_REPLACE(
            REGEXP_REPLACE(page, '.*/categories/([^/]+)/?$', '\\1'),
            '^https://.*$', NULL
        )"""

    op.execute(f"""
CREATE MATERIALIZED VIEW mv_allocation_scores AS
WITH
cats AS (
    SELECT domain, subcategory, COUNT(*) AS repo_count,
        COALESCE(SUM(stars), 0) AS total_stars, COALESCE(SUM(forks), 0) AS total_forks
    FROM ai_repos WHERE domain <> 'uncategorized'
      AND subcategory IS NOT NULL AND subcategory <> ''
    GROUP BY domain, subcategory HAVING COUNT(*) >= 2
),
snapshot_range AS (
    SELECT MAX(snapshot_date) AS latest_date, MAX(snapshot_date) - 7 AS d7_cutoff
    FROM ai_repo_snapshots
),
cat_snap_latest AS (
    SELECT ar.domain, ar.subcategory, SUM(s.stars) AS total_stars, SUM(s.forks) AS total_forks
    FROM ai_repos ar JOIN ai_repo_snapshots s ON s.repo_id = ar.id
    CROSS JOIN snapshot_range sr WHERE s.snapshot_date = sr.latest_date
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),
cat_snap_7d AS (
    SELECT ar.domain, ar.subcategory, SUM(s.stars) AS total_stars, SUM(s.forks) AS total_forks
    FROM ai_repos ar JOIN ai_repo_snapshots s ON s.repo_id = ar.id
    WHERE s.snapshot_date = (SELECT MAX(snapshot_date) FROM ai_repo_snapshots
        WHERE snapshot_date <= (SELECT d7_cutoff FROM snapshot_range))
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),
github_velocity AS (
    SELECT l.domain, l.subcategory,
        COALESCE(l.total_stars - s7.total_stars, 0) AS star_velocity_7d,
        COALESCE(l.total_forks - s7.total_forks, 0) AS fork_acceleration_7d
    FROM cat_snap_latest l
    LEFT JOIN cat_snap_7d s7 ON l.domain = s7.domain AND l.subcategory = s7.subcategory
),
new_repos AS (
    SELECT domain, subcategory, COUNT(*) AS new_repos_7d
    FROM ai_repos WHERE discovered_at >= NOW() - INTERVAL '7 days'
      AND subcategory IS NOT NULL AND subcategory <> ''
    GROUP BY domain, subcategory
),
hn_velocity AS (
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
newsletter_velocity AS (
    SELECT ar.domain, ar.subcategory,
           COUNT(DISTINCT nm.id) AS newsletter_mentions_7d
    FROM newsletter_mentions nm,
         jsonb_array_elements(nm.mentions) AS m
    JOIN projects p ON p.id = (m->>'project_id')::int
    JOIN ai_repos ar ON p.ai_repo_id = ar.id
    WHERE nm.published_at >= NOW() - INTERVAL '7 days'
      AND m->>'project_id' IS NOT NULL
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),
release_velocity AS (
    SELECT ar.domain, ar.subcategory, COUNT(*) AS releases_7d
    FROM releases r JOIN projects p ON r.project_id = p.id
    JOIN ai_repos ar ON p.ai_repo_id = ar.id
    WHERE r.released_at >= NOW() - INTERVAL '7 days'
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),
content_coverage AS (
    SELECT domain, subcategory,
           COUNT(*) FILTER (WHERE ai_summary IS NOT NULL)::numeric
               / GREATEST(COUNT(*), 1) AS summary_ratio
    FROM ai_repos WHERE subcategory IS NOT NULL AND subcategory <> ''
    GROUP BY domain, subcategory
),
gsc_all_by_domain AS (
    SELECT {_DOMAIN_CASE} AS domain,
        SUM(impressions) AS impressions, SUM(clicks) AS clicks
    FROM gsc_search_data WHERE search_date >= CURRENT_DATE - 7 GROUP BY 1
),
domain_prior AS (
    SELECT domain, COUNT(*)::numeric / NULLIF(SUM(COUNT(*)) OVER (), 0) AS expected_share
    FROM ai_repos WHERE domain <> 'uncategorized' GROUP BY domain
),
domain_surprise AS (
    SELECT p.domain, COALESCE(a.impressions, 0) AS domain_impressions_7d,
        CASE WHEN SUM(COALESCE(a.impressions, 0)) OVER () > 0
            THEN (COALESCE(a.impressions, 0)::numeric / SUM(COALESCE(a.impressions, 0)) OVER ())
                 / NULLIF(p.expected_share, 0) ELSE 0 END AS surprise_ratio
    FROM domain_prior p LEFT JOIN gsc_all_by_domain a ON p.domain = a.domain
),
gsc_current AS (
    SELECT {_DOMAIN_CASE} AS domain, {_SUBCAT_EXTRACT} AS subcategory,
        SUM(impressions) AS impressions, SUM(clicks) AS clicks, AVG(position) AS avg_position
    FROM gsc_search_data WHERE search_date >= CURRENT_DATE - 7 AND page LIKE '%/categories/%'
    GROUP BY 1, 2 HAVING {_SUBCAT_EXTRACT} IS NOT NULL
),
gsc_previous AS (
    SELECT {_DOMAIN_CASE} AS domain, {_SUBCAT_EXTRACT} AS subcategory,
        SUM(impressions) AS impressions, SUM(clicks) AS clicks, AVG(position) AS avg_position
    FROM gsc_search_data WHERE search_date BETWEEN CURRENT_DATE - 14 AND CURRENT_DATE - 8
      AND page LIKE '%/categories/%'
    GROUP BY 1, 2 HAVING {_SUBCAT_EXTRACT} IS NOT NULL
),
gsc_stats AS (
    SELECT COALESCE(gc.domain, gp.domain) AS domain,
        COALESCE(gc.subcategory, gp.subcategory) AS subcategory,
        COALESCE(gc.impressions, 0) AS gsc_impressions_7d,
        COALESCE(gc.clicks, 0) AS gsc_clicks_7d, gc.avg_position AS gsc_avg_position,
        CASE WHEN COALESCE(gp.impressions, 0) > 0
            THEN (COALESCE(gc.impressions, 0) - gp.impressions)::numeric / gp.impressions ELSE NULL END AS gsc_impression_growth_7d,
        CASE WHEN COALESCE(gp.clicks, 0) > 0
            THEN (COALESCE(gc.clicks, 0) - gp.clicks)::numeric / gp.clicks ELSE NULL END AS gsc_click_growth_7d,
        CASE WHEN gp.avg_position IS NOT NULL AND gc.avg_position IS NOT NULL
            THEN gp.avg_position - gc.avg_position ELSE NULL END AS gsc_position_improvement
    FROM gsc_current gc FULL OUTER JOIN gsc_previous gp
        ON gc.domain = gp.domain AND gc.subcategory = gp.subcategory
    WHERE COALESCE(gc.domain, gp.domain) IS NOT NULL
),
gsc_position AS (
    SELECT domain, subcategory, gsc_avg_position, gsc_impressions_7d, gsc_clicks_7d,
        CASE WHEN gsc_avg_position IS NOT NULL
            THEN GREATEST(0, 100 - LEAST(gsc_avg_position, 20) * 5) ELSE NULL END AS position_strength,
        CASE WHEN gsc_impressions_7d > 0 AND gsc_avg_position IS NOT NULL
            THEN (gsc_clicks_7d::numeric / gsc_impressions_7d)
                 / CASE WHEN gsc_avg_position <= 1 THEN 0.398 WHEN gsc_avg_position <= 2 THEN 0.187
                    WHEN gsc_avg_position <= 3 THEN 0.102 WHEN gsc_avg_position <= 4 THEN 0.072
                    WHEN gsc_avg_position <= 5 THEN 0.051 WHEN gsc_avg_position <= 6 THEN 0.044
                    WHEN gsc_avg_position <= 7 THEN 0.030 WHEN gsc_avg_position <= 8 THEN 0.021
                    WHEN gsc_avg_position <= 9 THEN 0.019 WHEN gsc_avg_position <= 10 THEN 0.016
                    ELSE 0.010 END ELSE NULL END AS ctr_vs_benchmark
    FROM gsc_stats
),
umami_stats AS (
    SELECT domain, subcategory, SUM(pageviews) AS umami_pageviews_7d,
        AVG(unique_sessions) AS umami_avg_sessions
    FROM umami_page_stats WHERE stat_date >= CURRENT_DATE - 7 AND subcategory IS NOT NULL
    GROUP BY domain, subcategory
),
assembled AS (
    SELECT c.domain, c.subcategory, c.repo_count, c.total_stars,
        COALESCE(gs.gsc_impression_growth_7d, 0) AS gsc_impression_growth_7d,
        COALESCE(gs.gsc_click_growth_7d, 0) AS gsc_click_growth_7d,
        COALESCE(gs.gsc_position_improvement, 0) AS gsc_position_improvement,
        COALESCE(gs.gsc_impressions_7d, 0) AS gsc_impressions_7d,
        COALESCE(gs.gsc_clicks_7d, 0) AS gsc_clicks_7d, gs.gsc_avg_position,
        gp.position_strength, gp.ctr_vs_benchmark,
        COALESCE(ds.surprise_ratio, 0) AS surprise_ratio,
        COALESCE(ds.domain_impressions_7d, 0) AS domain_impressions_7d,
        COALESCE(um.umami_pageviews_7d, 0) AS umami_pageviews_7d,
        COALESCE(um.umami_avg_sessions, 0) AS umami_avg_sessions,
        COALESCE(gv.star_velocity_7d, 0) AS github_star_velocity_7d,
        COALESCE(nr.new_repos_7d, 0) AS github_new_repos_7d,
        COALESCE(gv.fork_acceleration_7d, 0) AS github_fork_acceleration_7d,
        CASE WHEN COALESCE(gs.gsc_impressions_7d, 0) > 0 THEN 1.0 ELSE 0.0 END AS gsc_coverage_ratio,
        COALESCE(hv.hn_posts_7d, 0) AS hn_posts_7d,
        COALESCE(hv.hn_points_7d, 0) AS hn_points_7d,
        COALESCE(nv.newsletter_mentions_7d, 0) AS newsletter_mentions_7d,
        COALESCE(rv.releases_7d, 0) AS releases_7d,
        COALESCE(cc.summary_ratio, 0) AS summary_ratio
    FROM cats c
    LEFT JOIN github_velocity gv ON c.domain = gv.domain AND c.subcategory = gv.subcategory
    LEFT JOIN new_repos nr ON c.domain = nr.domain AND c.subcategory = nr.subcategory
    LEFT JOIN gsc_stats gs ON c.domain = gs.domain AND c.subcategory = gs.subcategory
    LEFT JOIN gsc_position gp ON c.domain = gp.domain AND c.subcategory = gp.subcategory
    LEFT JOIN domain_surprise ds ON c.domain = ds.domain
    LEFT JOIN umami_stats um ON c.domain = um.domain AND c.subcategory = um.subcategory
    LEFT JOIN hn_velocity hv ON c.domain = hv.domain AND c.subcategory = hv.subcategory
    LEFT JOIN newsletter_velocity nv ON c.domain = nv.domain AND c.subcategory = nv.subcategory
    LEFT JOIN release_velocity rv ON c.domain = rv.domain AND c.subcategory = rv.subcategory
    LEFT JOIN content_coverage cc ON c.domain = cc.domain AND c.subcategory = cc.subcategory
),
ehs_scored AS (
    SELECT *, LEAST(100, ROUND(
        25 * PERCENT_RANK() OVER (ORDER BY gsc_impression_growth_7d)
      + 20 * PERCENT_RANK() OVER (ORDER BY gsc_click_growth_7d)
      + 15 * PERCENT_RANK() OVER (ORDER BY gsc_position_improvement)
      + 15 * PERCENT_RANK() OVER (ORDER BY COALESCE(ctr_vs_benchmark, 0))
      + 15 * PERCENT_RANK() OVER (ORDER BY umami_pageviews_7d)
      + 10 * PERCENT_RANK() OVER (ORDER BY umami_avg_sessions)
    ))::int AS ehs FROM assembled
),
scored AS (
    SELECT *, LEAST(100, ROUND(
        20 * PERCENT_RANK() OVER (ORDER BY github_star_velocity_7d)
      + 15 * PERCENT_RANK() OVER (ORDER BY github_new_repos_7d)
      + 5  * PERCENT_RANK() OVER (ORDER BY github_fork_acceleration_7d)
      + 15 * (1 - gsc_coverage_ratio)
      + 15 * PERCENT_RANK() OVER (ORDER BY COALESCE(position_strength, 0))
      + 15 * PERCENT_RANK() OVER (ORDER BY hn_points_7d)
      + 10 * PERCENT_RANK() OVER (ORDER BY newsletter_mentions_7d)
      + 5  * PERCENT_RANK() OVER (ORDER BY releases_7d)
    ))::int AS es FROM ehs_scored
)
SELECT domain, subcategory, repo_count, total_stars,
    ehs, gsc_impression_growth_7d, gsc_click_growth_7d, gsc_position_improvement,
    gsc_impressions_7d, gsc_clicks_7d, gsc_avg_position, ctr_vs_benchmark,
    umami_pageviews_7d, umami_avg_sessions,
    es, github_star_velocity_7d, github_new_repos_7d, github_fork_acceleration_7d,
    gsc_coverage_ratio, position_strength,
    hn_posts_7d, hn_points_7d, newsletter_mentions_7d, releases_7d, summary_ratio,
    surprise_ratio, domain_impressions_7d,
    CASE
        WHEN domain_impressions_7d >= 50 AND gsc_impressions_7d >= 50 THEN 'full'
        WHEN domain_impressions_7d >= 50 THEN 'domain-level'
        WHEN gsc_impressions_7d > 0 THEN 'gsc-sparse'
        WHEN umami_pageviews_7d > 0 THEN 'umami-only'
        ELSE 'github-only'
    END AS confidence_level,
    GREATEST(ehs, es) AS opportunity_score,
    CASE
        WHEN GREATEST(ehs, es) >= 80 THEN 'prime'
        WHEN GREATEST(ehs, es) >= 60 THEN 'promising'
        WHEN GREATEST(ehs, es) >= 40 THEN 'growing'
        WHEN GREATEST(ehs, es) >= 20 THEN 'competitive'
        ELSE 'saturated'
    END AS opportunity_tier
FROM scored
    """)
    op.execute(
        "CREATE UNIQUE INDEX idx_mv_alloc_scores_uniq "
        "ON mv_allocation_scores (domain, COALESCE(subcategory, ''))"
    )

    # Recreate v_deep_dive_queue
    op.execute("""
        CREATE OR REPLACE VIEW v_deep_dive_queue AS
        SELECT
            a.domain, a.subcategory, a.ehs, a.es,
            GREATEST(a.ehs, a.es) AS combined_score,
            a.repo_count, a.total_stars, a.confidence_level,
            a.surprise_ratio, a.position_strength, a.ctr_vs_benchmark,
            a.gsc_impressions_7d, a.gsc_clicks_7d, a.domain_impressions_7d,
            a.github_star_velocity_7d, a.github_new_repos_7d, a.umami_pageviews_7d,
            a.hn_points_7d, a.newsletter_mentions_7d, a.releases_7d, a.summary_ratio,
            CASE
                WHEN a.ehs >= a.es AND a.ehs >= 50 THEN 'established_heat'
                WHEN a.es >= 50 THEN 'emerging_signal'
                ELSE 'below_threshold'
            END AS queue
        FROM mv_allocation_scores a
        WHERE GREATEST(a.ehs, a.es) > 20
        ORDER BY GREATEST(a.ehs, a.es) DESC
    """)


def _rebuild_nucleation_project():
    """Recreate mv_nucleation_project with created_at in output."""
    op.execute("""
CREATE MATERIALIZED VIEW mv_nucleation_project AS
WITH
snapshot_bounds AS (
    SELECT MAX(snapshot_date) AS latest, MAX(snapshot_date) - 7 AS target_7d,
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
star_delta AS (
    SELECT s_now.repo_id, s_now.stars AS stars_now,
           s_now.stars - COALESCE(s_prev.stars, 0) AS star_delta_7d
    FROM ai_repo_snapshots s_now
    CROSS JOIN snapshot_bounds sb
    LEFT JOIN baseline_date bd ON TRUE
    LEFT JOIN ai_repo_snapshots s_prev
        ON s_prev.repo_id = s_now.repo_id AND s_prev.snapshot_date = bd.d7
    WHERE s_now.snapshot_date = sb.latest AND sb.latest <> bd.d7
),
star_zscore AS (
    SELECT sd.repo_id, sd.star_delta_7d,
        CASE WHEN STDDEV(sd.star_delta_7d) OVER (PARTITION BY ar.domain, ar.subcategory) > 0
            THEN (sd.star_delta_7d - AVG(sd.star_delta_7d) OVER (PARTITION BY ar.domain, ar.subcategory))
                 / STDDEV(sd.star_delta_7d) OVER (PARTITION BY ar.domain, ar.subcategory)
            ELSE 0 END AS star_velocity_zscore
    FROM star_delta sd JOIN ai_repos ar ON ar.id = sd.repo_id
    WHERE ar.subcategory IS NOT NULL AND ar.subcategory <> ''
),
hn_signal AS (
    SELECT ar.id AS repo_id, COUNT(DISTINCT hp.id) AS hn_posts_7d,
           COALESCE(SUM(hp.points), 0) AS hn_points_7d
    FROM ai_repos ar JOIN projects p ON p.ai_repo_id = ar.id
    JOIN hn_posts hp ON hp.project_id = p.id
    WHERE hp.posted_at >= NOW() - INTERVAL '7 days' GROUP BY ar.id
),
newsletter_signal AS (
    SELECT ar.id AS repo_id, COUNT(*) AS newsletter_mentions_7d,
           COUNT(DISTINCT nm.feed_slug) AS newsletter_feeds_7d
    FROM newsletter_mentions nm, jsonb_array_elements(nm.mentions) AS m
    JOIN projects p ON p.id = (m->>'project_id')::int
    JOIN ai_repos ar ON p.ai_repo_id = ar.id
    WHERE nm.published_at >= NOW() - INTERVAL '7 days' AND m->>'project_id' IS NOT NULL
    GROUP BY ar.id
),
release_signal AS (
    SELECT ar.id AS repo_id, COUNT(*) AS releases_7d
    FROM releases r JOIN projects p ON r.project_id = p.id
    JOIN ai_repos ar ON p.ai_repo_id = ar.id
    WHERE r.released_at >= NOW() - INTERVAL '7 days' GROUP BY ar.id
),
assembled AS (
    SELECT ar.id, ar.full_name, ar.name, ar.domain, ar.subcategory,
        ar.stars, ar.commits_30d, ar.created_at,
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
      AND (COALESCE(sz.star_delta_7d, 0) > 0 OR COALESCE(hs.hn_posts_7d, 0) > 0
           OR COALESCE(ns.newsletter_mentions_7d, 0) > 0 OR COALESCE(rs.releases_7d, 0) > 0
           OR COALESCE(ar.commits_30d, 0) > 0)
),
scored AS (
    SELECT *, LEAST(100, ROUND(
        35 * PERCENT_RANK() OVER (ORDER BY star_velocity_zscore)
      + 20 * PERCENT_RANK() OVER (ORDER BY hn_points_7d)
      + 15 * PERCENT_RANK() OVER (ORDER BY newsletter_feeds_7d)
      + 15 * PERCENT_RANK() OVER (ORDER BY releases_7d)
      + 15 * PERCENT_RANK() OVER (ORDER BY COALESCE(commits_30d, 0))
    ))::int AS nucleation_score FROM assembled
)
SELECT id, full_name, name, domain, subcategory, stars, commits_30d, created_at,
    star_delta_7d, star_velocity_zscore,
    hn_posts_7d, hn_points_7d, newsletter_mentions_7d, newsletter_feeds_7d,
    releases_7d, nucleation_score,
    CASE WHEN star_velocity_zscore >= 1.5 AND hn_posts_7d = 0 AND newsletter_mentions_7d = 0
        THEN TRUE ELSE FALSE END AS narrative_gap
FROM scored
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_nucleation_project_id ON mv_nucleation_project (id)")


def _rebuild_nucleation_category():
    """Recreate mv_nucleation_category using COALESCE(created_at, discovered_at)."""
    op.execute("""
CREATE MATERIALIZED VIEW mv_nucleation_category AS
WITH
new_7d AS (
    SELECT domain, subcategory, COUNT(*) AS new_repos_7d,
           COALESCE(SUM(stars), 0) AS new_repo_stars_7d
    FROM ai_repos
    WHERE COALESCE(created_at, discovered_at) >= NOW() - INTERVAL '7 days'
      AND subcategory IS NOT NULL AND subcategory <> ''
    GROUP BY domain, subcategory
),
new_14d AS (
    SELECT domain, subcategory, COUNT(*) AS new_repos_14d
    FROM ai_repos
    WHERE COALESCE(created_at, discovered_at) >= NOW() - INTERVAL '14 days'
      AND subcategory IS NOT NULL AND subcategory <> ''
    GROUP BY domain, subcategory
),
hn_cat AS (
    SELECT ar.domain, ar.subcategory,
           COUNT(DISTINCT hp.id) AS hn_posts_7d,
           COALESCE(SUM(hp.points), 0) AS hn_points_7d
    FROM hn_posts hp JOIN projects p ON hp.project_id = p.id
    JOIN ai_repos ar ON p.ai_repo_id = ar.id
    WHERE hp.posted_at >= NOW() - INTERVAL '7 days'
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),
nl_cat AS (
    SELECT ar.domain, ar.subcategory, COUNT(*) AS newsletter_mentions_7d
    FROM newsletter_mentions nm, jsonb_array_elements(nm.mentions) AS m
    JOIN projects p ON p.id = (m->>'project_id')::int
    JOIN ai_repos ar ON p.ai_repo_id = ar.id
    WHERE nm.published_at >= NOW() - INTERVAL '7 days'
      AND m->>'project_id' IS NOT NULL
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),
assembled AS (
    SELECT COALESCE(n7.domain, n14.domain) AS domain,
        COALESCE(n7.subcategory, n14.subcategory) AS subcategory,
        COALESCE(n7.new_repos_7d, 0) AS new_repos_7d,
        COALESCE(n14.new_repos_14d, 0) AS new_repos_14d,
        COALESCE(n7.new_repo_stars_7d, 0) AS new_repo_stars_7d,
        CASE WHEN COALESCE(n14.new_repos_14d, 0) - COALESCE(n7.new_repos_7d, 0) > 0
            THEN COALESCE(n7.new_repos_7d, 0)::numeric
                 / (COALESCE(n14.new_repos_14d, 0) - COALESCE(n7.new_repos_7d, 0))
            ELSE NULL END AS acceleration,
        COALESCE(hc.hn_posts_7d, 0) + COALESCE(hc.hn_points_7d, 0) AS hn_coverage_7d,
        COALESCE(nc.newsletter_mentions_7d, 0) AS newsletter_coverage_7d
    FROM new_7d n7
    FULL OUTER JOIN new_14d n14 ON n7.domain = n14.domain AND n7.subcategory = n14.subcategory
    LEFT JOIN hn_cat hc ON COALESCE(n7.domain, n14.domain) = hc.domain
        AND COALESCE(n7.subcategory, n14.subcategory) = hc.subcategory
    LEFT JOIN nl_cat nc ON COALESCE(n7.domain, n14.domain) = nc.domain
        AND COALESCE(n7.subcategory, n14.subcategory) = nc.subcategory
    WHERE COALESCE(n7.new_repos_7d, 0) + COALESCE(n14.new_repos_14d, 0) > 0
)
SELECT domain, subcategory, new_repos_7d, new_repos_14d, new_repo_stars_7d,
    acceleration, hn_coverage_7d, newsletter_coverage_7d,
    CASE WHEN new_repos_7d >= 3 AND hn_coverage_7d = 0 AND newsletter_coverage_7d = 0
        THEN TRUE ELSE FALSE END AS creation_without_buzz
FROM assembled
    """)
    op.execute(
        "CREATE UNIQUE INDEX idx_mv_nucleation_cat_uniq "
        "ON mv_nucleation_category (domain, COALESCE(subcategory, ''))"
    )


def _rebuild_nucleation_report():
    """Recreate v_nucleation_report."""
    op.execute("""
CREATE OR REPLACE VIEW v_nucleation_report AS
SELECT 'project'::text AS section, np.name AS label, np.full_name AS detail,
    np.domain, np.subcategory, np.nucleation_score AS score, np.narrative_gap AS gap_flag,
    np.star_delta_7d, np.star_velocity_zscore,
    np.hn_posts_7d, np.hn_points_7d, np.newsletter_mentions_7d, np.newsletter_feeds_7d,
    np.releases_7d, np.stars, NULL::int AS new_repos_7d, NULL::numeric AS acceleration
FROM mv_nucleation_project np WHERE np.nucleation_score >= 30
UNION ALL
SELECT 'category'::text AS section, nc.subcategory AS label, nc.domain AS detail,
    nc.domain, nc.subcategory,
    LEAST(100, COALESCE(nc.new_repos_7d * COALESCE(nc.acceleration, 1), 0))::int AS score,
    nc.creation_without_buzz AS gap_flag,
    NULL::int, NULL::numeric, NULL::int, NULL::int, NULL::int, NULL::int,
    NULL::int, NULL::int, nc.new_repos_7d, nc.acceleration
FROM mv_nucleation_category nc WHERE nc.new_repos_7d >= 1
    """)
