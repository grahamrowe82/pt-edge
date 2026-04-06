"""Demand Radar: session detection table + owner demand view

Revision ID: 085
Revises: 084
Create Date: 2026-04-06

Two tactical fixes from the Demand Radar research:

1. bot_sessions table — populated daily by worker task that detects
   multi-page AI agent sessions from raw access logs, including
   cross-IP fan-out detection for OAI-SearchBot.

2. mv_owner_demand MV — per-github_owner aggregation of AI agent
   demand signals. Raw facts only (hits, IPs, pages, agent families),
   no business logic or thresholds baked in.
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

    # --- 2. mv_owner_demand MV ---
    # Raw facts: per-owner aggregation of AI agent demand.
    # No thresholds, no labels — just the signal.
    tier1_list = ", ".join(_TIER1_FAMILIES)
    op.execute(f"""
        CREATE MATERIALIZED VIEW mv_owner_demand AS
        SELECT
            ar.github_owner,
            COUNT(DISTINCT ar.id) AS repo_count,
            COALESCE(SUM(ar.stars), 0) AS total_stars,
            ARRAY_AGG(DISTINCT ar.domain) FILTER (WHERE ar.domain <> 'uncategorized') AS domains,
            COALESCE(SUM(bad.hits), 0) AS ai_hits_7d,
            COALESCE(SUM(bad.unique_ips), 0) AS ai_ips_7d,
            COUNT(DISTINCT bad.path) FILTER (WHERE bad.path IS NOT NULL) AS pages_hit,
            COUNT(DISTINCT bad.bot_family) FILTER (WHERE bad.bot_family IS NOT NULL) AS agent_families
        FROM ai_repos ar
        LEFT JOIN mv_access_bot_demand bad
            ON bad.path LIKE '%%/servers/' || ar.full_name || '/%%'
            AND bad.bot_family IN ({tier1_list})
            AND bad.access_date >= CURRENT_DATE - 7
        GROUP BY ar.github_owner
        HAVING COALESCE(SUM(bad.hits), 0) > 0
        ORDER BY COALESCE(SUM(bad.hits), 0) DESC
    """)
    op.execute(
        "CREATE UNIQUE INDEX idx_mv_owner_demand_owner "
        "ON mv_owner_demand (github_owner)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_owner_demand")
    op.execute("DROP TABLE IF EXISTS bot_sessions")
