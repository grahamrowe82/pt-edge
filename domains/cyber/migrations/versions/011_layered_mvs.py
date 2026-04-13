"""Break mv_cve_scores into layered MVs to avoid crashing 1GB DB.

Revision ID: 011
Revises: 010
Create Date: 2026-04-13

The monolithic mv_cve_scores ran a 2.3M-row GROUP BY and 242K correlated
EXISTS subqueries in a single SQL statement, exhausting shared buffers on
the 1GB basic Postgres instance and dropping all connections.

Fix: pre-compute the expensive parts as two small MVs (software counts
and exploit flags), then rewrite mv_cve_scores to JOIN them instead of
doing inline aggregation. Each layer is lightweight enough for 1GB.

Tested against production DB:
- mv_cve_software_counts: 2 seconds (292K rows)
- mv_cve_exploit_flags: 0.3 seconds (20K rows)
- mv_cve_scores (rewritten): 7 seconds (242K rows)
- Full cascade including downstream MVs: 25 seconds total
"""
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade():
    # Drop all views in reverse dependency order
    for view in ["mv_entity_summary", "mv_technique_scores", "mv_pattern_scores",
                 "mv_weakness_scores", "mv_vendor_scores", "mv_software_scores",
                 "mv_cve_scores"]:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view}")

    # Layer 1: software counts (single-table GROUP BY, no joins)
    op.execute("""
        CREATE MATERIALIZED VIEW mv_cve_software_counts AS
        SELECT cve_id, COUNT(*) AS cnt
        FROM cve_software
        GROUP BY cve_id
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_cve_software_counts (cve_id)")

    # Layer 2: exploit flags (trivial filter on small table)
    op.execute("""
        CREATE MATERIALIZED VIEW mv_cve_exploit_flags AS
        SELECT DISTINCT cve_id
        FROM cve_exploits
        WHERE verified = true
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_cve_exploit_flags (cve_id)")

    # Layer 3: CVE scores joining pre-computed layers (no inline aggregation)
    op.execute("""
        CREATE MATERIALIZED VIEW mv_cve_scores AS
        SELECT
            c.id, c.cve_id,
            c.description, c.cvss_base_score, c.epss_score, c.is_kev,
            c.attack_vector, c.published_date,
            LEAST(25, (
                COALESCE(c.cvss_base_score, 0) * 2
                + CASE WHEN c.attack_complexity = 'LOW' THEN 3 ELSE 0 END
                + CASE WHEN c.attack_vector = 'NETWORK' THEN 2 ELSE 0 END
            )::int) AS severity,
            LEAST(25, (
                LEAST(15, (LN(COALESCE(c.epss_score, 0) * 100 + 1) * 3.5)::int)
                + CASE WHEN c.is_kev THEN 5 ELSE 0 END
                + CASE WHEN ef.cve_id IS NOT NULL THEN 5 ELSE 0 END
            )::int) AS exploitability,
            LEAST(25, (LN(GREATEST(1, COALESCE(sc.cnt, 0)) + 1) * 5)::int) AS exposure,
            CASE WHEN c.has_fix THEN 10 ELSE 25 END AS patch_availability,
            LEAST(100, (
                LEAST(25, (COALESCE(c.cvss_base_score, 0) * 2
                    + CASE WHEN c.attack_complexity = 'LOW' THEN 3 ELSE 0 END
                    + CASE WHEN c.attack_vector = 'NETWORK' THEN 2 ELSE 0 END)::int)
                + LEAST(25, (LEAST(15, (LN(COALESCE(c.epss_score, 0) * 100 + 1) * 3.5)::int)
                    + CASE WHEN c.is_kev THEN 5 ELSE 0 END
                    + CASE WHEN ef.cve_id IS NOT NULL THEN 5 ELSE 0 END)::int)
                + LEAST(25, (LN(GREATEST(1, COALESCE(sc.cnt, 0)) + 1) * 5)::int)
                + CASE WHEN c.has_fix THEN 10 ELSE 25 END
            )) AS composite_score,
            CASE
                WHEN LEAST(100, (
                    LEAST(25, (COALESCE(c.cvss_base_score, 0) * 2 + CASE WHEN c.attack_complexity = 'LOW' THEN 3 ELSE 0 END + CASE WHEN c.attack_vector = 'NETWORK' THEN 2 ELSE 0 END)::int)
                    + LEAST(25, (LEAST(15, (LN(COALESCE(c.epss_score, 0) * 100 + 1) * 3.5)::int) + CASE WHEN c.is_kev THEN 5 ELSE 0 END + CASE WHEN ef.cve_id IS NOT NULL THEN 5 ELSE 0 END)::int)
                    + LEAST(25, (LN(GREATEST(1, COALESCE(sc.cnt, 0)) + 1) * 5)::int)
                    + CASE WHEN c.has_fix THEN 10 ELSE 25 END
                )) >= 70 THEN 'critical-risk'
                WHEN LEAST(100, (
                    LEAST(25, (COALESCE(c.cvss_base_score, 0) * 2 + CASE WHEN c.attack_complexity = 'LOW' THEN 3 ELSE 0 END + CASE WHEN c.attack_vector = 'NETWORK' THEN 2 ELSE 0 END)::int)
                    + LEAST(25, (LEAST(15, (LN(COALESCE(c.epss_score, 0) * 100 + 1) * 3.5)::int) + CASE WHEN c.is_kev THEN 5 ELSE 0 END + CASE WHEN ef.cve_id IS NOT NULL THEN 5 ELSE 0 END)::int)
                    + LEAST(25, (LN(GREATEST(1, COALESCE(sc.cnt, 0)) + 1) * 5)::int)
                    + CASE WHEN c.has_fix THEN 10 ELSE 25 END
                )) >= 50 THEN 'high-risk'
                WHEN LEAST(100, (
                    LEAST(25, (COALESCE(c.cvss_base_score, 0) * 2 + CASE WHEN c.attack_complexity = 'LOW' THEN 3 ELSE 0 END + CASE WHEN c.attack_vector = 'NETWORK' THEN 2 ELSE 0 END)::int)
                    + LEAST(25, (LEAST(15, (LN(COALESCE(c.epss_score, 0) * 100 + 1) * 3.5)::int) + CASE WHEN c.is_kev THEN 5 ELSE 0 END + CASE WHEN ef.cve_id IS NOT NULL THEN 5 ELSE 0 END)::int)
                    + LEAST(25, (LN(GREATEST(1, COALESCE(sc.cnt, 0)) + 1) * 5)::int)
                    + CASE WHEN c.has_fix THEN 10 ELSE 25 END
                )) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM cves c
        LEFT JOIN mv_cve_software_counts sc ON sc.cve_id = c.id
        LEFT JOIN mv_cve_exploit_flags ef ON ef.cve_id = c.id
        WHERE c.cvss_base_score IS NOT NULL
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_cve_scores (id)")

    # Downstream MVs (unchanged structure, just rebuilt)
    op.execute("""CREATE MATERIALIZED VIEW mv_software_scores AS
        SELECT s.id, s.cpe_id, s.name,
            LEAST(25, COALESCE(agg.max_severity, 0)) AS severity, LEAST(25, COALESCE(agg.max_exploitability, 0)) AS exploitability, LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 4)::int) AS exposure, COALESCE(agg.max_patch, 0) AS patch_availability,
            LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 4)::int) + COALESCE(agg.max_patch, 0)) AS composite_score,
            CASE WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 4)::int) + COALESCE(agg.max_patch, 0)) >= 70 THEN 'critical-risk' WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 4)::int) + COALESCE(agg.max_patch, 0)) >= 50 THEN 'high-risk' WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 4)::int) + COALESCE(agg.max_patch, 0)) >= 30 THEN 'moderate-risk' ELSE 'low-risk' END AS quality_tier
        FROM software s LEFT JOIN (SELECT cs.software_id, COUNT(*) AS cve_count, MAX(cv.severity) AS max_severity, MAX(cv.exploitability) AS max_exploitability, MAX(cv.patch_availability) AS max_patch FROM cve_software cs JOIN mv_cve_scores cv ON cv.id = cs.cve_id GROUP BY cs.software_id) agg ON agg.software_id = s.id""")
    op.execute("""CREATE MATERIALIZED VIEW mv_vendor_scores AS
        SELECT v.id, v.name, v.slug,
            LEAST(25, COALESCE(agg.max_severity, 0)) AS severity, LEAST(25, COALESCE(agg.max_exploitability, 0)) AS exploitability, LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int) AS exposure, COALESCE(agg.max_patch, 0) AS patch_availability,
            LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int) + COALESCE(agg.max_patch, 0)) AS composite_score,
            CASE WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int) + COALESCE(agg.max_patch, 0)) >= 70 THEN 'critical-risk' WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int) + COALESCE(agg.max_patch, 0)) >= 50 THEN 'high-risk' WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int) + COALESCE(agg.max_patch, 0)) >= 30 THEN 'moderate-risk' ELSE 'low-risk' END AS quality_tier
        FROM vendors v LEFT JOIN (SELECT cv.vendor_id, COUNT(DISTINCT cv.cve_id) AS cve_count, MAX(cs.severity) AS max_severity, MAX(cs.exploitability) AS max_exploitability, MAX(cs.patch_availability) AS max_patch FROM cve_vendors cv JOIN mv_cve_scores cs ON cs.id = cv.cve_id GROUP BY cv.vendor_id) agg ON agg.vendor_id = v.id""")
    op.execute("""CREATE MATERIALIZED VIEW mv_weakness_scores AS
        SELECT w.id, w.cwe_id, w.name, w.description, w.abstraction,
            LEAST(25, COALESCE(agg.max_severity, 0)) AS severity, LEAST(25, COALESCE(agg.max_exploitability, 0)) AS exploitability, LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int) AS exposure, COALESCE(agg.max_patch, 0) AS patch_availability,
            LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int) + COALESCE(agg.max_patch, 0)) AS composite_score,
            CASE WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int) + COALESCE(agg.max_patch, 0)) >= 70 THEN 'critical-risk' WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int) + COALESCE(agg.max_patch, 0)) >= 50 THEN 'high-risk' WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 3)::int) + COALESCE(agg.max_patch, 0)) >= 30 THEN 'moderate-risk' ELSE 'low-risk' END AS quality_tier
        FROM weaknesses w LEFT JOIN (SELECT cw.weakness_id, COUNT(DISTINCT cw.cve_id) AS cve_count, MAX(cs.severity) AS max_severity, MAX(cs.exploitability) AS max_exploitability, MAX(cs.patch_availability) AS max_patch FROM cve_weaknesses cw JOIN mv_cve_scores cs ON cs.id = cw.cve_id GROUP BY cw.weakness_id) agg ON agg.weakness_id = w.id""")
    op.execute("""CREATE MATERIALIZED VIEW mv_pattern_scores AS
        SELECT ap.id, ap.capec_id, ap.name, ap.description, ap.likelihood, ap.severity AS raw_severity,
            LEAST(25, COALESCE(agg.max_severity, 0)) AS severity, LEAST(25, COALESCE(agg.max_exploitability, 0)) AS exploitability, LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2.5)::int) AS exposure, COALESCE(agg.max_patch, 0) AS patch_availability,
            LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2.5)::int) + COALESCE(agg.max_patch, 0)) AS composite_score,
            CASE WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2.5)::int) + COALESCE(agg.max_patch, 0)) >= 70 THEN 'critical-risk' WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2.5)::int) + COALESCE(agg.max_patch, 0)) >= 50 THEN 'high-risk' WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2.5)::int) + COALESCE(agg.max_patch, 0)) >= 30 THEN 'moderate-risk' ELSE 'low-risk' END AS quality_tier
        FROM attack_patterns ap LEFT JOIN (SELECT wp.pattern_id, COUNT(DISTINCT cw.cve_id) AS cve_count, MAX(cs.severity) AS max_severity, MAX(cs.exploitability) AS max_exploitability, MAX(cs.patch_availability) AS max_patch FROM weakness_patterns wp JOIN cve_weaknesses cw ON cw.weakness_id = wp.weakness_id JOIN mv_cve_scores cs ON cs.id = cw.cve_id GROUP BY wp.pattern_id) agg ON agg.pattern_id = ap.id""")
    op.execute("""CREATE MATERIALIZED VIEW mv_technique_scores AS
        SELECT t.id, t.technique_id, t.name, t.description, t.platforms, t.detection,
            LEAST(25, COALESCE(agg.max_severity, 0)) AS severity, LEAST(25, COALESCE(agg.max_exploitability, 0)) AS exploitability, LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2)::int) AS exposure, COALESCE(agg.max_patch, 0) AS patch_availability,
            LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2)::int) + COALESCE(agg.max_patch, 0)) AS composite_score,
            CASE WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2)::int) + COALESCE(agg.max_patch, 0)) >= 70 THEN 'critical-risk' WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2)::int) + COALESCE(agg.max_patch, 0)) >= 50 THEN 'high-risk' WHEN LEAST(100, LEAST(25, COALESCE(agg.max_severity, 0)) + LEAST(25, COALESCE(agg.max_exploitability, 0)) + LEAST(25, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 2)::int) + COALESCE(agg.max_patch, 0)) >= 30 THEN 'moderate-risk' ELSE 'low-risk' END AS quality_tier
        FROM techniques t LEFT JOIN (SELECT pt.technique_id, COUNT(DISTINCT cw.cve_id) AS cve_count, MAX(cs.severity) AS max_severity, MAX(cs.exploitability) AS max_exploitability, MAX(cs.patch_availability) AS max_patch FROM pattern_techniques pt JOIN weakness_patterns wp ON wp.pattern_id = pt.pattern_id JOIN cve_weaknesses cw ON cw.weakness_id = wp.weakness_id JOIN mv_cve_scores cs ON cs.id = cw.cve_id GROUP BY pt.technique_id) agg ON agg.technique_id = t.id""")
    op.execute("""CREATE MATERIALIZED VIEW mv_entity_summary AS
        SELECT 'cves' AS entity_type, COUNT(*) AS total, COUNT(*) FILTER (WHERE quality_tier = 'critical-risk') AS critical_risk, COUNT(*) FILTER (WHERE quality_tier = 'high-risk') AS high_risk, COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk') AS moderate_risk, COUNT(*) FILTER (WHERE quality_tier = 'low-risk') AS low_risk FROM mv_cve_scores
        UNION ALL SELECT 'software', COUNT(*), COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'), COUNT(*) FILTER (WHERE quality_tier = 'high-risk'), COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'), COUNT(*) FILTER (WHERE quality_tier = 'low-risk') FROM mv_software_scores
        UNION ALL SELECT 'vendors', COUNT(*), COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'), COUNT(*) FILTER (WHERE quality_tier = 'high-risk'), COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'), COUNT(*) FILTER (WHERE quality_tier = 'low-risk') FROM mv_vendor_scores
        UNION ALL SELECT 'weaknesses', COUNT(*), COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'), COUNT(*) FILTER (WHERE quality_tier = 'high-risk'), COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'), COUNT(*) FILTER (WHERE quality_tier = 'low-risk') FROM mv_weakness_scores
        UNION ALL SELECT 'techniques', COUNT(*), COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'), COUNT(*) FILTER (WHERE quality_tier = 'high-risk'), COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'), COUNT(*) FILTER (WHERE quality_tier = 'low-risk') FROM mv_technique_scores
        UNION ALL SELECT 'attack_patterns', COUNT(*), COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'), COUNT(*) FILTER (WHERE quality_tier = 'high-risk'), COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'), COUNT(*) FILTER (WHERE quality_tier = 'low-risk') FROM mv_pattern_scores""")

    # Unique indexes for CONCURRENT refresh
    for view in ["mv_software_scores", "mv_vendor_scores", "mv_weakness_scores",
                 "mv_pattern_scores", "mv_technique_scores"]:
        op.execute(f"CREATE UNIQUE INDEX ON {view} (id)")


def downgrade():
    for view in ["mv_entity_summary", "mv_technique_scores", "mv_pattern_scores",
                 "mv_weakness_scores", "mv_vendor_scores", "mv_software_scores",
                 "mv_cve_scores", "mv_cve_exploit_flags", "mv_cve_software_counts"]:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view}")
