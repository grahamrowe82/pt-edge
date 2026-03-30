"""Add deep_dives table for curated landscape content

Revision ID: 064
Revises: 062
Create Date: 2026-03-30

Stores hand-curated editorial content with Jinja2 template bodies
that reference live DB metrics at render time.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "064"
down_revision: Union[str, None] = "063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE deep_dives (
            id              SERIAL PRIMARY KEY,
            slug            VARCHAR(100) NOT NULL UNIQUE,
            title           VARCHAR(300) NOT NULL,
            subtitle        VARCHAR(500),
            author          VARCHAR(100) DEFAULT 'Graham Rowe',
            primary_domain  VARCHAR(50) NOT NULL,
            domains         TEXT[] NOT NULL DEFAULT '{}',
            meta_description VARCHAR(300),
            template_body   TEXT NOT NULL,
            featured_repos  TEXT[] NOT NULL DEFAULT '{}',
            featured_categories TEXT[] NOT NULL DEFAULT '{}',
            status          VARCHAR(20) NOT NULL DEFAULT 'draft',
            published_at    TIMESTAMPTZ,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_deep_dives_status ON deep_dives(status)")
    op.execute("CREATE INDEX idx_deep_dives_domain ON deep_dives(primary_domain)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS deep_dives CASCADE")
