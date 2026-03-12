"""Add package_deps table and dependency columns on ai_repos.

Stores direct dependencies for repos with detected PyPI/npm packages.
Enables dependency graph queries: get_dependencies() and find_dependents().

Revision ID: 025
Revises: 024
Create Date: 2026-03-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE package_deps (
            id SERIAL PRIMARY KEY,
            repo_id INTEGER NOT NULL REFERENCES ai_repos(id) ON DELETE CASCADE,
            dep_name VARCHAR(200) NOT NULL,
            dep_spec VARCHAR(200),
            source VARCHAR(10) NOT NULL CHECK (source IN ('pypi', 'npm')),
            is_dev BOOLEAN NOT NULL DEFAULT false,
            fetched_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (repo_id, dep_name, source)
        )
    """)
    op.execute("CREATE INDEX ix_package_deps_dep_name ON package_deps (dep_name)")
    op.execute("CREATE INDEX ix_package_deps_repo_id ON package_deps (repo_id)")
    op.execute("ALTER TABLE ai_repos ADD COLUMN dependency_count INTEGER DEFAULT 0")
    op.execute("ALTER TABLE ai_repos ADD COLUMN deps_fetched_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE ai_repos DROP COLUMN IF EXISTS deps_fetched_at")
    op.execute("ALTER TABLE ai_repos DROP COLUMN IF EXISTS dependency_count")
    op.execute("DROP INDEX IF EXISTS ix_package_deps_repo_id")
    op.execute("DROP INDEX IF EXISTS ix_package_deps_dep_name")
    op.execute("DROP TABLE IF EXISTS package_deps")
