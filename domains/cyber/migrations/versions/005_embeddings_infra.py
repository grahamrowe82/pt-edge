"""Embeddings infrastructure — budget, indexes, categories.

Revision ID: 005
Revises: 004
Create Date: 2026-04-11

Adds OpenAI resource budget for embedding generation, HNSW indexes for
cosine similarity search, entity_categories table for auto-discovered
clusters, and category columns on entity tables.
"""
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

ENTITY_TABLES = ["cves", "software", "vendors", "weaknesses", "techniques", "attack_patterns"]


def upgrade():
    # OpenAI resource budget for embeddings
    op.execute("""
        INSERT INTO resource_budgets (resource_type, period_hours, budget, rpm)
        VALUES ('openai', 1, 24000, 400)
        ON CONFLICT (resource_type) DO NOTHING
    """)

    # HNSW indexes for cosine similarity search on all entity tables
    for table in ENTITY_TABLES:
        op.execute(f"""
            CREATE INDEX IF NOT EXISTS ix_{table}_embedding_hnsw
            ON {table} USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)

    # Entity categories table for auto-discovered clusters
    op.execute("""
        CREATE TABLE IF NOT EXISTS entity_categories (
            id serial PRIMARY KEY,
            entity_type text NOT NULL,
            level text NOT NULL DEFAULT 'category',
            label text NOT NULL,
            display_label text,
            parent_label text,
            description text,
            centroid text NOT NULL,
            entity_count int DEFAULT 0,
            UNIQUE(entity_type, level, label)
        )
    """)

    # Category column on all entity tables
    for table in ENTITY_TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS category VARCHAR(50)")
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_category "
            f"ON {table} (category) WHERE category IS NOT NULL"
        )


def downgrade():
    for table in reversed(ENTITY_TABLES):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_category")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS category")
    op.execute("DROP TABLE IF EXISTS entity_categories")
    for table in reversed(ENTITY_TABLES):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_embedding_hnsw")
    op.execute("DELETE FROM resource_budgets WHERE resource_type = 'openai'")
