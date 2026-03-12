"""Add client_ip and user_agent columns to tool_usage.

Enables distinguishing real users from health checks and bots.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_usage", sa.Column("client_ip", sa.String(45), nullable=True))
    op.add_column("tool_usage", sa.Column("user_agent", sa.String(500), nullable=True))
    op.create_index("ix_tool_usage_client_ip", "tool_usage", ["client_ip"])


def downgrade() -> None:
    op.drop_index("ix_tool_usage_client_ip", table_name="tool_usage")
    op.drop_column("tool_usage", "user_agent")
    op.drop_column("tool_usage", "client_ip")
