"""Add structural_cache table for weekly cron outputs

Revision ID: 061
Revises: 060
Create Date: 2026-03-29

Stores JSON blobs from weekly structural computations (comparison pairs,
category data, centroids) so the daily deploy reads from cache instead
of recomputing from embeddings.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "061"
down_revision: Union[str, None] = "060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "structural_cache",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("structural_cache")
