"""Product-level scores: aggregate CPE versions into logical products.

Revision ID: 012
Revises: 011
Create Date: 2026-04-13

The software table has version-specific CPE entries (cpe:2.3:a:google:chrome:80.*,
cpe:2.3:a:google:chrome:81.*, etc). This makes software pages useless — Chrome
appears hundreds of times and scores 100/100 because it rewards CVE volume.

Fix: GROUP BY (vendor_key, product_key) extracted from the CPE string to create
logical products. Score by *proportion* of dangerous CVEs (EPSS>10%, KEV, exploited),
not by volume.

Dimensions:
- Active Threat (0-25): proportion with high EPSS + small absolute bonus
- Exploit Availability (0-25): proportion exploited + KEV proportion
- Severity Profile (0-25): average CVSS across linked CVEs
- Recency (0-25): how recent are CVE disclosures

Tested against production DB:
- Chrome: 53 (high) — down from 100 (critical). 4% high-EPSS, 2.7% KEV.
- Windows Server 2012: 78 (critical). 25% high-EPSS, 4.4% KEV, 4.8% exploited.
- Siemens Acuson firmware: 71 (critical). 100% across all danger signals.
- Linux Kernel: 44 (moderate). 11K CVEs but 0.5% dangerous.
"""
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade():
    # Drop entity summary (will recreate with product counts)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_entity_summary")

    # Product-level scores: aggregate CPE versions by (vendor_key, product_key)
    op.execute("""
        CREATE MATERIALIZED VIEW mv_product_scores AS
        WITH product_cves AS (
            SELECT
                split_part(s.cpe_id, ':', 4) AS vendor_key,
                split_part(s.cpe_id, ':', 5) AS product_key,
                s.vendor_id,
                s.part,
                s.name AS sw_name,
                v.name AS vendor_name,
                v.slug AS vendor_slug,
                c.id AS cve_id,
                c.cvss_base_score,
                c.epss_score,
                c.is_kev,
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
                MAX(vendor_id) AS vendor_id,
                MAX(part) AS part,
                MAX(sw_name) AS display_name,
                MAX(vendor_name) AS vendor_name,
                MAX(vendor_slug) AS vendor_slug,
                COUNT(DISTINCT cve_id) AS cve_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE epss_score > 0.1) AS high_epss_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE is_kev) AS kev_count,
                COUNT(DISTINCT cve_id) FILTER (WHERE has_exploit) AS exploit_count,
                ROUND(AVG(cvss_base_score)::numeric, 1) AS avg_cvss,
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
                avg_cvss, max_epss, latest_cve_date,
                pct_high_epss, pct_kev, pct_exploited,
                -- Active Threat (0-25): EPSS proportion + absolute bonus
                LEAST(25, (
                    pct_high_epss * 0.8
                    + LEAST(5, LN(high_epss_count + 1) * 0.7)
                )::int) AS active_threat,
                -- Exploit Availability (0-25): exploit proportion + KEV proportion
                LEAST(25, (
                    LEAST(15, pct_exploited * 1.5)
                    + LEAST(10, pct_kev * 0.6)
                )::int) AS exploit_availability,
                -- Severity Profile (0-25): average CVSS
                LEAST(25, (avg_cvss * 2.5)::int) AS severity_profile,
                -- Recency (0-25): years since latest CVE
                LEAST(25, GREATEST(0, (
                    25 - EXTRACT(YEAR FROM age(now(), latest_cve_date)) * 3
                )::int)) AS recency
            FROM product_agg
        )
        SELECT
            s.*,
            LEAST(100, s.active_threat + s.exploit_availability
                + s.severity_profile + s.recency) AS composite_score,
            CASE
                WHEN LEAST(100, s.active_threat + s.exploit_availability
                    + s.severity_profile + s.recency) >= 70 THEN 'critical-risk'
                WHEN LEAST(100, s.active_threat + s.exploit_availability
                    + s.severity_profile + s.recency) >= 50 THEN 'high-risk'
                WHEN LEAST(100, s.active_threat + s.exploit_availability
                    + s.severity_profile + s.recency) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM scored s
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_product_scores (id)")

    # Rebuild entity summary with product counts
    op.execute("""CREATE MATERIALIZED VIEW mv_entity_summary AS
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
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_entity_summary")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_product_scores")
    # Restore entity summary without products
    op.execute("""CREATE MATERIALIZED VIEW mv_entity_summary AS
        SELECT 'cves' AS entity_type, COUNT(*) AS total,
            COUNT(*) FILTER (WHERE quality_tier = 'critical-risk') AS critical_risk,
            COUNT(*) FILTER (WHERE quality_tier = 'high-risk') AS high_risk,
            COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk') AS moderate_risk,
            COUNT(*) FILTER (WHERE quality_tier = 'low-risk') AS low_risk
        FROM mv_cve_scores
        UNION ALL SELECT 'software', COUNT(*),
            COUNT(*) FILTER (WHERE quality_tier = 'critical-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'high-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'moderate-risk'),
            COUNT(*) FILTER (WHERE quality_tier = 'low-risk')
        FROM mv_software_scores
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
