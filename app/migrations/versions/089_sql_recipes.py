"""Add sql_recipes table for workflow recipes as data.

Revision ID: 089
Revises: 088
Create Date: 2026-04-11

Agents discover these recipes via list_workflows() or
SELECT * FROM sql_recipes. They read the template and adapt it
to their needs — they don't execute it blindly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = "089"
down_revision: Union[str, None] = "088"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sql_recipes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("category", sa.String(50)),
        sa.Column("sql_template", sa.Text, nullable=False),
        sa.Column("parameters", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Seed with cowpath-based recipes
    op.execute("""
        INSERT INTO sql_recipes (name, description, category, sql_template, parameters) VALUES
        (
            'project_detail',
            'Look up a specific project by name. Returns key metrics and AI summary.',
            'point_lookup',
            $$SELECT full_name, stars, forks, ai_summary, domain, subcategory,
       quality_score, language, license, last_pushed_at, downloads_monthly
FROM ai_repos
WHERE full_name ILIKE ''%'' || :project || ''%''
ORDER BY stars DESC LIMIT 5$$,
            '{"project": {"type": "string", "description": "Project name or partial match (e.g. ''langchain'')"}}'::jsonb
        ),
        (
            'landscape_scan',
            'List top projects in a domain, sorted by stars. Use for "what are all the tools for X?" questions.',
            'landscape',
            $$SELECT full_name, stars, ai_summary, quality_score, language, last_pushed_at
FROM ai_repos
WHERE domain = :domain AND archived = false
ORDER BY stars DESC LIMIT 50$$,
            '{"domain": {"type": "string", "description": "Domain slug (e.g. ''mcp'', ''agents'', ''rag'', ''llm-tools'')"}}'::jsonb
        ),
        (
            'whats_new',
            'Recently created repos, sorted by stars. Use for "what shipped recently?" questions.',
            'trending',
            $$SELECT full_name, stars, domain, language, ai_summary, created_at
FROM ai_repos
WHERE created_at > now() - (:days || '' days'')::interval
  AND archived = false
ORDER BY stars DESC LIMIT 30$$,
            '{"days": {"type": "integer", "description": "Look-back window in days (default 7)", "default": 7}}'::jsonb
        ),
        (
            'domain_overview',
            'Summary statistics for a domain: total repos, top languages, star distribution.',
            'landscape',
            $$SELECT
    COUNT(*) AS total_repos,
    COUNT(*) FILTER (WHERE stars >= 1000) AS repos_1k_plus,
    COUNT(*) FILTER (WHERE stars >= 10000) AS repos_10k_plus,
    ROUND(AVG(stars)) AS avg_stars,
    MAX(stars) AS max_stars,
    mode() WITHIN GROUP (ORDER BY language) AS top_language
FROM ai_repos
WHERE domain = :domain AND archived = false$$,
            '{"domain": {"type": "string", "description": "Domain slug"}}'::jsonb
        );
    """)


def downgrade() -> None:
    op.drop_table("sql_recipes")
