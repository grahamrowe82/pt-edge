"""Add vscode_extension_id column to projects.

Revision ID: 035
Revises: 034
Create Date: 2026-03-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "035"
down_revision: Union[str, None] = "034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("vscode_extension_id", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "vscode_extension_id")
