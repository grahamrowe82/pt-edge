"""Add velocity tracking columns to project_candidates.

Enables tracking star count changes between ingest cycles so that
radar() can surface candidates that are exploding in popularity.

Revision ID: 005
Revises: 004
Create Date: 2026-03-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("project_candidates", sa.Column("stars_previous", sa.Integer(), nullable=True))
    op.add_column(
        "project_candidates",
        sa.Column("stars_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_candidates", "stars_updated_at")
    op.drop_column("project_candidates", "stars_previous")
