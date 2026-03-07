"""Add methodology table for deep documentation of tools and algorithms.

Stores rich explanations of how each tool works — algorithms, thresholds,
design decisions — so users can query, critique, and suggest improvements.

Revision ID: 006
Revises: 005
Create Date: 2026-03-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "methodology",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic", sa.String(100), nullable=False, unique=True),
        sa.Column("category", sa.String(50), nullable=False),   # tool, metric, algorithm, design
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),         # 1-2 sentence overview
        sa.Column("detail", sa.Text(), nullable=False),          # full markdown explanation
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("methodology")
