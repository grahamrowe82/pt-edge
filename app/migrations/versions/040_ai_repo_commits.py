"""Add commits_30d and commits_checked_at to ai_repos for velocity scoring

Revision ID: 040
Revises: 039
Create Date: 2026-03-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "040"
down_revision: Union[str, None] = "039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_repos", sa.Column("commits_30d", sa.Integer(), nullable=True))
    op.add_column("ai_repos", sa.Column("commits_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_ai_repos_commits_checked",
        "ai_repos",
        ["commits_checked_at", "stars"],
        postgresql_nulls_not_distinct=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_repos_commits_checked", table_name="ai_repos")
    op.drop_column("ai_repos", "commits_checked_at")
    op.drop_column("ai_repos", "commits_30d")
