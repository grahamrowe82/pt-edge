"""Add indexes and commercial materialized views for unified observability.

Revision ID: 091
Revises: 090
Create Date: 2026-04-11

Indexes support the key query patterns: by transport, by caller IP,
by endpoint. Two MVs answer commercial questions: daily rollup and
per-caller profiles for lead identification.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "091"
down_revision: Union[str, None] = "090"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Indexes for common query patterns
    op.create_index("ix_api_usage_transport_created", "api_usage", ["transport", "created_at"])
    op.create_index("ix_api_usage_client_ip_created", "api_usage", ["client_ip", "created_at"])
    op.create_index("ix_api_usage_endpoint_created", "api_usage", ["endpoint", "created_at"])

    # Daily rollup: calls by transport, auth type, endpoint
    op.execute("""
        CREATE MATERIALIZED VIEW mv_api_daily AS
        SELECT
            created_at::date AS day,
            transport,
            CASE WHEN api_key_id IS NOT NULL THEN 'keyed' ELSE 'anonymous' END AS auth_type,
            endpoint,
            COUNT(*) AS calls,
            COUNT(DISTINCT COALESCE(api_key_id::text, client_ip)) AS unique_callers,
            AVG(duration_ms)::int AS avg_duration_ms
        FROM api_usage
        GROUP BY 1, 2, 3, 4
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_api_daily (day, transport, auth_type, endpoint)")

    # Per-caller profiles: who's using the product, how, and how much
    op.execute("""
        CREATE MATERIALIZED VIEW mv_api_callers AS
        SELECT
            COALESCE(api_key_id::text, client_ip) AS caller_id,
            CASE WHEN api_key_id IS NOT NULL THEN 'keyed' ELSE 'anonymous' END AS auth_type,
            api_key_id,
            client_ip,
            MIN(user_agent) AS sample_user_agent,
            MIN(created_at) AS first_seen,
            MAX(created_at) AS last_seen,
            COUNT(*) AS total_calls,
            COUNT(DISTINCT created_at::date) AS active_days,
            COUNT(DISTINCT endpoint) AS distinct_endpoints,
            ARRAY_AGG(DISTINCT transport) AS transports
        FROM api_usage
        GROUP BY 1, 2, 3, 4
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_api_callers (caller_id, auth_type)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_api_callers")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_api_daily")
    op.drop_index("ix_api_usage_endpoint_created")
    op.drop_index("ix_api_usage_client_ip_created")
    op.drop_index("ix_api_usage_transport_created")
