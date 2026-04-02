"""Normalize package names + create mv_dep_resolution

Revision ID: 072
Revises: 071
Create Date: 2026-04-02

1. Normalize ai_repos.pypi_package to lowercase-with-hyphens (matching
   package_deps.dep_name convention) so JOINs resolve correctly.
2. Reset downloads_checked_at for high-star repos with no detected packages,
   allowing the improved detection pipeline to re-check them.
3. Create mv_dep_resolution materialized view mapping dep_name → repo_id.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "072"
down_revision: Union[str, None] = "071"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Normalize existing pypi_package values
    op.execute("""
        UPDATE ai_repos
        SET pypi_package = LOWER(REPLACE(pypi_package, '_', '-'))
        WHERE pypi_package IS NOT NULL
          AND pypi_package <> LOWER(REPLACE(pypi_package, '_', '-'))
    """)

    # 2. Reset detection for high-star repos with no packages found
    #    so the syntactic + LLM pipeline can re-check them
    op.execute("""
        UPDATE ai_repos
        SET downloads_checked_at = NULL
        WHERE pypi_package IS NULL
          AND npm_package IS NULL
          AND crate_package IS NULL
          AND stars >= 20
          AND downloads_checked_at < NOW() - INTERVAL '30 days'
    """)

    # 3. Create dep resolution materialized view
    op.execute("""
        CREATE MATERIALIZED VIEW mv_dep_resolution AS
        SELECT DISTINCT pd.dep_name, pd.source, ar.id AS repo_id, ar.full_name
        FROM package_deps pd
        JOIN ai_repos ar ON (
            (pd.source = 'pypi' AND pd.dep_name = ar.pypi_package)
            OR (pd.source = 'npm' AND pd.dep_name = ar.npm_package)
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX ix_mv_dep_resolution_dep_source
        ON mv_dep_resolution (dep_name, source)
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_dep_resolution")
    # Normalization and reset are not reversible but are idempotent
