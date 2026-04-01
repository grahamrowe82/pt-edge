"""Add coverage audit infrastructure

Revision ID: 068
Revises: 067
Create Date: 2026-04-01

Three tables for weekly awesome-list coverage auditing:
  - awesome_list_sources: discovered awesome lists
  - awesome_list_repos: repos extracted from each list + reconciliation status
  - coverage_snapshots: weekly summary metrics per list
"""
from typing import Sequence, Union

from alembic import op

revision: str = "068"
down_revision: Union[str, None] = "067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS awesome_list_sources (
            id SERIAL PRIMARY KEY,
            full_name VARCHAR(200) NOT NULL UNIQUE,
            url TEXT NOT NULL,
            stars INT,
            last_scanned_at TIMESTAMPTZ,
            repo_count INT,
            description TEXT,
            discovered_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS awesome_list_repos (
            id SERIAL PRIMARY KEY,
            source_id INT REFERENCES awesome_list_sources(id),
            repo_full_name VARCHAR(200) NOT NULL,
            matched_ai_repo_id INT REFERENCES ai_repos(id),
            scan_date DATE NOT NULL DEFAULT CURRENT_DATE,
            status VARCHAR(20) NOT NULL DEFAULT 'unmatched',
            github_stars INT,
            github_last_pushed TIMESTAMPTZ,
            github_archived BOOLEAN,
            github_description TEXT,
            UNIQUE (source_id, repo_full_name, scan_date)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_alr_status ON awesome_list_repos(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_alr_source ON awesome_list_repos(source_id, scan_date)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS coverage_snapshots (
            id SERIAL PRIMARY KEY,
            scan_date DATE NOT NULL DEFAULT CURRENT_DATE,
            source_full_name VARCHAR(200) NOT NULL,
            total_listed INT NOT NULL,
            matched INT NOT NULL,
            unmatched INT NOT NULL,
            stale INT NOT NULL DEFAULT 0,
            archived INT NOT NULL DEFAULT 0,
            out_of_scope INT NOT NULL DEFAULT 0,
            coverage_pct NUMERIC(5,2),
            UNIQUE (source_full_name, scan_date)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS coverage_snapshots CASCADE")
    op.execute("DROP TABLE IF EXISTS awesome_list_repos CASCADE")
    op.execute("DROP TABLE IF EXISTS awesome_list_sources CASCADE")
