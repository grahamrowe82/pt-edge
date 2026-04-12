"""Domain redirects table for static redirect generation

Revision ID: 092
Revises: 091
Create Date: 2026-04-12

When repos get reclassified to a different domain, the old URL 404s.
This table is an append-only log of "this repo once lived at this domain."
At deploy time, the redirect generator reads this table and writes
static HTML redirect files at each old path.

Backfills ~10K known reclassifications from bot traffic history.
"""

from alembic import op

revision = "092"
down_revision = "091"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE domain_redirects (
            full_name VARCHAR(200) NOT NULL,
            old_domain VARCHAR(50) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (full_name, old_domain)
        )
    """)

    # Backfill: any repo that received bot traffic under a different domain
    op.execute("""
        INSERT INTO domain_redirects (full_name, old_domain)
        SELECT DISTINCT bad.full_name, bad.domain
        FROM mv_access_bot_demand bad
        JOIN ai_repos ar ON bad.full_name = ar.full_name
        WHERE bad.page_type = 'server'
          AND bad.domain != ar.domain
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS domain_redirects")
