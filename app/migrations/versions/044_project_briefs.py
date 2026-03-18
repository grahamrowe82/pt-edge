"""Add project_briefs and domain_briefs tables for LLM-generated intelligence

Revision ID: 044
Revises: 043
Create Date: 2026-03-18

- project_briefs: per-project LLM-generated narrative briefs
- domain_briefs: per-domain landscape narrative briefs
- generation_hash for staleness detection
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "044"
down_revision: Union[str, None] = "043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_briefs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("evidence", sa.dialects.postgresql.JSONB),
        sa.Column("generation_hash", sa.String(64)),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_project_briefs_project_id", "project_briefs", ["project_id"], unique=True)

    op.create_table(
        "domain_briefs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("domain", sa.String(50), nullable=False, unique=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("evidence", sa.dialects.postgresql.JSONB),
        sa.Column("generation_hash", sa.String(64)),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("domain_briefs")
    op.drop_index("idx_project_briefs_project_id", table_name="project_briefs")
    op.drop_table("project_briefs")
