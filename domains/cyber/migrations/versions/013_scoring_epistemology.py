"""Fix epistemological errors in all scoring materialized views.

Revision ID: 013
Revises: 012
Create Date: 2026-04-13

Three categories of fix:

1. CVE scoring: drop patch_availability (has_fix only covers 0.3% of CVEs,
   giving 99.7% maximum "no patch" score — pure noise). Rescale remaining
   3 dimensions (severity, exploitability, exposure) from 0-25 each to
   0-33/34 each so composite still reaches 0-100.

2. Product scoring: drop severity_profile (avg CVSS) and recency (latest CVE
   age). Both are noise — high CVSS and recent CVEs indicate active
   maintenance (Chrome), not danger. Keep only active_threat and
   exploit_availability, rescaled to 0-50 each.

3. Vendor/weakness/pattern/technique scoring: rewrite from MAX-based
   (one extreme CVE makes everything critical) to proportion-based
   (same 2-dimension pattern as products). This fixes the clustering
   problem where every major entity scored critical.

Tested against production DB:
- Products: Chrome 21 (low), Windows Server 2012 71 (critical),
  Siemens Acuson 100 (critical)
- Vendors: no longer all clustered at critical
- Weaknesses: CWE-79 (XSS) differentiates from CWE-787 (OOB Write)
"""
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

# Helper for the tier CASE expression
TIER_CASE = """
    CASE
        WHEN {score} >= 70 THEN 'critical-risk'
        WHEN {score} >= 50 THEN 'high-risk'
        WHEN {score} >= 30 THEN 'moderate-risk'
        ELSE 'low-risk'
    END
"""

# The two-dimension proportion-based scoring formula used by
# products, vendors, weaknesses, patterns, and techniques.
# Expects CTEs to provide: pct_high_epss, pct_kev, pct_exploited, high_epss_count
ACTIVE_THREAT_50 = "LEAST(50, (pct_high_epss * 2 + LEAST(10, LN(high_epss_count + 1) * 1.4))::int)"
EXPLOIT_AVAIL_50 = "LEAST(50, (LEAST(30, pct_exploited * 3) + LEAST(20, pct_kev * 1.5))::int)"
COMPOSITE_2DIM = f"LEAST(100, {ACTIVE_THREAT_50} + {EXPLOIT_AVAIL_50})"


def upgrade():
    # ------------------------------------------------------------------
    # Drop all scoring MVs in reverse dependency order
    # (keep mv_cve_software_counts and mv_cve_exploit_flags — unchanged)
    # ------------------------------------------------------------------
    for view in [
        "mv_entity_summary",
        "mv_technique_scores", "mv_pattern_scores",
        "mv_weakness_scores", "mv_vendor_scores",
        "mv_software_scores",
        "mv_product_scores",
        "mv_cve_scores",
    ]:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view}")

    # ------------------------------------------------------------------
    # mv_cve_scores: 3 dimensions (no patch_availability), rescaled to 0-100
    # ------------------------------------------------------------------
    op.execute("""
        CREATE MATERIALIZED VIEW mv_cve_scores AS
        WITH scored AS (
            SELECT
                c.id, c.cve_id,
                c.description, c.cvss_base_score, c.epss_score, c.is_kev,
                c.attack_vector, c.published_date,
                -- Severity (0-33): CVSS-based
                LEAST(33, (
                    COALESCE(c.cvss_base_score, 0) * 2.6
                    + CASE WHEN c.attack_complexity = 'LOW' THEN 4 ELSE 0 END
                    + CASE WHEN c.attack_vector = 'NETWORK' THEN 3 ELSE 0 END
                )::int) AS severity,
                -- Exploitability (0-34): EPSS + KEV + Exploit-DB
                LEAST(34, (
                    LEAST(20, (LN(COALESCE(c.epss_score, 0) * 100 + 1) * 4.5)::int)
                    + CASE WHEN c.is_kev THEN 7 ELSE 0 END
                    + CASE WHEN ef.cve_id IS NOT NULL THEN 7 ELSE 0 END
                )::int) AS exploitability,
                -- Exposure (0-33): software count
                LEAST(33, (LN(GREATEST(1, COALESCE(sc.cnt, 0)) + 1) * 6.5)::int) AS exposure
            FROM cves c
            LEFT JOIN mv_cve_software_counts sc ON sc.cve_id = c.id
            LEFT JOIN mv_cve_exploit_flags ef ON ef.cve_id = c.id
            WHERE c.cvss_base_score IS NOT NULL
        )
        SELECT s.*,
            LEAST(100, s.severity + s.exploitability + s.exposure) AS composite_score,
            CASE
                WHEN LEAST(100, s.severity + s.exploitability + s.exposure) >= 70 THEN 'critical-risk'
                WHEN LEAST(100, s.severity + s.exploitability + s.exposure) >= 50 THEN 'high-risk'
                WHEN LEAST(100, s.severity + s.exploitability + s.exposure) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM scored s
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_cve_scores (id)")

    # ------------------------------------------------------------------
    # mv_product_scores: 2 dimensions (active_threat + exploit_availability)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE MATERIALIZED VIEW mv_product_scores AS
        WITH product_cves AS (
            SELECT
                split_part(s.cpe_id, ':', 4) AS vendor_key,
                split_part(s.cpe_id, ':', 5) AS product_key,
                s.vendor_id, s.part, s.name AS sw_name,
                v.name AS vendor_name, v.slug AS vendor_slug,
                c.id AS cve_id, c.cvss_base_score, c.epss_score, c.is_kev,
                c.published_date,
                ef.cve_id IS NOT NULL AS has_exploit
            FROM software s
            JOIN cve_software cs ON cs.software_id = s.id
            JOIN cves c ON c.id = cs.cve_id
            JOIN vendors v ON v.id = s.vendor_id
            LEFT JOIN mv_cve_exploit_flags ef ON ef.cve_id = c.id
            WHERE c.cvss_base_score IS NOT NULL
        ),
        product_agg AS (
            SELECT
                vendor_key, product_key,
                MAX(vendor_id) AS vendor_id, MAX(part) AS part,
                MAX(sw_name) AS display_name,
                MAX(vendor_name) AS vendor_name, MAX(vendor_slug) AS vendor_slug,
                COUNT(DISTINCT cve_id) AS cve_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE epss_score > 0.1) AS high_epss_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE is_kev) AS kev_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE has_exploit) AS exploit_count,
                MAX(epss_score) AS max_epss,
                MAX(published_date) AS latest_cve_date,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE epss_score > 0.1)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_high_epss,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE is_kev)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_kev,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE has_exploit)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_exploited
            FROM product_cves
            GROUP BY vendor_key, product_key
        ),
        scored AS (
            SELECT
                vendor_key || '/' || product_key AS id,
                vendor_key, product_key, display_name,
                vendor_id, vendor_name, vendor_slug, part,
                cve_count, high_epss_count, kev_count, exploit_count,
                max_epss, latest_cve_date,
                pct_high_epss, pct_kev, pct_exploited,
                """ + ACTIVE_THREAT_50 + """ AS active_threat,
                """ + EXPLOIT_AVAIL_50 + """ AS exploit_availability
            FROM product_agg
        )
        SELECT s.*,
            LEAST(100, s.active_threat + s.exploit_availability) AS composite_score,
            """ + TIER_CASE.format(score="LEAST(100, s.active_threat + s.exploit_availability)") + """ AS quality_tier
        FROM scored s
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_product_scores (id)")

    # ------------------------------------------------------------------
    # mv_software_scores: 3 dimensions aligned with new mv_cve_scores
    # (kept for snapshot compatibility, not used for page generation)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE MATERIALIZED VIEW mv_software_scores AS
        SELECT s.id, s.cpe_id, s.name,
            LEAST(33, COALESCE(agg.max_severity, 0)) AS severity,
            LEAST(34, COALESCE(agg.max_exploitability, 0)) AS exploitability,
            LEAST(33, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 5.5)::int) AS exposure,
            LEAST(100,
                LEAST(33, COALESCE(agg.max_severity, 0))
                + LEAST(34, COALESCE(agg.max_exploitability, 0))
                + LEAST(33, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 5.5)::int)
            ) AS composite_score,
            CASE
                WHEN LEAST(100,
                    LEAST(33, COALESCE(agg.max_severity, 0))
                    + LEAST(34, COALESCE(agg.max_exploitability, 0))
                    + LEAST(33, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 5.5)::int)
                ) >= 70 THEN 'critical-risk'
                WHEN LEAST(100,
                    LEAST(33, COALESCE(agg.max_severity, 0))
                    + LEAST(34, COALESCE(agg.max_exploitability, 0))
                    + LEAST(33, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 5.5)::int)
                ) >= 50 THEN 'high-risk'
                WHEN LEAST(100,
                    LEAST(33, COALESCE(agg.max_severity, 0))
                    + LEAST(34, COALESCE(agg.max_exploitability, 0))
                    + LEAST(33, (LN(GREATEST(1, COALESCE(agg.cve_count, 0)) + 1) * 5.5)::int)
                ) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM software s
        LEFT JOIN (
            SELECT cs.software_id, COUNT(*) AS cve_count,
                MAX(cv.severity) AS max_severity,
                MAX(cv.exploitability) AS max_exploitability
            FROM cve_software cs
            JOIN mv_cve_scores cv ON cv.id = cs.cve_id
            GROUP BY cs.software_id
        ) agg ON agg.software_id = s.id
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_software_scores (id)")

    # ------------------------------------------------------------------
    # mv_vendor_scores: proportion-based (2 dimensions)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE MATERIALIZED VIEW mv_vendor_scores AS
        WITH vendor_cves AS (
            SELECT cv.vendor_id, c.id AS cve_id,
                c.epss_score, c.is_kev,
                ef.cve_id IS NOT NULL AS has_exploit
            FROM cve_vendors cv
            JOIN cves c ON c.id = cv.cve_id
            LEFT JOIN mv_cve_exploit_flags ef ON ef.cve_id = c.id
            WHERE c.cvss_base_score IS NOT NULL
        ),
        vendor_agg AS (
            SELECT vendor_id,
                COUNT(DISTINCT cve_id) AS cve_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE epss_score > 0.1) AS high_epss_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE is_kev) AS kev_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE has_exploit) AS exploit_count,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE epss_score > 0.1)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_high_epss,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE is_kev)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_kev,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE has_exploit)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_exploited
            FROM vendor_cves
            GROUP BY vendor_id
        )
        SELECT v.id, v.name, v.slug,
            a.cve_count, a.high_epss_count, a.kev_count, a.exploit_count,
            a.pct_high_epss, a.pct_kev, a.pct_exploited,
            """ + ACTIVE_THREAT_50 + """ AS active_threat,
            """ + EXPLOIT_AVAIL_50 + """ AS exploit_availability,
            """ + COMPOSITE_2DIM + """ AS composite_score,
            """ + TIER_CASE.format(score=COMPOSITE_2DIM) + """ AS quality_tier
        FROM vendors v
        JOIN vendor_agg a ON a.vendor_id = v.id
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_vendor_scores (id)")

    # ------------------------------------------------------------------
    # mv_weakness_scores: proportion-based (2 dimensions)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE MATERIALIZED VIEW mv_weakness_scores AS
        WITH weakness_cves AS (
            SELECT cw.weakness_id, c.id AS cve_id,
                c.epss_score, c.is_kev,
                ef.cve_id IS NOT NULL AS has_exploit
            FROM cve_weaknesses cw
            JOIN cves c ON c.id = cw.cve_id
            LEFT JOIN mv_cve_exploit_flags ef ON ef.cve_id = c.id
            WHERE c.cvss_base_score IS NOT NULL
        ),
        weakness_agg AS (
            SELECT weakness_id,
                COUNT(DISTINCT cve_id) AS cve_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE epss_score > 0.1) AS high_epss_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE is_kev) AS kev_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE has_exploit) AS exploit_count,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE epss_score > 0.1)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_high_epss,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE is_kev)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_kev,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE has_exploit)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_exploited
            FROM weakness_cves
            GROUP BY weakness_id
        )
        SELECT w.id, w.cwe_id, w.name, w.description, w.abstraction,
            a.cve_count, a.high_epss_count, a.kev_count, a.exploit_count,
            a.pct_high_epss, a.pct_kev, a.pct_exploited,
            """ + ACTIVE_THREAT_50 + """ AS active_threat,
            """ + EXPLOIT_AVAIL_50 + """ AS exploit_availability,
            """ + COMPOSITE_2DIM + """ AS composite_score,
            """ + TIER_CASE.format(score=COMPOSITE_2DIM) + """ AS quality_tier
        FROM weaknesses w
        JOIN weakness_agg a ON a.weakness_id = w.id
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_weakness_scores (id)")

    # ------------------------------------------------------------------
    # mv_pattern_scores: proportion-based (2 dimensions)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE MATERIALIZED VIEW mv_pattern_scores AS
        WITH pattern_cves AS (
            SELECT wp.pattern_id, c.id AS cve_id,
                c.epss_score, c.is_kev,
                ef.cve_id IS NOT NULL AS has_exploit
            FROM weakness_patterns wp
            JOIN cve_weaknesses cw ON cw.weakness_id = wp.weakness_id
            JOIN cves c ON c.id = cw.cve_id
            LEFT JOIN mv_cve_exploit_flags ef ON ef.cve_id = c.id
            WHERE c.cvss_base_score IS NOT NULL
        ),
        pattern_agg AS (
            SELECT pattern_id,
                COUNT(DISTINCT cve_id) AS cve_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE epss_score > 0.1) AS high_epss_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE is_kev) AS kev_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE has_exploit) AS exploit_count,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE epss_score > 0.1)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_high_epss,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE is_kev)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_kev,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE has_exploit)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_exploited
            FROM pattern_cves
            GROUP BY pattern_id
        )
        SELECT ap.id, ap.capec_id, ap.name, ap.description,
            ap.likelihood, ap.severity AS raw_severity,
            a.cve_count, a.high_epss_count, a.kev_count, a.exploit_count,
            a.pct_high_epss, a.pct_kev, a.pct_exploited,
            """ + ACTIVE_THREAT_50 + """ AS active_threat,
            """ + EXPLOIT_AVAIL_50 + """ AS exploit_availability,
            """ + COMPOSITE_2DIM + """ AS composite_score,
            """ + TIER_CASE.format(score=COMPOSITE_2DIM) + """ AS quality_tier
        FROM attack_patterns ap
        JOIN pattern_agg a ON a.pattern_id = ap.id
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_pattern_scores (id)")

    # ------------------------------------------------------------------
    # mv_technique_scores: proportion-based (2 dimensions)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE MATERIALIZED VIEW mv_technique_scores AS
        WITH technique_cves AS (
            SELECT pt.technique_id AS tech_id, c.id AS cve_id,
                c.epss_score, c.is_kev,
                ef.cve_id IS NOT NULL AS has_exploit
            FROM pattern_techniques pt
            JOIN weakness_patterns wp ON wp.pattern_id = pt.pattern_id
            JOIN cve_weaknesses cw ON cw.weakness_id = wp.weakness_id
            JOIN cves c ON c.id = cw.cve_id
            LEFT JOIN mv_cve_exploit_flags ef ON ef.cve_id = c.id
            WHERE c.cvss_base_score IS NOT NULL
        ),
        technique_agg AS (
            SELECT tech_id,
                COUNT(DISTINCT cve_id) AS cve_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE epss_score > 0.1) AS high_epss_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE is_kev) AS kev_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE has_exploit) AS exploit_count,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE epss_score > 0.1)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_high_epss,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE is_kev)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_kev,
                ROUND(100.0 * COUNT(DISTINCT cve_id) FILTER (WHERE has_exploit)
                    / NULLIF(COUNT(DISTINCT cve_id), 0), 1) AS pct_exploited
            FROM technique_cves
            GROUP BY tech_id
        )
        SELECT t.id, t.technique_id, t.name, t.description,
            t.platforms, t.detection,
            a.cve_count, a.high_epss_count, a.kev_count, a.exploit_count,
            a.pct_high_epss, a.pct_kev, a.pct_exploited,
            """ + ACTIVE_THREAT_50 + """ AS active_threat,
            """ + EXPLOIT_AVAIL_50 + """ AS exploit_availability,
            """ + COMPOSITE_2DIM + """ AS composite_score,
            """ + TIER_CASE.format(score=COMPOSITE_2DIM) + """ AS quality_tier
        FROM techniques t
        JOIN technique_agg a ON a.tech_id = t.id
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_technique_scores (id)")

    # ------------------------------------------------------------------
    # mv_entity_summary: rebuild
    # ------------------------------------------------------------------
    op.execute("""
        CREATE MATERIALIZED VIEW mv_entity_summary AS
        SELECT 'cves' AS entity_type, COUNT(*) AS total,
            COUNT(*) FILTER (WHERE quality_tier = 'critical-risk') AS critical_risk,
            COUNT(*) FILTER (WHERE quality_tier = 'high-risk') AS high_risk,
            COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk') AS moderate_risk,
            COUNT(*) FILTER (WHERE quality_tier = 'low-risk') AS low_risk
        FROM mv_cve_scores
        UNION ALL SELECT 'products', COUNT(*),
            COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'high-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'low-risk')
        FROM mv_product_scores
        UNION ALL SELECT 'vendors', COUNT(*),
            COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'high-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'low-risk')
        FROM mv_vendor_scores
        UNION ALL SELECT 'weaknesses', COUNT(*),
            COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'high-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'low-risk')
        FROM mv_weakness_scores
        UNION ALL SELECT 'techniques', COUNT(*),
            COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'high-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'low-risk')
        FROM mv_technique_scores
        UNION ALL SELECT 'attack_patterns', COUNT(*),
            COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'high-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'low-risk')
        FROM mv_pattern_scores
    """)


def downgrade():
    # Downgrade not implemented — previous MVs are in migrations 011+012
    pass
