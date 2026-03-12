"""Add materialized views for usage analytics.

mv_usage_sessions: groups tool_usage rows into sessions (10-min gap).
mv_usage_daily_summary: daily rollup of calls, unique IPs, bot vs real.
"""
from typing import Union

from alembic import op

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- mv_usage_sessions ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_usage_sessions AS
WITH ordered AS (
    SELECT
        id,
        tool_name,
        client_ip,
        user_agent,
        created_at,
        LAG(created_at) OVER (PARTITION BY COALESCE(client_ip, 'unknown') ORDER BY created_at) AS prev_at
    FROM tool_usage
),
session_starts AS (
    SELECT
        *,
        CASE
            WHEN prev_at IS NULL
                 OR created_at - prev_at > INTERVAL '10 minutes'
            THEN 1
            ELSE 0
        END AS is_new_session
    FROM ordered
),
session_ids AS (
    SELECT
        *,
        SUM(is_new_session) OVER (
            PARTITION BY COALESCE(client_ip, 'unknown')
            ORDER BY created_at
        ) AS session_num
    FROM session_starts
)
SELECT
    COALESCE(client_ip, 'unknown') AS client_ip,
    session_num,
    MIN(user_agent) AS user_agent,
    MIN(created_at) AS started_at,
    MAX(created_at) AS ended_at,
    EXTRACT(EPOCH FROM MAX(created_at) - MIN(created_at))::int AS duration_secs,
    COUNT(*) AS tool_calls,
    COUNT(DISTINCT tool_name) AS distinct_tools,
    ARRAY_AGG(DISTINCT tool_name ORDER BY tool_name) AS tools_used,
    CASE
        WHEN MIN(user_agent) ILIKE '%glama%' THEN true
        WHEN MIN(user_agent) ILIKE '%bot%' THEN true
        WHEN MIN(user_agent) ILIKE '%health%' THEN true
        WHEN COUNT(DISTINCT tool_name) <= 2
             AND COUNT(*) >= 3
             AND EXTRACT(EPOCH FROM MAX(created_at) - MIN(created_at)) < 10
        THEN true
        ELSE false
    END AS is_bot,
    MIN(created_at)::date AS session_date
FROM session_ids
GROUP BY COALESCE(client_ip, 'unknown'), session_num
""")
    op.execute("""
CREATE UNIQUE INDEX ix_mv_usage_sessions_uniq
    ON mv_usage_sessions (client_ip, session_num)
""")

    # --- mv_usage_daily_summary ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_usage_daily_summary AS
WITH sessions AS (
    SELECT * FROM mv_usage_sessions
)
SELECT
    session_date AS day,
    COUNT(*) AS total_sessions,
    COUNT(*) FILTER (WHERE NOT is_bot) AS real_sessions,
    COUNT(*) FILTER (WHERE is_bot) AS bot_sessions,
    COUNT(DISTINCT client_ip) AS unique_ips,
    COUNT(DISTINCT client_ip) FILTER (WHERE NOT is_bot) AS unique_real_ips,
    SUM(tool_calls) AS total_tool_calls,
    SUM(tool_calls) FILTER (WHERE NOT is_bot) AS real_tool_calls
FROM sessions
GROUP BY session_date
ORDER BY session_date DESC
""")
    op.execute("""
CREATE UNIQUE INDEX ix_mv_usage_daily_summary_day
    ON mv_usage_daily_summary (day)
""")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_usage_daily_summary")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_usage_sessions")
