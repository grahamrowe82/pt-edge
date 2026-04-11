"""Add transport, client_ip, user_agent to api_usage for unified observability.

Revision ID: 090
Revises: 089
Create Date: 2026-04-11

All three transports (REST, MCP, CLI) log to api_usage.
The transport column identifies the source. api_key_id becomes
nullable so MCP calls via API_TOKEN (no key row) can be tracked.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "090"
down_revision: Union[str, None] = "089"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("api_usage", sa.Column("transport", sa.String(10)))
    op.add_column("api_usage", sa.Column("client_ip", sa.String(45)))
    op.add_column("api_usage", sa.Column("user_agent", sa.String(500)))

    # Make api_key_id nullable so MCP/CLI calls without a pte_* key can be logged
    op.alter_column("api_usage", "api_key_id", nullable=True)

    # Backfill existing rows as 'rest' transport
    op.execute("UPDATE api_usage SET transport = 'rest' WHERE transport IS NULL")


def downgrade() -> None:
    op.drop_column("api_usage", "user_agent")
    op.drop_column("api_usage", "client_ip")
    op.drop_column("api_usage", "transport")
    op.alter_column("api_usage", "api_key_id", nullable=False)
