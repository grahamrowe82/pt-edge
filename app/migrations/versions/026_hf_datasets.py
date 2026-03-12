"""Add hf_datasets table for HuggingFace Hub dataset index.

Stores dataset metadata from the HF Hub API with 256d embeddings
for semantic search via find_dataset().

Revision ID: 026
Revises: 025
Create Date: 2026-03-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE hf_datasets (
            id SERIAL PRIMARY KEY,
            hf_id VARCHAR(300) NOT NULL UNIQUE,
            pretty_name TEXT,
            description TEXT,
            author VARCHAR(200),
            tags TEXT[] DEFAULT '{}',
            task_categories TEXT[] DEFAULT '{}',
            languages TEXT[] DEFAULT '{}',
            downloads INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ,
            last_modified TIMESTAMPTZ,
            discovered_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            embedding vector(256)
        )
    """)
    op.execute("CREATE INDEX ix_hf_datasets_downloads ON hf_datasets (downloads DESC)")
    op.execute("""
        CREATE INDEX ix_hf_datasets_embedding ON hf_datasets
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_hf_datasets_embedding")
    op.execute("DROP INDEX IF EXISTS ix_hf_datasets_downloads")
    op.execute("DROP TABLE IF EXISTS hf_datasets")
