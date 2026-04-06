"""Set RPM values for all providers in resource_budgets

Revision ID: 082
Revises: 081
Create Date: 2026-04-06

Moves RPM enforcement from hardcoded sleeps to the database.
Values derived from current sleep intervals and API documentation.
"""

from alembic import op
from typing import Sequence, Union

revision: str = "082"
down_revision: Union[str, None] = "081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PyPI: sleep(0.5-1.0) between calls → 120 RPM
    op.execute("UPDATE resource_budgets SET rpm = 120 WHERE resource_type = 'pypi'")
    # npm: sleep(0.3) between calls → 200 RPM
    op.execute("UPDATE resource_budgets SET rpm = 200 WHERE resource_type = 'npm'")
    # HuggingFace: sleep(0.6) = 500 req/300s documented → 100 RPM
    op.execute("UPDATE resource_budgets SET rpm = 100 WHERE resource_type = 'huggingface'")
    # Docker Hub: sleep(0.5) → 120 RPM
    op.execute("UPDATE resource_budgets SET rpm = 120 WHERE resource_type = 'dockerhub'")
    # HN Algolia: sleep(1.0) → 60 RPM
    op.execute("UPDATE resource_budgets SET rpm = 60 WHERE resource_type = 'hn_algolia'")
    # V2EX: sleep(6.0), hard limit 120/hr → 10 RPM
    op.execute("UPDATE resource_budgets SET rpm = 10 WHERE resource_type = 'v2ex'")
    # crates.io: sleep(1.0), documented 1 req/sec → 60 RPM
    op.execute("UPDATE resource_budgets SET rpm = 60 WHERE resource_type = 'crates'")


def downgrade() -> None:
    op.execute("""
        UPDATE resource_budgets SET rpm = NULL
        WHERE resource_type IN ('pypi', 'npm', 'huggingface', 'dockerhub',
                                'hn_algolia', 'v2ex', 'crates')
    """)
