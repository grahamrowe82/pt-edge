"""Add 12 new domains: quality materialized views

Revision ID: 087
Revises: 086
Create Date: 2026-04-07

Creates mv_*_quality views for: llm-inference, ai-evals, fine-tuning,
document-ai, ai-safety, recommendation-systems, audio-ai, synthetic-data,
time-series, multimodal, 3d-ai, scientific-ml.
"""
from string import Template
from typing import Sequence, Union

from alembic import op

revision: str = "087"
down_revision: Union[str, None] = "086"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Quality MV template — same as migration 071
_QUALITY_VIEW_SQL = Template("""
CREATE MATERIALIZED VIEW $view_name AS
WITH
dep_counts AS (
    SELECT ar.id AS repo_id, COUNT(DISTINCT pd.repo_id) AS reverse_dep_count
    FROM ai_repos ar
    LEFT JOIN package_deps pd ON (
        (pd.dep_name = ar.pypi_package AND ar.pypi_package IS NOT NULL)
        OR (pd.dep_name = ar.npm_package AND ar.npm_package IS NOT NULL))
    WHERE ar.domain = '$domain'
    GROUP BY ar.id
),
ages AS (
    SELECT id AS repo_id,
           EXTRACT(DAY FROM NOW() - COALESCE(created_at, discovered_at))::int AS age_days
    FROM ai_repos WHERE domain = '$domain'
),
scored AS (
    SELECT
        ar.id, ar.full_name, ar.name, ar.description, ar.ai_summary,
        ar.stars, ar.forks, ar.language, ar.license, ar.archived,
        ar.category, ar.subcategory, ar.last_pushed_at, ar.pypi_package, ar.npm_package,
        ar.downloads_monthly, ar.dependency_count, ar.commits_30d,
        COALESCE(dc.reverse_dep_count, 0) AS reverse_dep_count,
        CASE WHEN ar.archived THEN 0 ELSE
            LEAST(12, CASE
                WHEN COALESCE(ar.commits_30d, 0) = 0 THEN 0
                WHEN ar.commits_30d <= 5 THEN 3 WHEN ar.commits_30d <= 20 THEN 7
                WHEN ar.commits_30d <= 50 THEN 10 ELSE 12 END)
            + CASE
                WHEN ar.last_pushed_at IS NULL THEN 0
                WHEN ar.last_pushed_at >= NOW() - INTERVAL '30 days' THEN 13
                WHEN ar.last_pushed_at >= NOW() - INTERVAL '90 days' THEN 10
                WHEN ar.last_pushed_at >= NOW() - INTERVAL '180 days' THEN 6
                WHEN ar.last_pushed_at >= NOW() - INTERVAL '365 days' THEN 2
                ELSE 0 END
        END AS maintenance_score,
        LEAST(10, CASE WHEN COALESCE(ar.stars, 0) = 0 THEN 0
            ELSE GREATEST(0, (LN(ar.stars + 1) * 2)::int) END)
        + LEAST(10, CASE WHEN COALESCE(ar.downloads_monthly, 0) = 0 THEN 0
            ELSE GREATEST(0, LN(ar.downloads_monthly + 1)::int) END)
        + LEAST(5, COALESCE(dc.reverse_dep_count, 0))
        AS adoption_score,
        CASE WHEN ar.license IS NOT NULL AND ar.license != '' THEN 8 ELSE 0 END
        + CASE WHEN ar.pypi_package IS NOT NULL OR ar.npm_package IS NOT NULL THEN 9 ELSE 0 END
        + LEAST(8, CASE
            WHEN COALESCE(ag.age_days, 0) = 0 THEN 0
            WHEN ag.age_days < 30 THEN 1 WHEN ag.age_days < 90 THEN 3
            WHEN ag.age_days < 180 THEN 5 WHEN ag.age_days < 365 THEN 7
            ELSE 8 END)
        AS maturity_score,
        LEAST(15, CASE WHEN COALESCE(ar.forks, 0) = 0 THEN 0
            ELSE GREATEST(0, (LN(ar.forks + 1) * 3)::int) END)
        + LEAST(10, CASE WHEN COALESCE(ar.stars, 0) = 0 THEN 0
            ELSE LEAST(10, ROUND(COALESCE(ar.forks, 0)::numeric / NULLIF(ar.stars, 0) * 50))::int END)
        AS community_score
    FROM ai_repos ar
    LEFT JOIN dep_counts dc ON ar.id = dc.repo_id
    LEFT JOIN ages ag ON ar.id = ag.repo_id
    WHERE ar.domain = '$domain'
)
SELECT id, full_name, name, description, ai_summary, stars, forks, language, license, archived,
    category, subcategory, last_pushed_at, pypi_package, npm_package, downloads_monthly,
    dependency_count, commits_30d, reverse_dep_count,
    maintenance_score, adoption_score, maturity_score, community_score,
    LEAST(100, maintenance_score + adoption_score + maturity_score + community_score) AS quality_score,
    CASE
        WHEN LEAST(100, maintenance_score + adoption_score + maturity_score + community_score) >= 70 THEN 'verified'
        WHEN LEAST(100, maintenance_score + adoption_score + maturity_score + community_score) >= 50 THEN 'established'
        WHEN LEAST(100, maintenance_score + adoption_score + maturity_score + community_score) >= 30 THEN 'emerging'
        ELSE 'experimental'
    END AS quality_tier,
    (
        CASE WHEN archived THEN ARRAY['archived'] ELSE ARRAY[]::text[] END
        || CASE WHEN license IS NULL OR license = '' THEN ARRAY['no_license'] ELSE ARRAY[]::text[] END
        || CASE WHEN last_pushed_at < NOW() - INTERVAL '180 days' OR last_pushed_at IS NULL
                THEN ARRAY['stale_6m'] ELSE ARRAY[]::text[] END
        || CASE WHEN pypi_package IS NULL AND npm_package IS NULL
                THEN ARRAY['no_package'] ELSE ARRAY[]::text[] END
        || CASE WHEN COALESCE(dependency_count, 0) = 0 AND reverse_dep_count = 0
                THEN ARRAY['no_dependents'] ELSE ARRAY[]::text[] END
    ) AS risk_flags
FROM scored
""")

NEW_DOMAINS = [
    ("mv_llm_inference_quality", "llm-inference"),
    ("mv_ai_evals_quality", "ai-evals"),
    ("mv_fine_tuning_quality", "fine-tuning"),
    ("mv_document_ai_quality", "document-ai"),
    ("mv_ai_safety_quality", "ai-safety"),
    ("mv_recommendation_systems_quality", "recommendation-systems"),
    ("mv_audio_ai_quality", "audio-ai"),
    ("mv_synthetic_data_quality", "synthetic-data"),
    ("mv_time_series_quality", "time-series"),
    ("mv_multimodal_quality", "multimodal"),
    ("mv_3d_ai_quality", "3d-ai"),
    ("mv_scientific_ml_quality", "scientific-ml"),
]


def upgrade() -> None:
    for view_name, domain in NEW_DOMAINS:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view_name} CASCADE")
        op.execute(_QUALITY_VIEW_SQL.substitute(view_name=view_name, domain=domain))
        op.execute(f"CREATE UNIQUE INDEX idx_{view_name}_id ON {view_name} (id)")


def downgrade() -> None:
    for view_name, _ in NEW_DOMAINS:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view_name} CASCADE")
