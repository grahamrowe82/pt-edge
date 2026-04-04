"""Add http_access_log table for bot demand intelligence

Revision ID: 074
Revises: 073
Create Date: 2026-04-04

Captures HTTP requests to the static directory site (HTML pages only).
Every bot crawl is a demand signal — this table is the foundation for
the demand intelligence flywheel.
"""

from alembic import op
import sqlalchemy as sa

revision = "074"
down_revision = "073"


def upgrade() -> None:
    op.create_table(
        "http_access_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("path", sa.String(200), nullable=False),
        sa.Column("method", sa.String(10), nullable=False, server_default="GET"),
        sa.Column("status_code", sa.SmallInteger()),
        sa.Column("user_agent", sa.String(300)),
        sa.Column("client_ip", sa.String(45)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_http_access_log_created", "http_access_log", ["created_at"])
    op.create_index("idx_http_access_log_path", "http_access_log", ["path"])


def downgrade() -> None:
    op.drop_index("idx_http_access_log_path")
    op.drop_index("idx_http_access_log_created")
    op.drop_table("http_access_log")
