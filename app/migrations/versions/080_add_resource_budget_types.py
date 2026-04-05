"""Add resource budget types for external APIs

Revision ID: 080
Revises: 079
Create Date: 2026-04-05

Adds budget rows for external API groups so that the worker can run
tasks concurrently without overwhelming any single API. Tasks with
the same resource_type are serialised; different resource types run
in parallel.
"""

from alembic import op
from typing import Sequence, Union

revision: str = "080"
down_revision: Union[str, None] = "079"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # External API budget groups — generous limits since these are
    # coarse-grained tasks (one at a time per resource type).
    # The budget prevents concurrent tasks from hammering the same API
    # when the worker runs tasks in parallel.
    op.execute("""
        INSERT INTO resource_budgets (resource_type, period_hours, budget)
        VALUES
            ('pypi', 1, 5000),
            ('npm', 1, 5000),
            ('huggingface', 1, 1000),
            ('dockerhub', 1, 1000),
            ('vscode', 1, 1000),
            ('hn_algolia', 1, 10000),
            ('v2ex', 1, 120),
            ('crates', 1, 3600),
            ('db_only', 24, 999999)
        ON CONFLICT (resource_type) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM resource_budgets
        WHERE resource_type IN (
            'pypi', 'npm', 'huggingface', 'dockerhub', 'vscode',
            'hn_algolia', 'v2ex', 'crates', 'db_only'
        )
    """)
