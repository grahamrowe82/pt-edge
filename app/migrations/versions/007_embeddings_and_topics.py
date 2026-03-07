"""Add pgvector embeddings and GitHub topics for semantic search.

Enables semantic project discovery via vector similarity search.
GitHub topics captured from API give each project a structured fingerprint.

Revision ID: 007
Revises: 006
Create Date: 2026-03-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # GitHub topics — structured tags from the API
    op.add_column("projects", sa.Column("topics", sa.ARRAY(sa.Text()), nullable=True))
    op.add_column("project_candidates", sa.Column("topics", sa.ARRAY(sa.Text()), nullable=True))

    # Embeddings — 1536 dims = OpenAI text-embedding-3-small
    op.execute("ALTER TABLE projects ADD COLUMN embedding vector(1536)")
    op.execute("ALTER TABLE methodology ADD COLUMN embedding vector(1536)")

    # HNSW indexes — work on empty tables, no training phase needed
    op.execute("""
        CREATE INDEX ix_projects_embedding_hnsw ON projects
        USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)
    """)
    op.execute("""
        CREATE INDEX ix_methodology_embedding_hnsw ON methodology
        USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_methodology_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_projects_embedding_hnsw")
    op.execute("ALTER TABLE methodology DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS embedding")
    op.drop_column("project_candidates", "topics")
    op.drop_column("projects", "topics")
