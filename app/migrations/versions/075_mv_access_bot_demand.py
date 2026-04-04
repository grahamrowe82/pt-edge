"""Add mv_access_bot_demand materialized view

Revision ID: 075
Revises: 074
Create Date: 2026-04-04

Classifies HTTP access log entries by bot family and aggregates
daily demand signals per path. AI user-action crawlers (ChatGPT-User,
Claude-Web, Perplexity-User) are the primary demand signal — each
request represents a real human asking an AI assistant a question.
"""

from alembic import op

revision = "075"
down_revision = "074"


def upgrade() -> None:
    op.execute("""
        CREATE MATERIALIZED VIEW mv_access_bot_demand AS
        WITH classified AS (
            SELECT
                path,
                status_code,
                client_ip,
                duration_ms,
                created_at,
                created_at::date AS access_date,
                CASE
                    -- AI user-action crawlers (demand signal: human asked an AI)
                    WHEN user_agent ILIKE '%ChatGPT-User%'       THEN 'ChatGPT-User'
                    WHEN user_agent ILIKE '%Claude-Web%'          THEN 'Claude-Web'
                    WHEN user_agent ILIKE '%Perplexity-User%'     THEN 'Perplexity-User'
                    WHEN user_agent ILIKE '%OAI-SearchBot%'       THEN 'OAI-SearchBot'
                    WHEN user_agent ILIKE '%Claude-SearchBot%'    THEN 'Claude-SearchBot'
                    -- AI training crawlers
                    WHEN user_agent ILIKE '%GPTBot%'              THEN 'GPTBot'
                    WHEN user_agent ILIKE '%ClaudeBot%'           THEN 'ClaudeBot'
                    WHEN user_agent ILIKE '%PerplexityBot%'       THEN 'PerplexityBot'
                    WHEN user_agent ILIKE '%Google-Extended%'     THEN 'Google-Extended'
                    WHEN user_agent ILIKE '%Meta-ExternalAgent%'  THEN 'Meta-ExternalAgent'
                    WHEN user_agent ILIKE '%Bytespider%'          THEN 'Bytespider'
                    WHEN user_agent ILIKE '%Amazonbot%'           THEN 'Amazonbot'
                    -- Search engines
                    WHEN user_agent ILIKE '%Googlebot%'           THEN 'Googlebot'
                    WHEN user_agent ILIKE '%Bingbot%'             THEN 'Bingbot'
                    WHEN user_agent ILIKE '%YandexBot%'           THEN 'YandexBot'
                    WHEN user_agent ILIKE '%Applebot%'            THEN 'Applebot'
                    WHEN user_agent ILIKE '%DuckDuckBot%'         THEN 'DuckDuckBot'
                    -- Social / SEO
                    WHEN user_agent ILIKE '%facebookexternalhit%' THEN 'FacebookBot'
                    WHEN user_agent ILIKE '%Twitterbot%'          THEN 'TwitterBot'
                    WHEN user_agent ILIKE '%LinkedInBot%'         THEN 'LinkedInBot'
                    WHEN user_agent ILIKE '%SemrushBot%'          THEN 'SemrushBot'
                    WHEN user_agent ILIKE '%AhrefsBot%'           THEN 'AhrefsBot'
                    -- Catch-all bots
                    WHEN user_agent ILIKE '%bot%'                 THEN 'other_bot'
                    WHEN user_agent ILIKE '%crawler%'             THEN 'other_bot'
                    WHEN user_agent ILIKE '%spider%'              THEN 'other_bot'
                    ELSE 'human'
                END AS bot_family
            FROM http_access_log
        )
        SELECT
            access_date,
            bot_family,
            path,
            COUNT(*) AS hits,
            COUNT(DISTINCT client_ip) AS unique_ips,
            AVG(duration_ms)::int AS avg_duration_ms
        FROM classified
        WHERE bot_family != 'human'
        GROUP BY access_date, bot_family, path
        ORDER BY access_date DESC, hits DESC
    """)

    op.execute("""
        CREATE UNIQUE INDEX ix_mv_access_bot_demand_uniq
            ON mv_access_bot_demand (access_date, bot_family, path)
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_access_bot_demand")
