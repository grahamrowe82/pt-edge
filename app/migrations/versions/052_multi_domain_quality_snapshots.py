"""Add generic quality_snapshots table for multi-domain historical tracking

Revision ID: 052
Revises: 051
Create Date: 2026-03-28

Stores daily quality snapshots for agents, rag, ai-coding domains.
MCP continues using its own mcp_quality_snapshots table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "052"
down_revision: Union[str, None] = "051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quality_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("repo_id", sa.Integer, sa.ForeignKey("ai_repos.id"), nullable=False),
        sa.Column("domain", sa.String(30), nullable=False),
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
    op.create_index("idx_quality_snap_domain_date", "quality_snapshots", ["domain", "snapshot_date"])


def downgrade() -> None:
    op.drop_table("quality_snapshots")
