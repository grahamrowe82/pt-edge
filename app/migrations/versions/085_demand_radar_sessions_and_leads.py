"""Demand Radar: session detection table + warm leads view

Revision ID: 085
Revises: 084
Create Date: 2026-04-06

Two tactical fixes from the Demand Radar research:

1. bot_sessions table — populated daily by worker task that detects
   multi-page AI agent sessions from raw access logs, including
   cross-IP fan-out detection for OAI-SearchBot.

2. mv_warm_leads MV — identifies commercial entities (multi-repo GitHub
   orgs) cross-referenced with AI agent demand. Foundation of the
   claim-your-page business model.
"""

from alembic import op

revision = "085"
down_revision = "084"

_TIER1_FAMILIES = (
    "'ChatGPT-User'",
    "'Claude-Web'",
    "'Perplexity-User'",
    "'OAI-SearchBot'",
    "'Claude-SearchBot'",
    "'DuckAssistBot'",
    "'Claude-User'",
)


def upgrade() -> None:
    # --- 1. bot_sessions table ---
    op.execute("""
        CREATE TABLE bot_sessions (
            id SERIAL PRIMARY KEY,
            session_date DATE NOT NULL,
            bot_family VARCHAR(30) NOT NULL,
            ip_count SMALLINT NOT NULL DEFAULT 1,
            page_count INT NOT NULL,
            duration_seconds INT,
            primary_domain VARCHAR(50),
            primary_subcategory VARCHAR(100),
            domains TEXT[],
            subcategories TEXT[],
            is_deep_research BOOLEAN NOT NULL DEFAULT false,
            is_comparison BOOLEAN NOT NULL DEFAULT false,
            is_fan_out BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX ix_bot_sessions_date ON bot_sessions (session_date)"
    )
    op.execute(
        "CREATE INDEX ix_bot_sessions_domain ON bot_sessions (primary_domain, session_date)"
    )

    # --- 2. mv_warm_leads MV ---
    tier1_list = ", ".join(_TIER1_FAMILIES)
    op.execute(f"""
        CREATE MATERIALIZED VIEW mv_warm_leads AS
        WITH org_stats AS (
            SELECT
                github_owner,
                COUNT(*) AS repo_count,
                SUM(stars) AS total_stars,
                SUM(forks) AS total_forks,
                ARRAY_AGG(DISTINCT domain) FILTER (WHERE domain <> 'uncategorized') AS domains,
                BOOL_OR(ai_summary IS NOT NULL) AS has_enriched_content
            FROM ai_repos
            GROUP BY github_owner
            HAVING COUNT(*) >= 3
        ),
        demand AS (
            SELECT
                ar.github_owner,
                SUM(bad.hits) AS ai_hits_7d,
                SUM(bad.unique_ips) AS ai_ips_7d,
                COUNT(DISTINCT bad.path) AS pages_hit,
                COUNT(DISTINCT bad.bot_family) AS agent_families
            FROM mv_access_bot_demand bad
            JOIN ai_repos ar ON bad.path LIKE '%/servers/' || ar.full_name || '/%'
            WHERE bad.bot_family IN ({tier1_list})
              AND bad.access_date >= CURRENT_DATE - 7
            GROUP BY ar.github_owner
        )
        SELECT
            o.github_owner,
            o.repo_count,
            o.total_stars,
            o.total_forks,
            o.domains,
            o.has_enriched_content,
            COALESCE(d.ai_hits_7d, 0) AS ai_hits_7d,
            COALESCE(d.ai_ips_7d, 0) AS ai_ips_7d,
            COALESCE(d.pages_hit, 0) AS pages_hit,
            COALESCE(d.agent_families, 0) AS agent_families,
            CASE
                WHEN d.ai_hits_7d IS NOT NULL AND d.ai_hits_7d > 0 THEN 'warm'
                WHEN o.total_stars >= 1000 THEN 'notable'
                ELSE 'cold'
            END AS lead_status
        FROM org_stats o
        LEFT JOIN demand d ON o.github_owner = d.github_owner
        ORDER BY COALESCE(d.ai_hits_7d, 0) DESC, o.total_stars DESC
    """)
    op.execute(
        "CREATE UNIQUE INDEX idx_mv_warm_leads_owner "
        "ON mv_warm_leads (github_owner)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_warm_leads")
    op.execute("DROP TABLE IF EXISTS bot_sessions")
