"""Add mcp_servers table for MCP server discovery via GitHub.

Indexes MCP server repos from GitHub Search API with pgvector
embeddings for semantic search via the find_mcp_server() tool.

Revision ID: 020
Revises: 019
Create Date: 2026-03-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE mcp_servers (
            id              SERIAL PRIMARY KEY,
            github_owner    VARCHAR NOT NULL,
            github_repo     VARCHAR NOT NULL,
            full_name       VARCHAR NOT NULL,
            name            VARCHAR NOT NULL,
            description     TEXT,
            stars           INTEGER DEFAULT 0,
            forks           INTEGER DEFAULT 0,
            language        VARCHAR,
            topics          TEXT[],
            license         VARCHAR,
            last_pushed_at  TIMESTAMPTZ,
            archived        BOOLEAN DEFAULT FALSE,
            discovered_at   TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            embedding        vector(1536),
            UNIQUE (github_owner, github_repo)
        )
    """)
    op.execute("""
        CREATE INDEX ix_mcp_servers_embedding_hnsw ON mcp_servers
        USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)
    """)
    op.execute("CREATE INDEX ix_mcp_servers_stars ON mcp_servers (stars DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_mcp_servers_stars")
    op.execute("DROP INDEX IF EXISTS ix_mcp_servers_embedding_hnsw")
    op.execute("DROP TABLE IF EXISTS mcp_servers")
