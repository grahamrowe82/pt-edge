"""Add public_apis table for APIs.guru directory.

Indexes ~2,500 REST APIs with 256d embeddings for semantic search
via find_public_api().

Revision ID: 023
Revises: 022
Create Date: 2026-03-11
"""
from typing import Sequence, Union

from alembic import op

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE public_apis (
            id SERIAL PRIMARY KEY,
            provider VARCHAR NOT NULL,
            service_name VARCHAR NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            description TEXT,
            categories TEXT[],
            openapi_version VARCHAR(20),
            spec_url TEXT,
            logo_url TEXT,
            contact_url TEXT,
            api_version VARCHAR(50),
            added_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ,
            discovered_at TIMESTAMPTZ DEFAULT NOW(),
            embedding vector(256),
            UNIQUE (provider, service_name)
        )
    """)
    op.execute("""
        CREATE INDEX ix_public_apis_embedding_hnsw ON public_apis
        USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)
    """)
    op.execute("""
        CREATE INDEX ix_public_apis_categories ON public_apis USING gin (categories)
    """)
    op.execute("""
        CREATE INDEX ix_public_apis_provider ON public_apis (provider)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_public_apis_provider")
    op.execute("DROP INDEX IF EXISTS ix_public_apis_categories")
    op.execute("DROP INDEX IF EXISTS ix_public_apis_embedding_hnsw")
    op.execute("DROP TABLE IF EXISTS public_apis")
