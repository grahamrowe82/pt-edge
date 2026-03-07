"""Add V2EX posts table and seed Chinese labs

Revision ID: 013
Revises: 012
Create Date: 2026-03-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Seed Chinese labs ---
    op.execute("""
        INSERT INTO labs (name, slug, url, github_org)
        VALUES
            ('DeepSeek', 'deepseek', 'https://deepseek.com', 'deepseek-ai'),
            ('Qwen', 'qwen', 'https://qwen.ai', 'QwenLM'),
            ('Zhipu AI', 'zhipu-ai', 'https://zhipuai.cn', 'THUDM')
        ON CONFLICT (slug) DO NOTHING
    """)

    # --- 2. V2EX posts table ---
    op.create_table(
        "v2ex_posts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("v2ex_id", sa.Integer, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("author", sa.String(100), nullable=False),
        sa.Column("replies", sa.Integer, server_default="0"),
        sa.Column("node_name", sa.String(50), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("lab_id", sa.Integer, sa.ForeignKey("labs.id"), nullable=True),
    )
    op.create_index("ix_v2ex_posts_v2ex_id", "v2ex_posts", ["v2ex_id"], unique=True)
    op.create_index("ix_v2ex_posts_lab_id", "v2ex_posts", ["lab_id"])
    op.create_index("ix_v2ex_posts_posted_at", "v2ex_posts", ["posted_at"])


def downgrade() -> None:
    op.drop_table("v2ex_posts")
    op.execute("DELETE FROM labs WHERE slug IN ('deepseek', 'qwen', 'zhipu-ai')")
