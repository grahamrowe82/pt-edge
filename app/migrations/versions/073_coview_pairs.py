"""Add coview_pairs table for session-based recommendations

Revision ID: 073
Revises: 072
Create Date: 2026-04-04

Stores co-view pairs extracted from Umami session data.
When two project pages are viewed in the same synthetic session,
the pair is recorded here. Used for "people also viewed" recommendations.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "073"
down_revision: Union[str, None] = "072"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS coview_pairs (
            id SERIAL PRIMARY KEY,
            full_name_a VARCHAR(200) NOT NULL,
            full_name_b VARCHAR(200) NOT NULL,
            domain VARCHAR(50),
            coview_count INT DEFAULT 1,
            first_seen_at TIMESTAMPTZ DEFAULT NOW(),
            last_seen_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (full_name_a, full_name_b)
        );
        CREATE INDEX IF NOT EXISTS idx_coview_a ON coview_pairs (full_name_a);
        CREATE INDEX IF NOT EXISTS idx_coview_b ON coview_pairs (full_name_b);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS coview_pairs;")
