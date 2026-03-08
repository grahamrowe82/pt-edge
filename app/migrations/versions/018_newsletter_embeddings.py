"""Add pgvector embeddings to newsletter_mentions for semantic search.

Enables topic() to find relevant newsletter coverage via cosine similarity.

Revision ID: 018
Revises: 017
Create Date: 2026-03-08
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE newsletter_mentions ADD COLUMN embedding vector(1536)")
    op.execute("""
        CREATE INDEX ix_newsletter_embedding_hnsw ON newsletter_mentions
        USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_newsletter_embedding_hnsw")
    op.execute("ALTER TABLE newsletter_mentions DROP COLUMN IF EXISTS embedding")
