"""Add task queue, resource budgets, and raw cache tables

Revision ID: 079
Revises: 078
Create Date: 2026-04-05

Foundation for the database-driven work queue architecture.
See docs/design/worker-architecture.md for full design.

Three tables:
- tasks: work queue with priority, state, resource tracking
- resource_budgets: per-resource-type budget tracking (GitHub, Gemini, etc.)
- raw_cache: cached raw API responses (interface between fetch and enrich tasks)
"""

from alembic import op
from typing import Sequence, Union

revision: str = "079"
down_revision: Union[str, None] = "078"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- tasks table --
    op.execute("""
        CREATE TABLE tasks (
            id              bigserial PRIMARY KEY,
            task_type       text NOT NULL,
            subject_id      text,
            priority        smallint NOT NULL DEFAULT 5,
            state           text NOT NULL DEFAULT 'pending',
            resource_type   text,
            estimated_cost_usd numeric(10,6),
            claimed_by      text,
            claimed_at      timestamptz,
            heartbeat_at    timestamptz,
            completed_at    timestamptz,
            result          jsonb,
            error_message   text,
            retry_count     smallint NOT NULL DEFAULT 0,
            max_retries     smallint NOT NULL DEFAULT 3,
            created_at      timestamptz NOT NULL DEFAULT now()
        )
    """)

    # Claim query index: find highest-priority pending task fast
    op.execute("""
        CREATE INDEX idx_tasks_claimable
        ON tasks (priority DESC, created_at ASC)
        WHERE state = 'pending'
    """)

    # Lookup by type + subject
    op.execute("""
        CREATE INDEX idx_tasks_type_subject
        ON tasks (task_type, subject_id)
    """)

    # Active tasks (pending or claimed) for monitoring
    op.execute("""
        CREATE INDEX idx_tasks_state
        ON tasks (state)
        WHERE state IN ('claimed', 'pending')
    """)

    # Dedup: prevent scheduler from creating duplicate tasks
    op.execute("""
        CREATE UNIQUE INDEX idx_tasks_dedup
        ON tasks (task_type, subject_id)
        WHERE state IN ('pending', 'claimed')
    """)

    # -- resource_budgets table --
    op.execute("""
        CREATE TABLE resource_budgets (
            resource_type   text PRIMARY KEY,
            period_start    timestamptz NOT NULL DEFAULT now(),
            period_hours    int NOT NULL,
            budget          int NOT NULL,
            consumed        int NOT NULL DEFAULT 0
        )
    """)

    # Seed with initial budgets
    op.execute("""
        INSERT INTO resource_budgets (resource_type, period_hours, budget) VALUES
            ('github_api', 1, 4500),
            ('gemini', 24, 10000),
            ('openai', 1, 24000)
    """)

    # -- raw_cache table --
    op.execute("""
        CREATE TABLE raw_cache (
            source      text NOT NULL,
            subject_id  text NOT NULL,
            fetched_at  timestamptz NOT NULL DEFAULT now(),
            payload     text,
            PRIMARY KEY (source, subject_id)
        )
    """)

    op.execute("""
        CREATE INDEX idx_raw_cache_fetched
        ON raw_cache (source, fetched_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS raw_cache")
    op.execute("DROP TABLE IF EXISTS resource_budgets")
    op.execute("DROP TABLE IF EXISTS tasks")
