"""Wilson score lower bounds for all proportion-based MVs + product_metadata.

Revision ID: 014
Revises: 013
Create Date: 2026-04-14

Raw proportions give unearned certainty to small samples: a product with
2 CVEs both exploited scored 100/100 — same as one with 600/600. The Wilson
score interval lower bound accounts for sample size: 2/2 → ~15% credible
rate, 600/600 → ~99%. This is the same math Reddit uses for ranking.

Formula: (p + z²/2n - z√((p(1-p) + z²/4n)/n)) / (1 + z²/n)
z = 1.96 (95% confidence), z² = 3.8416

Also creates product_metadata table for embedding-based categories,
peer comparisons, and human-readable risk guidance.

Tested against production DB:
- Chrome (2758 CVEs): 11 low — 3.3% Wilson EPSS vs 4% raw
- D-Link Dir-880L (9 CVEs): 36 moderate — 12% Wilson EPSS vs 33% raw
- Siemens Acuson (6 CVEs): 100 critical — 61% Wilson, still caps both dims
- Wall-of-100s: 347 → 183 products at score 100
"""
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None

# Wilson lower bound SQL fragment. Expects: p (proportion 0-1), n (count).
# Returns credible lower bound at 95% confidence.
# GREATEST(0, ...) prevents negative values for very small p.
WILSON = """GREATEST(0, ({p} + 1.9208/{n}
    - 1.96 * SQRT(({p} * (1 - {p}) + 0.9604/{n}) / {n}))
    / (1 + 3.8416/{n}))"""

# Scoring from Wilson-adjusted proportions
ACTIVE_THREAT_50 = "LEAST(50, (w_epss * 200)::int)"
EXPLOIT_AVAIL_50 = "LEAST(50, (w_kev * 150 + w_exploit * 150)::int)"


def _wilson(p_expr: str, n_expr: str) -> str:
    """Generate Wilson lower bound SQL for a proportion column."""
    return WILSON.format(p=p_expr, n=n_expr)


def upgrade():
    # ------------------------------------------------------------------
    # Drop proportion-based MVs (keep CVE + software, they don't use Wilson)
    # ------------------------------------------------------------------
    for view in [
        "mv_entity_summary",
        "mv_technique_scores", "mv_pattern_scores",
        "mv_weakness_scores", "mv_vendor_scores",
        "mv_product_scores",
    ]:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view}")

    # ------------------------------------------------------------------
    # mv_product_scores: Wilson-adjusted proportions
    # ------------------------------------------------------------------
    w_epss = _wilson("pct_high_epss / 100.0", "cve_count")
    w_kev = _wilson("pct_kev / 100.0", "cve_count")
    w_exploit = _wilson("pct_exploited / 100.0", "cve_count")

    op.execute(f"""
        CREATE MATERIALIZED VIEW mv_product_scores AS
        WITH product_cves AS (
            SELECT split_part(s.cpe_id, ':', 4) AS vendor_key,
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
            SELECT vendor_key, product_key,
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
            SELECT vendor_key || '/' || product_key AS id,
                vendor_key, product_key, display_name,
                vendor_id, vendor_name, vendor_slug, part,
                cve_count, high_epss_count, kev_count, exploit_count,
                max_epss, latest_cve_date,
                pct_high_epss, pct_kev, pct_exploited,
                {w_epss} AS w_epss,
                {w_kev} AS w_kev,
                {w_exploit} AS w_exploit,
                {ACTIVE_THREAT_50} AS active_threat,
                {EXPLOIT_AVAIL_50} AS exploit_availability
            FROM product_agg
        )
        SELECT s.*,
            LEAST(100, s.active_threat + s.exploit_availability) AS composite_score,
            CASE
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 70 THEN 'critical-risk'
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 50 THEN 'high-risk'
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM scored s
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_product_scores (id)")

    # ------------------------------------------------------------------
    # mv_vendor_scores: Wilson-adjusted
    # ------------------------------------------------------------------
    w_epss_v = _wilson("pct_high_epss / 100.0", "cve_count")
    w_kev_v = _wilson("pct_kev / 100.0", "cve_count")
    w_exploit_v = _wilson("pct_exploited / 100.0", "cve_count")

    op.execute(f"""
        CREATE MATERIALIZED VIEW mv_vendor_scores AS
        WITH vendor_cves AS (
            SELECT cv.vendor_id, c.id AS cve_id, c.epss_score, c.is_kev,
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
            FROM vendor_cves GROUP BY vendor_id
        ),
        scored AS (
            SELECT vendor_id, cve_count, high_epss_count, kev_count, exploit_count,
                pct_high_epss, pct_kev, pct_exploited,
                {w_epss_v} AS w_epss, {w_kev_v} AS w_kev, {w_exploit_v} AS w_exploit,
                {ACTIVE_THREAT_50} AS active_threat,
                {EXPLOIT_AVAIL_50} AS exploit_availability
            FROM vendor_agg
        )
        SELECT v.id, v.name, v.slug,
            s.cve_count, s.high_epss_count, s.kev_count, s.exploit_count,
            s.pct_high_epss, s.pct_kev, s.pct_exploited,
            s.active_threat, s.exploit_availability,
            LEAST(100, s.active_threat + s.exploit_availability) AS composite_score,
            CASE
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 70 THEN 'critical-risk'
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 50 THEN 'high-risk'
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM vendors v JOIN scored s ON s.vendor_id = v.id
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_vendor_scores (id)")

    # ------------------------------------------------------------------
    # mv_weakness_scores: Wilson-adjusted
    # ------------------------------------------------------------------
    w_epss_w = _wilson("pct_high_epss / 100.0", "cve_count")
    w_kev_w = _wilson("pct_kev / 100.0", "cve_count")
    w_exploit_w = _wilson("pct_exploited / 100.0", "cve_count")

    op.execute(f"""
        CREATE MATERIALIZED VIEW mv_weakness_scores AS
        WITH weakness_cves AS (
            SELECT cw.weakness_id, c.id AS cve_id, c.epss_score, c.is_kev,
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
            FROM weakness_cves GROUP BY weakness_id
        ),
        scored AS (
            SELECT weakness_id, cve_count, high_epss_count, kev_count, exploit_count,
                pct_high_epss, pct_kev, pct_exploited,
                {w_epss_w} AS w_epss, {w_kev_w} AS w_kev, {w_exploit_w} AS w_exploit,
                {ACTIVE_THREAT_50} AS active_threat,
                {EXPLOIT_AVAIL_50} AS exploit_availability
            FROM weakness_agg
        )
        SELECT w.id, w.cwe_id, w.name, w.description, w.abstraction,
            s.cve_count, s.high_epss_count, s.kev_count, s.exploit_count,
            s.pct_high_epss, s.pct_kev, s.pct_exploited,
            s.active_threat, s.exploit_availability,
            LEAST(100, s.active_threat + s.exploit_availability) AS composite_score,
            CASE
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 70 THEN 'critical-risk'
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 50 THEN 'high-risk'
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM weaknesses w JOIN scored s ON s.weakness_id = w.id
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_weakness_scores (id)")

    # ------------------------------------------------------------------
    # mv_pattern_scores: Wilson-adjusted
    # ------------------------------------------------------------------
    w_epss_p = _wilson("pct_high_epss / 100.0", "cve_count")
    w_kev_p = _wilson("pct_kev / 100.0", "cve_count")
    w_exploit_p = _wilson("pct_exploited / 100.0", "cve_count")

    op.execute(f"""
        CREATE MATERIALIZED VIEW mv_pattern_scores AS
        WITH pattern_cves AS (
            SELECT wp.pattern_id, c.id AS cve_id, c.epss_score, c.is_kev,
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
            FROM pattern_cves GROUP BY pattern_id
        ),
        scored AS (
            SELECT pattern_id, cve_count, high_epss_count, kev_count, exploit_count,
                pct_high_epss, pct_kev, pct_exploited,
                {w_epss_p} AS w_epss, {w_kev_p} AS w_kev, {w_exploit_p} AS w_exploit,
                {ACTIVE_THREAT_50} AS active_threat,
                {EXPLOIT_AVAIL_50} AS exploit_availability
            FROM pattern_agg
        )
        SELECT ap.id, ap.capec_id, ap.name, ap.description,
            ap.likelihood, ap.severity AS raw_severity,
            s.cve_count, s.high_epss_count, s.kev_count, s.exploit_count,
            s.pct_high_epss, s.pct_kev, s.pct_exploited,
            s.active_threat, s.exploit_availability,
            LEAST(100, s.active_threat + s.exploit_availability) AS composite_score,
            CASE
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 70 THEN 'critical-risk'
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 50 THEN 'high-risk'
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM attack_patterns ap JOIN scored s ON s.pattern_id = ap.id
    """)
    op.execute("CREATE UNIQUE INDEX ON mv_pattern_scores (id)")

    # ------------------------------------------------------------------
    # mv_technique_scores: Wilson-adjusted
    # ------------------------------------------------------------------
    w_epss_t = _wilson("pct_high_epss / 100.0", "cve_count")
    w_kev_t = _wilson("pct_kev / 100.0", "cve_count")
    w_exploit_t = _wilson("pct_exploited / 100.0", "cve_count")

    op.execute(f"""
        CREATE MATERIALIZED VIEW mv_technique_scores AS
        WITH technique_cves AS (
            SELECT pt.technique_id AS tech_id, c.id AS cve_id, c.epss_score, c.is_kev,
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
            FROM technique_cves GROUP BY tech_id
        ),
        scored AS (
            SELECT tech_id, cve_count, high_epss_count, kev_count, exploit_count,
                pct_high_epss, pct_kev, pct_exploited,
                {w_epss_t} AS w_epss, {w_kev_t} AS w_kev, {w_exploit_t} AS w_exploit,
                {ACTIVE_THREAT_50} AS active_threat,
                {EXPLOIT_AVAIL_50} AS exploit_availability
            FROM technique_agg
        )
        SELECT t.id, t.technique_id, t.name, t.description, t.platforms, t.detection,
            s.cve_count, s.high_epss_count, s.kev_count, s.exploit_count,
            s.pct_high_epss, s.pct_kev, s.pct_exploited,
            s.active_threat, s.exploit_availability,
            LEAST(100, s.active_threat + s.exploit_availability) AS composite_score,
            CASE
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 70 THEN 'critical-risk'
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 50 THEN 'high-risk'
                WHEN LEAST(100, s.active_threat + s.exploit_availability) >= 30 THEN 'moderate-risk'
                ELSE 'low-risk'
            END AS quality_tier
        FROM techniques t JOIN scored s ON s.tech_id = t.id
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

    # ------------------------------------------------------------------
    # product_metadata table for embeddings, categories, guidance
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS product_metadata (
            vendor_key TEXT NOT NULL,
            product_key TEXT NOT NULL,
            embedding vector(1536),
            category TEXT,
            category_label TEXT,
            risk_summary TEXT,
            recommended_actions JSONB,
            peer_products JSONB,
            updated_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (vendor_key, product_key)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_product_metadata_category ON product_metadata (category)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS product_metadata")
    # Proportion-based MVs restored by re-running 013
    for view in [
        "mv_entity_summary",
        "mv_technique_scores", "mv_pattern_scores",
        "mv_weakness_scores", "mv_vendor_scores",
        "mv_product_scores",
    ]:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view}")
