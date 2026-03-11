"""Evolve mcp_servers into ai_repos.

Adds domain column, renames table, rebuilds embedding column at 256d
to fit within 250MB RAM constraint on Render.

Revision ID: 021
Revises: 020
Create Date: 2026-03-11
"""
from typing import Sequence, Union

from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add domain column — existing rows default to 'mcp'
    op.execute(
        "ALTER TABLE mcp_servers ADD COLUMN domain VARCHAR(50) NOT NULL DEFAULT 'mcp'"
    )

    # Drop old 1536d embedding column and its HNSW index
    op.execute("DROP INDEX IF EXISTS ix_mcp_servers_embedding_hnsw")
    op.execute("ALTER TABLE mcp_servers DROP COLUMN embedding")

    # Add new 256d embedding column
    op.execute("ALTER TABLE mcp_servers ADD COLUMN embedding vector(256)")

    # Rename table and existing star index
    op.execute("ALTER TABLE mcp_servers RENAME TO ai_repos")
    op.execute("ALTER INDEX ix_mcp_servers_stars RENAME TO ix_ai_repos_stars")

    # New indexes
    op.execute("""
        CREATE INDEX ix_ai_repos_embedding_hnsw ON ai_repos
        USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)
    """)
    op.execute("CREATE INDEX ix_ai_repos_domain ON ai_repos (domain)")
    op.execute(
        "CREATE INDEX ix_ai_repos_domain_stars ON ai_repos (domain, stars DESC)"
    )


def downgrade() -> None:
    # Reverse: drop new indexes, rename back, restore 1536d column
    op.execute("DROP INDEX IF EXISTS ix_ai_repos_domain_stars")
    op.execute("DROP INDEX IF EXISTS ix_ai_repos_domain")
    op.execute("DROP INDEX IF EXISTS ix_ai_repos_embedding_hnsw")

    op.execute("ALTER TABLE ai_repos RENAME TO mcp_servers")
    op.execute("ALTER INDEX ix_ai_repos_stars RENAME TO ix_mcp_servers_stars")

    op.execute("ALTER TABLE mcp_servers DROP COLUMN embedding")
    op.execute("ALTER TABLE mcp_servers ADD COLUMN embedding vector(1536)")
    op.execute("""
        CREATE INDEX ix_mcp_servers_embedding_hnsw ON mcp_servers
        USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)
    """)

    op.execute("ALTER TABLE mcp_servers DROP COLUMN domain")
