"""Add builder_tools table for canonical developer tool registry with MCP status.

Tracks developer tools/services and their MCP server availability.
Seeded from APIs.guru providers, enriched by cross-referencing ai_repos.

Revision ID: 028
Revises: 027
Create Date: 2026-03-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE builder_tools (
            id SERIAL PRIMARY KEY,
            slug VARCHAR(200) NOT NULL UNIQUE,
            name VARCHAR(300) NOT NULL,
            category VARCHAR(100),
            website VARCHAR(500),
            description TEXT,
            mcp_status VARCHAR(20) NOT NULL DEFAULT 'unchecked',
            mcp_type VARCHAR(30),
            mcp_endpoint TEXT,
            mcp_repo_slug VARCHAR(300),
            mcp_npm_package VARCHAR(300),
            mcp_checked_at TIMESTAMPTZ,
            source VARCHAR(30) NOT NULL DEFAULT 'apis_guru',
            source_ref VARCHAR(300),
            discovered_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_builder_tools_category ON builder_tools (category)")
    op.execute("CREATE INDEX ix_builder_tools_mcp_status ON builder_tools (mcp_status)")
    op.execute("CREATE INDEX ix_builder_tools_source ON builder_tools (source)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_builder_tools_source")
    op.execute("DROP INDEX IF EXISTS ix_builder_tools_mcp_status")
    op.execute("DROP INDEX IF EXISTS ix_builder_tools_category")
    op.execute("DROP TABLE IF EXISTS builder_tools")
