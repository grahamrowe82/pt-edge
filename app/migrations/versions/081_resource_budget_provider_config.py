"""Add provider-aware config, RPM, and backoff to resource_budgets

Revision ID: 081
Revises: 080
Create Date: 2026-04-06

Extends resource_budgets with:
- reset_mode/reset_tz/reset_hour: calendar vs rolling budget windows
- rpm: per-minute rate limit (replaces in-memory settings)
- last_call_at: timestamp of last actual API call
- backoff_until/backoff_count: adaptive exponential backoff state

See docs/strategy/resource-budget-infrastructure.md for full design.
"""

from alembic import op
from typing import Sequence, Union

revision: str = "081"
down_revision: Union[str, None] = "080"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE resource_budgets
          ADD COLUMN reset_mode    text NOT NULL DEFAULT 'rolling',
          ADD COLUMN reset_tz      text NOT NULL DEFAULT 'UTC',
          ADD COLUMN reset_hour    smallint NOT NULL DEFAULT 0,
          ADD COLUMN rpm           int,
          ADD COLUMN last_call_at  timestamptz,
          ADD COLUMN backoff_until timestamptz,
          ADD COLUMN backoff_count smallint NOT NULL DEFAULT 0
    """)

    # Gemini: calendar reset at midnight Pacific, 800 RPM, 10K/day
    op.execute("""
        UPDATE resource_budgets
        SET reset_mode = 'calendar',
            reset_tz = 'America/Los_Angeles',
            reset_hour = 0,
            rpm = 800,
            budget = 10000
        WHERE resource_type = 'gemini'
    """)

    # OpenAI: 400 RPM
    op.execute("""
        UPDATE resource_budgets
        SET rpm = 400
        WHERE resource_type = 'openai'
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE resource_budgets
          DROP COLUMN IF EXISTS reset_mode,
          DROP COLUMN IF EXISTS reset_tz,
          DROP COLUMN IF EXISTS reset_hour,
          DROP COLUMN IF EXISTS rpm,
          DROP COLUMN IF EXISTS last_call_at,
          DROP COLUMN IF EXISTS backoff_until,
          DROP COLUMN IF EXISTS backoff_count
    """)
