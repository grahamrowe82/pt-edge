"""Add comparison_sentences table for X vs Y pages

Revision ID: 060
Revises: 059
Create Date: 2026-03-29

Stores Haiku-generated decision sentences for comparison pages.
Placeholder rows (NULL sentence) are created during site generation;
the backfill fills them in at 2,000/day.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "060"
down_revision: Union[str, None] = "059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "comparison_sentences",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("repo_a_id", sa.Integer, sa.ForeignKey("ai_repos.id"), nullable=False),
        sa.Column("repo_b_id", sa.Integer, sa.ForeignKey("ai_repos.id"), nullable=False),
        sa.Column("domain", sa.String(50), nullable=False),
        sa.Column("subcategory", sa.String(50)),
        sa.Column("sentence", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("repo_a_id", "repo_b_id"),
    )


def downgrade() -> None:
    op.drop_table("comparison_sentences")
