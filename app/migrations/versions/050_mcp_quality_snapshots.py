"""Add mcp_quality_snapshots table for historical score tracking

Revision ID: 050
Revises: 049
Create Date: 2026-03-27

Stores daily snapshots of MCP quality scores so we can track
ecosystem health evolution over time.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "050"
down_revision: Union[str, None] = "049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_quality_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("repo_id", sa.Integer, sa.ForeignKey("ai_repos.id"), nullable=False),
        sa.Column("snapshot_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("quality_score", sa.Integer),
        sa.Column("quality_tier", sa.String(20)),
        sa.Column("maintenance_score", sa.Integer),
        sa.Column("adoption_score", sa.Integer),
        sa.Column("maturity_score", sa.Integer),
        sa.Column("community_score", sa.Integer),
        sa.Column("risk_flags", sa.ARRAY(sa.Text)),
        sa.UniqueConstraint("repo_id", "snapshot_date"),
    )
    op.create_index("idx_mcp_quality_snap_date", "mcp_quality_snapshots", ["snapshot_date"])


def downgrade() -> None:
    op.drop_table("mcp_quality_snapshots")
