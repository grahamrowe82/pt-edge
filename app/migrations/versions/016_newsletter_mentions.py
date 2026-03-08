"""Add newsletter_mentions table for RSS ingest pipeline

Stores newsletter entries with LLM-extracted project/lab mentions,
summaries, and sentiment. Deduplicates on entry_url.
Also creates the metrics.newsletter_mentions thin view for Evidence.dev.

Revision ID: 016
Revises: 015
Create Date: 2026-03-08
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE newsletter_mentions (
            id              SERIAL PRIMARY KEY,
            feed_slug       TEXT NOT NULL,
            entry_url       TEXT NOT NULL UNIQUE,
            title           TEXT NOT NULL,
            published_at    TIMESTAMPTZ,
            summary         TEXT,
            sentiment       TEXT,
            mentions        JSONB DEFAULT '[]'::jsonb,
            raw_content     TEXT,
            ingested_at     TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    op.execute(
        "CREATE INDEX idx_newsletter_feed ON newsletter_mentions(feed_slug)"
    )
    op.execute(
        "CREATE INDEX idx_newsletter_published ON newsletter_mentions(published_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_newsletter_mentions_gin ON newsletter_mentions USING gin(mentions)"
    )

    # Thin view for Evidence.dev / MCP
    op.execute(
        "CREATE OR REPLACE VIEW metrics.newsletter_mentions "
        "AS SELECT * FROM public.newsletter_mentions"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS metrics.newsletter_mentions")
    op.execute("DROP TABLE IF EXISTS newsletter_mentions")
