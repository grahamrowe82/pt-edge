"""Add llm_reviewed_at to hn_posts to prevent reprocessing unmatched posts

Revision ID: 046
Revises: 045
Create Date: 2026-03-26

Posts where LLM returns no match were never marked, causing ~1,900 posts
to be re-sent to Haiku every day (~600K wasted tokens/day).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "046"
down_revision: Union[str, None] = "045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hn_posts", sa.Column("llm_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "CREATE INDEX ix_hn_posts_llm_reviewed_at ON hn_posts (llm_reviewed_at) "
        "WHERE llm_reviewed_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_hn_posts_llm_reviewed_at", table_name="hn_posts")
    op.drop_column("hn_posts", "llm_reviewed_at")
