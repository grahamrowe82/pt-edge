"""Add feedback category, HN lab linkage, frontier models, and lab events

Revision ID: 012
Revises: 011
Create Date: 2026-03-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Feedback category on corrections ---
    op.add_column("corrections", sa.Column(
        "category", sa.String(20), nullable=False, server_default="bug",
    ))

    # --- 2. HN→lab linkage ---
    op.add_column("hn_posts", sa.Column(
        "lab_id", sa.Integer, sa.ForeignKey("labs.id"), nullable=True,
    ))
    op.create_index("ix_hn_posts_lab_id", "hn_posts", ["lab_id"])

    # --- 3. Frontier models table ---
    op.create_table(
        "frontier_models",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lab_id", sa.Integer, sa.ForeignKey("labs.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), unique=True, nullable=False),
        sa.Column("openrouter_id", sa.String(200), unique=True, nullable=True),
        sa.Column("context_window", sa.Integer, nullable=True),
        sa.Column("max_completion_tokens", sa.Integer, nullable=True),
        sa.Column("pricing_input", sa.String(50), nullable=True),
        sa.Column("pricing_output", sa.String(50), nullable=True),
        sa.Column("modality", sa.String(100), nullable=True),
        sa.Column("capabilities", postgresql.JSONB, nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_frontier_models_lab_id", "frontier_models", ["lab_id"])

    # --- 4. Lab events table ---
    op.create_table(
        "lab_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("lab_id", sa.Integer, sa.ForeignKey("labs.id"), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("source_hn_id", sa.Integer, nullable=True),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_lab_events_lab_id", "lab_events", ["lab_id"])
    op.create_index("ix_lab_events_event_date", "lab_events", ["event_date"])


def downgrade() -> None:
    op.drop_table("lab_events")
    op.drop_table("frontier_models")
    op.drop_index("ix_hn_posts_lab_id", "hn_posts")
    op.drop_column("hn_posts", "lab_id")
    op.drop_column("corrections", "category")
