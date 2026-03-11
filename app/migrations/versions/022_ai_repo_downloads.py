"""Add package download columns to ai_repos.

Enables auto-detection of PyPI/npm packages and monthly download
tracking for search ranking in find_ai_tool().

Revision ID: 022
Revises: 021
Create Date: 2026-03-11
"""
from typing import Sequence, Union

from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE ai_repos ADD COLUMN pypi_package VARCHAR(200)")
    op.execute("ALTER TABLE ai_repos ADD COLUMN npm_package VARCHAR(200)")
    op.execute("ALTER TABLE ai_repos ADD COLUMN downloads_monthly BIGINT DEFAULT 0")
    op.execute("ALTER TABLE ai_repos ADD COLUMN downloads_checked_at TIMESTAMPTZ")
    op.execute("""
        CREATE INDEX ix_ai_repos_downloads_checked
        ON ai_repos (downloads_checked_at NULLS FIRST, stars DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ai_repos_downloads_checked")
    op.execute("ALTER TABLE ai_repos DROP COLUMN IF EXISTS downloads_checked_at")
    op.execute("ALTER TABLE ai_repos DROP COLUMN IF EXISTS downloads_monthly")
    op.execute("ALTER TABLE ai_repos DROP COLUMN IF EXISTS npm_package")
    op.execute("ALTER TABLE ai_repos DROP COLUMN IF EXISTS pypi_package")
