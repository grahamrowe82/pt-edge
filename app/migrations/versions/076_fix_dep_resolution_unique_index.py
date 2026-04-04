"""Fix mv_dep_resolution unique index for CONCURRENTLY refresh

Revision ID: 076
Revises: 075
Create Date: 2026-04-04

Migration 072 created a UNIQUE INDEX on (dep_name, source) but the DB
has a non-unique index — likely because duplicate (dep_name, source)
pairs exist when one package name maps to multiple repos. REFRESH
MATERIALIZED VIEW CONCURRENTLY requires a unique index. Fix by
recreating on (dep_name, source, repo_id) which is guaranteed unique.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "076"
down_revision: Union[str, None] = "075"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_mv_dep_resolution_dep_source")
    op.execute("""
        CREATE UNIQUE INDEX ix_mv_dep_resolution_uniq
        ON mv_dep_resolution (dep_name, source, repo_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_mv_dep_resolution_uniq")
    op.execute("""
        CREATE INDEX ix_mv_dep_resolution_dep_source
        ON mv_dep_resolution (dep_name, source)
    """)
