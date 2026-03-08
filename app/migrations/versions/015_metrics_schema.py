"""Create metrics schema with thin views for Evidence.dev dashboard

The clarity monorepo (Evidence.dev) expects SELECT * FROM metrics.<view>.
These thin views point to existing public tables and materialized views,
allowing Evidence SQL sources to query them without schema changes.

Revision ID: 015
Revises: 014
Create Date: 2026-03-08
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Materialized views to expose
_MV_VIEWS = [
    ("project_summary", "mv_project_summary"),
    ("momentum", "mv_momentum"),
    ("hype_ratio", "mv_hype_ratio"),
    ("lab_velocity", "mv_lab_velocity"),
    ("project_tier", "mv_project_tier"),
    ("lifecycle", "mv_lifecycle"),
]

# Raw tables to expose
_TABLE_VIEWS = [
    "labs",
    "lab_events",
    "frontier_models",
    "projects",
    "hn_posts",
    "v2ex_posts",
    "methodology",
    "download_snapshots",
    "github_snapshots",
    "lifecycle_history",
]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS metrics")

    # Thin views over materialized views
    for view_name, mv_name in _MV_VIEWS:
        op.execute(
            f"CREATE OR REPLACE VIEW metrics.{view_name} AS "
            f"SELECT * FROM public.{mv_name}"
        )

    # Thin views over raw tables
    for table_name in _TABLE_VIEWS:
        op.execute(
            f"CREATE OR REPLACE VIEW metrics.{table_name} AS "
            f"SELECT * FROM public.{table_name}"
        )


def downgrade() -> None:
    # Drop all views in metrics schema
    for view_name, _ in _MV_VIEWS:
        op.execute(f"DROP VIEW IF EXISTS metrics.{view_name}")

    for table_name in _TABLE_VIEWS:
        op.execute(f"DROP VIEW IF EXISTS metrics.{table_name}")

    op.execute("DROP SCHEMA IF EXISTS metrics")
