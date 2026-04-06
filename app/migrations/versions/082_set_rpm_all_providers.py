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
    # Gemini: official 1000 RPM, 10% headroom
    op.execute("UPDATE resource_budgets SET rpm = 900 WHERE resource_type = 'gemini'")
    # OpenAI: ~500 RPM typical for embeddings tier, conservative guess
    op.execute("UPDATE resource_budgets SET rpm = 400 WHERE resource_type = 'openai'")
    # PyPI: no published limits, conservative
    op.execute("UPDATE resource_budgets SET rpm = 120 WHERE resource_type = 'pypi'")
    # npm: no published limits, conservative
    op.execute("UPDATE resource_budgets SET rpm = 200 WHERE resource_type = 'npm'")
    # HuggingFace: official 1,000 req per 5 min (free user) = 200 RPM, 12K/hr
    op.execute("UPDATE resource_budgets SET rpm = 200, budget = 12000 WHERE resource_type = 'huggingface'")
    # Docker Hub: official 200 pulls per 6 hr (free auth), RPM 30
    op.execute("UPDATE resource_budgets SET rpm = 30, budget = 200, period_hours = 6 WHERE resource_type = 'dockerhub'")
    # HN Algolia: no published limits, conservative
    op.execute("UPDATE resource_budgets SET rpm = 60 WHERE resource_type = 'hn_algolia'")
    # V2EX: official 120/hr confirmed via X-Rate-Limit-Limit header
    op.execute("UPDATE resource_budgets SET rpm = 10 WHERE resource_type = 'v2ex'")
    # crates.io: convention 1 req/sec, no published hard limit
    op.execute("UPDATE resource_budgets SET rpm = 60 WHERE resource_type = 'crates'")


def downgrade() -> None:
    op.execute("""
        UPDATE resource_budgets SET rpm = NULL
        WHERE resource_type IN ('pypi', 'npm', 'huggingface', 'dockerhub',
                                'hn_algolia', 'v2ex', 'crates')
    """)
