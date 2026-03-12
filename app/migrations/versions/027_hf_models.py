"""Add hf_models table for HuggingFace Hub model index.

Stores model metadata from the HF Hub API with 256d embeddings
for semantic search via find_model().

Revision ID: 027
Revises: 026
Create Date: 2026-03-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE hf_models (
            id SERIAL PRIMARY KEY,
            hf_id VARCHAR(300) NOT NULL UNIQUE,
            pretty_name TEXT,
            description TEXT,
            author VARCHAR(200),
            tags TEXT[] DEFAULT '{}',
            pipeline_tag VARCHAR(100),
            library_name VARCHAR(100),
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
    op.execute("CREATE INDEX ix_hf_models_downloads ON hf_models (downloads DESC)")
    op.execute("CREATE INDEX ix_hf_models_pipeline_tag ON hf_models (pipeline_tag)")
    op.execute("""
        CREATE INDEX ix_hf_models_embedding ON hf_models
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_hf_models_embedding")
    op.execute("DROP INDEX IF EXISTS ix_hf_models_pipeline_tag")
    op.execute("DROP INDEX IF EXISTS ix_hf_models_downloads")
    op.execute("DROP TABLE IF EXISTS hf_models")
