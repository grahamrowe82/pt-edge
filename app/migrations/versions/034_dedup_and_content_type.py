"""Add unique constraint on projects(github_owner, github_repo) and content_type to ai_repos.

Revision ID: 034
Revises: 033
Create Date: 2026-03-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "034"
down_revision: Union[str, None] = "033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add content_type column to ai_repos (tool, tutorial, awesome-list, model, dataset, course)
    op.execute(
        "ALTER TABLE ai_repos ADD COLUMN content_type VARCHAR(20) NOT NULL DEFAULT 'tool'"
    )

    # Populate content_type with heuristics
    op.execute("""
        UPDATE ai_repos SET content_type = 'awesome-list'
        WHERE LOWER(name) LIKE 'awesome-%' OR LOWER(full_name) LIKE '%/awesome-%'
    """)
    op.execute("""
        UPDATE ai_repos SET content_type = 'tutorial'
        WHERE content_type = 'tool'
          AND (topics @> ARRAY['tutorial'] OR topics @> ARRAY['examples']
               OR LOWER(name) LIKE '%tutorial%' OR LOWER(name) LIKE '%examples%')
    """)
    op.execute("""
        UPDATE ai_repos SET content_type = 'course'
        WHERE content_type = 'tool'
          AND (topics @> ARRAY['course'] OR topics @> ARRAY['courses']
               OR LOWER(name) LIKE '%course%')
    """)

    op.create_index("ix_ai_repos_content_type", "ai_repos", ["content_type"])

    # Add unique constraint on projects(github_owner, github_repo) — partial, only non-null
    op.execute("""
        CREATE UNIQUE INDEX uq_projects_github_owner_repo
        ON projects (github_owner, github_repo)
        WHERE github_owner IS NOT NULL AND github_repo IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_projects_github_owner_repo")
    op.execute("DROP INDEX IF EXISTS ix_ai_repos_content_type")
    op.execute("ALTER TABLE ai_repos DROP COLUMN content_type")
