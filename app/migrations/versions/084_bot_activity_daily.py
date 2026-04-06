"""Create bot_activity_daily snapshot table

Revision ID: 084
Revises: 083
Create Date: 2026-04-06

Foundation for the Demand Radar ML pipeline. One row per
(date, domain, subcategory, bot_family) with aggregate metrics.
~10-15K rows/day. Populated daily by the snapshot_bot_activity
worker task after the MV refresh.

Every day without this table is a day of lost training data.
"""

from alembic import op

revision = "084"
down_revision = "083"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE bot_activity_daily (
            id SERIAL PRIMARY KEY,
            snapshot_date DATE NOT NULL,
            domain VARCHAR(50) NOT NULL,
            subcategory VARCHAR(100) NOT NULL,
            bot_family VARCHAR(30) NOT NULL,
            hits INT NOT NULL DEFAULT 0,
            unique_pages INT NOT NULL DEFAULT 0,
            unique_ips INT NOT NULL DEFAULT 0,
            revisit_ratio NUMERIC(5,2),
            UNIQUE (snapshot_date, domain, subcategory, bot_family)
        )
    """)
    op.execute(
        "CREATE INDEX ix_bot_activity_daily_date "
        "ON bot_activity_daily (snapshot_date)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bot_activity_daily")
