"""Add briefings table for curated ecosystem intelligence.

Stores distilled editorial findings backed by evidence — interpretive
conclusions that persist across sessions so users don't have to re-derive
structural patterns from raw data.

Revision ID: 031
Revises: 030
Create Date: 2026-03-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "031"
down_revision: Union[str, None] = "030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "briefings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("domain", sa.String(50), nullable=False),          # mcp, agents, rag, etc.
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),              # 1-2 sentence distillation
        sa.Column("detail", sa.Text(), nullable=False),               # full markdown finding
        sa.Column("evidence", sa.dialects.postgresql.JSONB()),        # structured data anchors
        sa.Column("source_article", sa.String(100)),                  # e.g. "07-the-8-layers..."
        sa.Column("verified_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_briefings_domain", "briefings", ["domain"])
    # Embedding column added separately (pgvector type)
    op.execute("ALTER TABLE briefings ADD COLUMN embedding vector(1536)")


def downgrade() -> None:
    op.drop_table("briefings")
