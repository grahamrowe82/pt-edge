"""Structural cache table for pre-computed relationship data.

Revision ID: 008
Revises: 007
Create Date: 2026-04-11

Simple key-value cache storing pre-computed JSON blobs (relationship
pairs, kill chain pages, etc.) so site generation reads from cache
instead of recomputing at build time.
"""
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS structural_cache (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS structural_cache")
