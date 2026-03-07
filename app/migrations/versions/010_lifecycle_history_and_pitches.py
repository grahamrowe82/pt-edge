"""Add lifecycle_history table for tracking stage transitions,
and article_pitches table for community article proposals.

Revision ID: 010
Revises: 009
Create Date: 2026-03-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lifecycle_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("lifecycle_stage", sa.String(30), nullable=False),
        sa.Column("snapshot_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.UniqueConstraint("project_id", "snapshot_date"),
    )

    op.create_table(
        "article_pitches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("topic", sa.String(300), nullable=False, index=True),
        sa.Column("thesis", sa.Text, nullable=False),
        sa.Column("evidence", sa.Text, nullable=True),
        sa.Column("audience_angle", sa.Text, nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("upvotes", sa.Integer, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("article_pitches")
    op.drop_table("lifecycle_history")
