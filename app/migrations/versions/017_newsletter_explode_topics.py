"""Explode newsletter entries into per-topic rows

Adds topic_index column so one RSS entry can produce multiple rows
(one per distinct topic). Changes the dedup key from entry_url alone
to (entry_url, topic_index).

Existing rows get topic_index=0.

Revision ID: 017
Revises: 016
Create Date: 2026-03-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add topic_index column (0 = single-topic entry or first topic)
    op.execute(
        "ALTER TABLE newsletter_mentions "
        "ADD COLUMN topic_index INTEGER NOT NULL DEFAULT 0"
    )

    # Drop old unique constraint on entry_url alone
    op.execute(
        "ALTER TABLE newsletter_mentions "
        "DROP CONSTRAINT newsletter_mentions_entry_url_key"
    )

    # New composite unique: one row per (entry_url, topic_index)
    op.execute(
        "CREATE UNIQUE INDEX idx_newsletter_entry_topic "
        "ON newsletter_mentions(entry_url, topic_index)"
    )

    # Recreate the metrics view to pick up the new column
    op.execute(
        "CREATE OR REPLACE VIEW metrics.newsletter_mentions "
        "AS SELECT * FROM public.newsletter_mentions"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_newsletter_entry_topic")
    op.execute(
        "DELETE FROM newsletter_mentions WHERE topic_index > 0"
    )
    op.execute(
        "ALTER TABLE newsletter_mentions "
        "ADD CONSTRAINT newsletter_mentions_entry_url_key UNIQUE (entry_url)"
    )
    op.execute(
        "ALTER TABLE newsletter_mentions DROP COLUMN topic_index"
    )
    op.execute(
        "CREATE OR REPLACE VIEW metrics.newsletter_mentions "
        "AS SELECT * FROM public.newsletter_mentions"
    )
