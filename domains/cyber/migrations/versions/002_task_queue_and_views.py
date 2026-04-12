"""Task queue schema fixes + resource budget seeds + initial materialized views.

Revision ID: 002
Revises: 001
Create Date: 2026-04-11

Adds missing columns to tasks table (subject_id, claimed_by, etc.),
creates dedup index, seeds resource_budgets, and creates initial
materialized views for CVE/software/vendor scoring.
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    # --- Task queue fixes ---

    # Add missing columns to tasks table
    op.add_column("tasks", sa.Column("subject_id", sa.Text))
    op.add_column("tasks", sa.Column("claimed_by", sa.Text))
    op.add_column("tasks", sa.Column("claimed_at", sa.DateTime(timezone=True)))
    op.add_column("tasks", sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.add_column("tasks", sa.Column("estimated_cost_usd", sa.Numeric(10, 6)))

    # Dedup index: prevent duplicate pending/claimed tasks for same type+subject
    op.execute("""
        CREATE UNIQUE INDEX idx_tasks_dedup
        ON tasks (task_type, COALESCE(subject_id, ''))
        WHERE state IN ('pending', 'claimed')
    """)

    # Claimable index for fast claim queries
    op.execute("""
        CREATE INDEX idx_tasks_claimable
        ON tasks (priority DESC, created_at ASC)
        WHERE state = 'pending'
    """)

    # Type+subject lookup
    op.execute("""
        CREATE INDEX idx_tasks_type_subject
        ON tasks (task_type, subject_id)
    """)

    # Active tasks for monitoring
    op.execute("""
        CREATE INDEX idx_tasks_active
        ON tasks (state)
        WHERE state IN ('claimed', 'pending')
    """)

    # Seed resource budgets for CyberEdge data sources
    op.execute("""
        INSERT INTO resource_budgets (resource_type, period_hours, budget, rpm) VALUES
            ('nvd',        24, 100000, 100),
            ('mitre',      24, 1000,   NULL),
            ('osv_ghsa',   24, 50000,  NULL),
            ('exploit_db', 24, 10000,  NULL),
            ('db_only',    24, 999999, NULL)
        ON CONFLICT (resource_type) DO NOTHING
    """)

    # --- Materialized views ---

    # CVE scores: severity from CVSS, exposure from CPE count
    op.execute("""
        CREATE MATERIALIZED VIEW mv_cve_scores AS
        SELECT
            c.id,
            c.cve_id,
            LEAST(25, (
                COALESCE(c.cvss_base_score, 0) * 2
                + CASE WHEN c.attack_complexity = 'LOW' THEN 3 ELSE 0 END
                + CASE WHEN c.attack_vector = 'NETWORK' THEN 2 ELSE 0 END
            )::int) AS severity,
            0 AS exploitability,
            LEAST(25, (
                LN(GREATEST(1, COALESCE(sw_count.cnt, 0)) + 1) * 5
            )::int) AS exposure,
            0 AS patch_availability,
            LEAST(100, (
                LEAST(25, (
                    COALESCE(c.cvss_base_score, 0) * 2
                    + CASE WHEN c.attack_complexity = 'LOW' THEN 3 ELSE 0 END
                    + CASE WHEN c.attack_vector = 'NETWORK' THEN 2 ELSE 0 END
                )::int)
                + LEAST(25, (
                    LN(GREATEST(1, COALESCE(sw_count.cnt, 0)) + 1) * 5
                )::int)
            )) AS composite_score,
            CASE
                WHEN LEAST(100, (
                    LEAST(25, (COALESCE(c.cvss_base_score, 0) * 2
                        + CASE WHEN c.attack_complexity = 'LOW' THEN 3 ELSE 0 END
                        + CASE WHEN c.attack_vector = 'NETWORK' THEN 2 ELSE 0 END)::int)
                    + LEAST(25, (LN(GREATEST(1, COALESCE(sw_count.cnt, 0)) + 1) * 5)::int)
                )) >= 70 THEN 'critical-risk'
                WHEN LEAST(100, (
                    LEAST(25, (COALESCE(c.cvss_base_score, 0) * 2
                        + CASE WHEN c.attack_complexity = 'LOW' THEN 3 ELSE 0 END
                        + CASE WHEN c.attack_vector = 'NETWORK' THEN 2 ELSE 0 END)::int)
                    + LEAST(25, (LN(GREATEST(1, COALESCE(sw_count.cnt, 0)) + 1) * 5)::int)
                )) >= 50 THEN 'high-risk'
                WHEN LEAST(100, (
                    LEAST(25, (COALESCE(c.cvss_base_score, 0) * 2
                        + CASE WHEN c.attack_complexity = 'LOW' THEN 3 ELSE 0 END
                        + CASE WHEN c.attack_vector = 'NETWORK' THEN 2 ELSE 0 END)::int)
                    + LEAST(25, (LN(GREATEST(1, COALESCE(sw_count.cnt, 0)) + 1) * 5)::int)
                )) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM cves c
        LEFT JOIN (
            SELECT cve_id, COUNT(*) AS cnt FROM cve_software GROUP BY cve_id
        ) sw_count ON sw_count.cve_id = c.id
        WHERE c.cvss_base_score IS NOT NULL
    """)

    op.execute("CREATE UNIQUE INDEX ON mv_cve_scores (id)")

    # Software scores: aggregated from CVE scores
    op.execute("""
        CREATE MATERIALIZED VIEW mv_software_scores AS
        SELECT
            s.id,
            s.cpe_id,
            s.name,
            LEAST(25, COALESCE(agg.max_severity, 0)) AS severity,
            0 AS exploitability,
            LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 4)::int) AS exposure,
            0 AS patch_availability,
            LEAST(100,
                LEAST(25, COALESCE(agg.max_severity, 0))
                + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 4)::int)
            ) AS composite_score,
            CASE
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 4)::int)
                ) >= 70 THEN 'critical-risk'
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 4)::int)
                ) >= 50 THEN 'high-risk'
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 4)::int)
                ) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM software s
        LEFT JOIN (
            SELECT cs.software_id,
                   COUNT(*) AS cve_count,
                   MAX(cv.severity) AS max_severity
            FROM cve_software cs
            JOIN mv_cve_scores cv ON cv.id = cs.cve_id
            GROUP BY cs.software_id
        ) agg ON agg.software_id = s.id
    """)

    op.execute("CREATE UNIQUE INDEX ON mv_software_scores (id)")

    # Vendor scores: aggregated from software scores across product portfolio
    op.execute("""
        CREATE MATERIALIZED VIEW mv_vendor_scores AS
        SELECT
            v.id,
            v.name,
            v.slug,
            LEAST(25, COALESCE(agg.max_severity, 0)) AS severity,
            0 AS exploitability,
            LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int) AS exposure,
            0 AS patch_availability,
            LEAST(100,
                LEAST(25, COALESCE(agg.max_severity, 0))
                + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int)
            ) AS composite_score,
            CASE
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int)
                ) >= 70 THEN 'critical-risk'
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int)
                ) >= 50 THEN 'high-risk'
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int)
                ) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM vendors v
        LEFT JOIN (
            SELECT cv.vendor_id,
                   COUNT(DISTINCT cv.cve_id) AS cve_count,
                   MAX(cs.severity) AS max_severity
            FROM cve_vendors cv
            JOIN mv_cve_scores cs ON cs.id = cv.cve_id
            GROUP BY cv.vendor_id
        ) agg ON agg.vendor_id = v.id
    """)

    op.execute("CREATE UNIQUE INDEX ON mv_vendor_scores (id)")

    # Entity summary: counts per entity type + tier distribution
    op.execute("""
        CREATE MATERIALIZED VIEW mv_entity_summary AS
        SELECT 'cves' AS entity_type, COUNT(*) AS total,
               COUNT(*) FILTER (WHERE quality_tier = 'critical-risk') AS critical_risk,
               COUNT(*) FILTER (WHERE quality_tier = 'high-risk') AS high_risk,
               COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk') AS moderate_risk,
               COUNT(*) FILTER (WHERE quality_tier = 'low-risk') AS low_risk
        FROM mv_cve_scores
        UNION ALL
        SELECT 'software', COUNT(*),
               COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'high-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'low-risk')
        FROM mv_software_scores
        UNION ALL
        SELECT 'vendors', COUNT(*),
               COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'high-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'low-risk')
        FROM mv_vendor_scores
    """)


def downgrade():
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_entity_summary")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_vendor_scores")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_software_scores")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_cve_scores")
    op.execute("DROP INDEX IF EXISTS idx_tasks_active")
    op.execute("DROP INDEX IF EXISTS idx_tasks_type_subject")
    op.execute("DROP INDEX IF EXISTS idx_tasks_claimable")
    op.execute("DROP INDEX IF EXISTS idx_tasks_dedup")
    op.drop_column("tasks", "estimated_cost_usd")
    op.drop_column("tasks", "completed_at")
    op.drop_column("tasks", "claimed_at")
    op.drop_column("tasks", "claimed_by")
    op.drop_column("tasks", "subject_id")
