"""Drop UNIQUE on vendors.slug — derived value should not constrain natural key.

Revision ID: 009
Revises: 008
Create Date: 2026-04-12

The slug is derived from cpe_vendor (the real unique key). Two different
cpe_vendor values can produce the same slug (e.g. network_associates and
network-associates both → network-associates), which breaks the NVD ingest.
"""
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE vendors DROP CONSTRAINT IF EXISTS vendors_slug_key")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_vendors_slug
        ON vendors (slug)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_vendors_slug")
    op.execute("""
        ALTER TABLE vendors ADD CONSTRAINT vendors_slug_key UNIQUE (slug)
    """)
