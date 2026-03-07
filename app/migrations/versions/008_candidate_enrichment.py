"""Add enrichment columns to project_candidates for pre-computed GitHub data.

Stores repo_created_at, commit_trend, and contributor_count so that MCP
tools (scout, deep_dive) can serve growth metrics without hitting the
GitHub API per-request.

Revision ID: 008
Revises: 007
Create Date: 2026-03-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_candidates",
        sa.Column("repo_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "project_candidates",
        sa.Column("commit_trend", sa.Integer(), nullable=True),
    )
    op.add_column(
        "project_candidates",
        sa.Column("contributor_count", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_candidates", "contributor_count")
    op.drop_column("project_candidates", "commit_trend")
    op.drop_column("project_candidates", "repo_created_at")
