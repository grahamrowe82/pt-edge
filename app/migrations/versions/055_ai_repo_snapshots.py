"""Add ai_repo_snapshots table for daily metric history

Revision ID: 055
Revises: 054
Create Date: 2026-03-28

Stores daily snapshots of stars, forks, downloads, and commits for all
ai_repos. One row per repo per day. Core historical IP — enables trend
analysis, sparklines, and growth classification.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "055"
down_revision: Union[str, None] = "054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_repo_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("repo_id", sa.Integer, sa.ForeignKey("ai_repos.id"), nullable=False),
        sa.Column("snapshot_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("stars", sa.Integer),
        sa.Column("forks", sa.Integer),
        sa.Column("downloads_monthly", sa.BigInteger),
        sa.Column("commits_30d", sa.Integer),
        sa.UniqueConstraint("repo_id", "snapshot_date"),
    )
    op.create_index("idx_ai_repo_snap_date", "ai_repo_snapshots", ["snapshot_date"])


def downgrade() -> None:
    op.drop_table("ai_repo_snapshots")
