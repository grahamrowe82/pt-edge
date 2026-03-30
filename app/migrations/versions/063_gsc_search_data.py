"""Add Google Search Console data tables

Revision ID: 063
Revises: 062
Create Date: 2026-03-30

Stores daily GSC search analytics: queries, pages, clicks,
impressions, CTR, and position. Granularity is per-query-per-page-per-date
so we can slice any way we need.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "063"
down_revision: Union[str, None] = "062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gsc_search_data",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("search_date", sa.Date, nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("page", sa.Text, nullable=False),
        sa.Column("clicks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ctr", sa.Float, nullable=False, server_default="0"),
        sa.Column("position", sa.Float, nullable=False, server_default="0"),
        sa.Column("device", sa.String(20)),
        sa.Column("country", sa.String(3)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("search_date", "query", "page", name="uq_gsc_date_query_page"),
    )
    op.execute("CREATE INDEX idx_gsc_search_date ON gsc_search_data (search_date)")
    op.execute("CREATE INDEX idx_gsc_query ON gsc_search_data (query)")
    op.execute("CREATE INDEX idx_gsc_page ON gsc_search_data (page)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS gsc_search_data CASCADE")
