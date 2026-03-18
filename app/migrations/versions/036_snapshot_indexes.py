"""Add snapshot_date indexes for momentum view range joins.

Revision ID: 036
"""

from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_gh_snapshots_date ON github_snapshots (snapshot_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_dl_snapshots_date ON download_snapshots (snapshot_date)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_gh_snapshots_date")
    op.execute("DROP INDEX IF EXISTS idx_dl_snapshots_date")
