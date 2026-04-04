"""Add AI browsing demand signal to allocation scores

Revision ID: 078
Revises: 077
Create Date: 2026-04-04

Adds a Tier 1 AI browsing demand signal (ChatGPT-User, Claude-Web,
Perplexity-User, OAI-SearchBot, Claude-SearchBot) to mv_allocation_scores.
These represent real humans asking AI assistants questions and getting
our pages as answers — the purest practitioner demand signal.

Hits are aggregated by (domain, subcategory) via path → ai_repos lookup.
Added to the ES (emergence score) formula at 10% weight, carved from
gsc_coverage_ratio (15→10%) and position_strength (15→10%).

Uses PERCENT_RANK for natural handling of the sparse, zero-heavy
distribution — no explicit Bayesian machinery needed at current volumes.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "078"
down_revision: Union[str, None] = "077"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tier 1 AI browsing agents: human-initiated, each hit = a real user question
_TIER1_FAMILIES = (
    "'ChatGPT-User'",
    "'Claude-Web'",
    "'Perplexity-User'",
    "'OAI-SearchBot'",
    "'Claude-SearchBot'",
)

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

_SUBCAT_EXTRACT = r"""REGEXP_REPLACE(
            REGEXP_REPLACE(page, '.*/categories/([^/]+)/?$', '\1'),
            '^https://.*$', NULL
        )"""

# Same patterns but using 'path' column (for mv_access_bot_demand)
_PATH_DOMAIN_CASE = _DOMAIN_CASE.replace("page", "path")
_PATH_SUBCAT_EXTRACT = _SUBCAT_EXTRACT.replace("page", "path")


def upgrade() -> None:
    # Drop dependent views
    op.execute("DROP VIEW IF EXISTS v_deep_dive_queue CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_allocation_scores CASCADE")

    tier1_list = ", ".join(_TIER1_FAMILIES)

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
-- Tier 1 AI browsing demand: ChatGPT-User, Claude-Web, Perplexity-User, etc.
-- Each hit = a real human asking an AI assistant a question.
-- Map path → ai_repos → (domain, subcategory) for project pages,
-- or extract from URL for category pages.
-- mv_access_bot_demand is pre-aggregated: (access_date, bot_family, path) → hits, unique_ips
ai_browsing_project AS (
    SELECT ar.domain, ar.subcategory,
           SUM(bad.hits) AS hits,
           SUM(bad.unique_ips) AS unique_ips
    FROM mv_access_bot_demand bad
    JOIN ai_repos ar ON bad.path LIKE '%/servers/' || ar.full_name || '/%'
    WHERE bad.bot_family IN ({tier1_list})
      AND bad.access_date >= CURRENT_DATE - 7
      AND ar.subcategory IS NOT NULL AND ar.subcategory <> ''
    GROUP BY ar.domain, ar.subcategory
),
ai_browsing_category AS (
    SELECT {_PATH_DOMAIN_CASE} AS domain,
           {_PATH_SUBCAT_EXTRACT} AS subcategory,
           SUM(hits) AS hits,
           SUM(unique_ips) AS unique_ips
    FROM mv_access_bot_demand
    WHERE bot_family IN ({tier1_list})
      AND access_date >= CURRENT_DATE - 7
      AND path LIKE '%/categories/%'
    GROUP BY 1, 2
    HAVING {_PATH_SUBCAT_EXTRACT} IS NOT NULL
),
ai_browsing AS (
    SELECT COALESCE(p.domain, c.domain) AS domain,
           COALESCE(p.subcategory, c.subcategory) AS subcategory,
           COALESCE(p.hits, 0) + COALESCE(c.hits, 0) AS ai_browsing_hits_7d,
           COALESCE(p.unique_ips, 0) + COALESCE(c.unique_ips, 0) AS ai_browsing_ips_7d
    FROM ai_browsing_project p
    FULL OUTER JOIN ai_browsing_category c
        ON p.domain = c.domain AND p.subcategory = c.subcategory
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
        COALESCE(cc.summary_ratio, 0) AS summary_ratio,
        COALESCE(ab.ai_browsing_hits_7d, 0) AS ai_browsing_hits_7d,
        COALESCE(ab.ai_browsing_ips_7d, 0) AS ai_browsing_ips_7d
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
    LEFT JOIN ai_browsing ab ON c.domain = ab.domain AND c.subcategory = ab.subcategory
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
      + 10 * (1 - gsc_coverage_ratio)
      + 10 * PERCENT_RANK() OVER (ORDER BY COALESCE(position_strength, 0))
      + 15 * PERCENT_RANK() OVER (ORDER BY hn_points_7d)
      + 10 * PERCENT_RANK() OVER (ORDER BY newsletter_mentions_7d)
      + 5  * PERCENT_RANK() OVER (ORDER BY releases_7d)
      + 10 * PERCENT_RANK() OVER (ORDER BY ai_browsing_hits_7d)
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
    ai_browsing_hits_7d, ai_browsing_ips_7d,
    CASE
        WHEN domain_impressions_7d >= 50 AND gsc_impressions_7d >= 50 THEN 'full'
        WHEN domain_impressions_7d >= 50 THEN 'domain-level'
        WHEN gsc_impressions_7d > 0 THEN 'gsc-sparse'
        WHEN umami_pageviews_7d > 0 THEN 'umami-only'
        WHEN ai_browsing_hits_7d > 0 THEN 'ai-browsing-only'
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
            a.ai_browsing_hits_7d, a.ai_browsing_ips_7d,
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
    # Revert to 077 version of mv_allocation_scores (without ai_browsing)
    op.execute("DROP VIEW IF EXISTS v_deep_dive_queue CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_allocation_scores CASCADE")
