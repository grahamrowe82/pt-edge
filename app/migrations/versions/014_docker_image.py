"""Add docker_image column to projects for Docker Hub pull tracking

Revision ID: 014
Revises: 013
Create Date: 2026-03-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("docker_image", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "docker_image")
