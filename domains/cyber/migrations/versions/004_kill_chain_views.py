"""Kill chain scoring views: weakness, pattern, technique scores.

Revision ID: 004
Revises: 003
Create Date: 2026-04-11

Adds materialized views for the three remaining entity types (weaknesses,
attack patterns, techniques) by aggregating CVE scores through the
kill chain: CVE �� CWE → CAPEC → ATT&CK. Updates mv_entity_summary
to include all 6 entity types.
"""
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    # Drop entity summary (depends on all scoring views)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_entity_summary")

    # Weakness scores: aggregated from linked CVE scores via cve_weaknesses
    op.execute("""
        CREATE MATERIALIZED VIEW mv_weakness_scores AS
        SELECT
            w.id,
            w.cwe_id,
            w.name,
            LEAST(25, COALESCE(agg.max_severity, 0)) AS severity,
            LEAST(25, COALESCE(agg.max_exploitability, 0)) AS exploitability,
            LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int) AS exposure,
            0 AS patch_availability,
            LEAST(100,
                LEAST(25, COALESCE(agg.max_severity, 0))
                + LEAST(25, COALESCE(agg.max_exploitability, 0))
                + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int)
            ) AS composite_score,
            CASE
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, COALESCE(agg.max_exploitability, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int)
                ) >= 70 THEN 'critical-risk'
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, COALESCE(agg.max_exploitability, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int)
                ) >= 50 THEN 'high-risk'
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, COALESCE(agg.max_exploitability, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int)
                ) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM weaknesses w
        LEFT JOIN (
            SELECT cw.weakness_id,
                   COUNT(DISTINCT cw.cve_id) AS cve_count,
                   MAX(cs.severity) AS max_severity,
                   MAX(cs.exploitability) AS max_exploitability
            FROM cve_weaknesses cw
            JOIN mv_cve_scores cs ON cs.id = cw.cve_id
            GROUP BY cw.weakness_id
        ) agg ON agg.weakness_id = w.id
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_weakness_scores (id)")

    # Pattern scores: aggregated from linked CVE scores via weakness_patterns → cve_weaknesses
    op.execute("""
        CREATE MATERIALIZED VIEW mv_pattern_scores AS
        SELECT
            ap.id,
            ap.capec_id,
            ap.name,
            LEAST(25, COALESCE(agg.max_severity, 0)) AS severity,
            LEAST(25, COALESCE(agg.max_exploitability, 0)) AS exploitability,
            LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2.5)::int) AS exposure,
            0 AS patch_availability,
            LEAST(100,
                LEAST(25, COALESCE(agg.max_severity, 0))
                + LEAST(25, COALESCE(agg.max_exploitability, 0))
                + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2.5)::int)
            ) AS composite_score,
            CASE
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, COALESCE(agg.max_exploitability, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2.5)::int)
                ) >= 70 THEN 'critical-risk'
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, COALESCE(agg.max_exploitability, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2.5)::int)
                ) >= 50 THEN 'high-risk'
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, COALESCE(agg.max_exploitability, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2.5)::int)
                ) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM attack_patterns ap
        LEFT JOIN (
            SELECT wp.pattern_id,
                   COUNT(DISTINCT cw.cve_id) AS cve_count,
                   MAX(cs.severity) AS max_severity,
                   MAX(cs.exploitability) AS max_exploitability
            FROM weakness_patterns wp
            JOIN cve_weaknesses cw ON cw.weakness_id = wp.weakness_id
            JOIN mv_cve_scores cs ON cs.id = cw.cve_id
            GROUP BY wp.pattern_id
        ) agg ON agg.pattern_id = ap.id
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_pattern_scores (id)")

    # Technique scores: aggregated through full chain technique → patterns → weaknesses → CVEs
    op.execute("""
        CREATE MATERIALIZED VIEW mv_technique_scores AS
        SELECT
            t.id,
            t.technique_id,
            t.name,
            LEAST(25, COALESCE(agg.max_severity, 0)) AS severity,
            LEAST(25, COALESCE(agg.max_exploitability, 0)) AS exploitability,
            LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2)::int) AS exposure,
            0 AS patch_availability,
            LEAST(100,
                LEAST(25, COALESCE(agg.max_severity, 0))
                + LEAST(25, COALESCE(agg.max_exploitability, 0))
                + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2)::int)
            ) AS composite_score,
            CASE
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, COALESCE(agg.max_exploitability, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2)::int)
                ) >= 70 THEN 'critical-risk'
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, COALESCE(agg.max_exploitability, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2)::int)
                ) >= 50 THEN 'high-risk'
                WHEN LEAST(100,
                    LEAST(25, COALESCE(agg.max_severity, 0))
                    + LEAST(25, COALESCE(agg.max_exploitability, 0))
                    + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2)::int)
                ) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM techniques t
        LEFT JOIN (
            SELECT pt.technique_id,
                   COUNT(DISTINCT cw.cve_id) AS cve_count,
                   MAX(cs.severity) AS max_severity,
                   MAX(cs.exploitability) AS max_exploitability
            FROM pattern_techniques pt
            JOIN weakness_patterns wp ON wp.pattern_id = pt.pattern_id
            JOIN cve_weaknesses cw ON cw.weakness_id = wp.weakness_id
            JOIN mv_cve_scores cs ON cs.id = cw.cve_id
            GROUP BY pt.technique_id
        ) agg ON agg.technique_id = t.id
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_technique_scores (id)")

    # Updated entity summary with all 6 entity types
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
        UNION ALL
        SELECT 'weaknesses', COUNT(*),
               COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'high-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'low-risk')
        FROM mv_weakness_scores
        UNION ALL
        SELECT 'techniques', COUNT(*),
               COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'high-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'low-risk')
        FROM mv_technique_scores
        UNION ALL
        SELECT 'attack_patterns', COUNT(*),
               COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'high-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'),
               COUNT(*) FILTER (WHERE quality_tier = 'low-risk')
        FROM mv_pattern_scores
    """)


def downgrade():
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_entity_summary")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_technique_scores")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_pattern_scores")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_weakness_scores")
    # Recreate the entity summary from 003 (just cves, software, vendors)
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
