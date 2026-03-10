"""Add pgvector embeddings to releases for semantic search.

Enables searching releases by meaning rather than just project association.

Revision ID: 019
Revises: 018
Create Date: 2026-03-10
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE releases ADD COLUMN embedding vector(1536)")
    op.execute("""
        CREATE INDEX ix_release_embedding_hnsw ON releases
        USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_release_embedding_hnsw")
    op.execute("ALTER TABLE releases DROP COLUMN IF EXISTS embedding")
