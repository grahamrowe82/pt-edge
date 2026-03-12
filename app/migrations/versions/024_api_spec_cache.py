"""Cache OpenAPI specs on public_apis table.

Adds spec_json (JSONB), spec_fetched_at, and spec_error columns
to support the spec-to-scaffold bridge.

Revision ID: 024
Revises: 023
Create Date: 2026-03-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE public_apis ADD COLUMN spec_json JSONB")
    op.execute("ALTER TABLE public_apis ADD COLUMN spec_fetched_at TIMESTAMPTZ")
    op.execute("ALTER TABLE public_apis ADD COLUMN spec_error VARCHAR(500)")
    op.execute("""
        CREATE INDEX ix_public_apis_spec_pending
        ON public_apis (spec_fetched_at NULLS FIRST)
        WHERE spec_url IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_public_apis_spec_pending")
    op.execute("ALTER TABLE public_apis DROP COLUMN IF EXISTS spec_error")
    op.execute("ALTER TABLE public_apis DROP COLUMN IF EXISTS spec_fetched_at")
    op.execute("ALTER TABLE public_apis DROP COLUMN IF EXISTS spec_json")
