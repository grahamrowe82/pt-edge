"""Add subcategory + crate_package to ai_repos, ai_repo_id FK on projects,
and mv_ai_repo_ecosystem materialized view.

Revision ID: 032
Revises: 031
Create Date: 2026-03-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "032"
down_revision: Union[str, None] = "031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. ai_repos: subcategory column ---
    op.execute("ALTER TABLE ai_repos ADD COLUMN subcategory VARCHAR(50)")
    op.execute(
        "CREATE INDEX ix_ai_repos_domain_subcategory "
        "ON ai_repos (domain, subcategory)"
    )

    # --- 2. ai_repos: crate_package column ---
    op.execute("ALTER TABLE ai_repos ADD COLUMN crate_package VARCHAR(200)")

    # --- 3. projects: foreign key to ai_repos ---
    op.execute("ALTER TABLE projects ADD COLUMN ai_repo_id INTEGER")
    op.execute(
        "ALTER TABLE projects ADD CONSTRAINT fk_projects_ai_repo_id "
        "FOREIGN KEY (ai_repo_id) REFERENCES ai_repos(id)"
    )
    op.execute("CREATE INDEX ix_projects_ai_repo_id ON projects (ai_repo_id)")

    # --- 4. Backfill ai_repo_id for existing projects ---
    op.execute("""
        UPDATE projects p
        SET ai_repo_id = a.id
        FROM ai_repos a
        WHERE LOWER(p.github_owner) = LOWER(a.github_owner)
          AND LOWER(p.github_repo) = LOWER(a.github_repo)
          AND p.ai_repo_id IS NULL
          AND p.github_owner IS NOT NULL
    """)

    # --- 5. Materialized view: mv_ai_repo_ecosystem ---
    op.execute("""
CREATE MATERIALIZED VIEW mv_ai_repo_ecosystem AS
SELECT
    domain,
    subcategory,
    COUNT(*) AS repo_count,
    COUNT(*) FILTER (WHERE stars >= 100) AS repos_100_plus_stars,
    COUNT(*) FILTER (WHERE stars >= 1000) AS repos_1k_plus_stars,
    ROUND(AVG(stars)::numeric, 0) AS avg_stars,
    MAX(stars) AS max_stars,
    SUM(downloads_monthly) AS total_downloads_monthly,
    COUNT(*) FILTER (WHERE downloads_monthly > 0) AS repos_with_downloads,
    COUNT(*) FILTER (WHERE pypi_package IS NOT NULL) AS pypi_count,
    COUNT(*) FILTER (WHERE npm_package IS NOT NULL) AS npm_count,
    COUNT(*) FILTER (WHERE crate_package IS NOT NULL) AS crate_count,
    ROUND(AVG(EXTRACT(EPOCH FROM (NOW() - last_pushed_at)) / 86400)::numeric, 0)
        AS avg_days_since_push,
    COUNT(*) FILTER (WHERE archived = true) AS archived_count
FROM ai_repos
WHERE domain != 'uncategorized'
GROUP BY domain, subcategory
ORDER BY domain, repo_count DESC
    """)
    op.execute("""
CREATE UNIQUE INDEX ix_mv_ai_repo_ecosystem_uniq
    ON mv_ai_repo_ecosystem (domain, COALESCE(subcategory, ''))
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_ai_repo_ecosystem")
    op.execute("ALTER TABLE projects DROP CONSTRAINT IF EXISTS fk_projects_ai_repo_id")
    op.execute("DROP INDEX IF EXISTS ix_projects_ai_repo_id")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS ai_repo_id")
    op.execute("ALTER TABLE ai_repos DROP COLUMN IF EXISTS crate_package")
    op.execute("DROP INDEX IF EXISTS ix_ai_repos_domain_subcategory")
    op.execute("ALTER TABLE ai_repos DROP COLUMN IF EXISTS subcategory")
