"""Add 1536d embedding column, category column, and category centroids table

Revision ID: 056
Revises: 055
Create Date: 2026-03-28

- embedding_1536: full-resolution embeddings for clustering/analytics (no HNSW index)
- category: broad category label (5-10 per domain, assigned via k-means clustering)
- category_centroids: stores cluster centroids for ongoing classification of new repos
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "056"
down_revision: Union[str, None] = "055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE ai_repos ADD COLUMN embedding_1536 vector(1536)")
    op.add_column("ai_repos", sa.Column("category", sa.String(50)))

    op.create_table(
        "category_centroids",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("domain", sa.String(50), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),  # 'category' or 'subcategory'
        sa.Column("label", sa.String(50), nullable=False),
        sa.Column("parent_label", sa.String(50)),  # NULL for categories
        sa.Column("description", sa.Text),
        sa.Column("repo_count", sa.Integer),
        sa.UniqueConstraint("domain", "level", "label"),
    )
    # Store centroids as text (not vector) — only used in batch Python, not pgvector queries
    op.add_column("category_centroids", sa.Column("centroid", sa.Text, nullable=False))


def downgrade() -> None:
    op.drop_table("category_centroids")
    op.drop_column("ai_repos", "category")
    op.execute("ALTER TABLE ai_repos DROP COLUMN IF EXISTS embedding_1536")
