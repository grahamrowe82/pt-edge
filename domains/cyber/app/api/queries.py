"""Query helpers for the REST API. All queries use the readonly engine."""

from datetime import datetime

from sqlalchemy import text

from domains.cyber.app.db import readonly_engine


def serialize_row(row) -> dict:
    """Convert a SQLAlchemy Row to a JSON-safe dict."""
    d = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, (float, int)):
            d[k] = v
    return d


def search_cves(q: str | None = None, min_severity: float | None = None,
                kev_only: bool = False, limit: int = 20) -> list[dict]:
    """Search CVEs by keyword, severity, or KEV status."""
    conditions = ["c.cvss_base_score IS NOT NULL"]
    params = {"lim": min(limit, 100)}

    if q:
        conditions.append("(c.cve_id ILIKE :q OR c.description ILIKE :q)")
        params["q"] = f"%{q}%"
    if min_severity is not None:
        conditions.append("c.cvss_base_score >= :sev")
        params["sev"] = min_severity
    if kev_only:
        conditions.append("c.is_kev = true")

    where = " AND ".join(conditions)
    with readonly_engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT c.cve_id, c.description, c.cvss_base_score, c.epss_score,
                   c.is_kev, c.attack_vector, cs.composite_score, cs.quality_tier,
                   cs.severity, cs.exploitability, cs.exposure
            FROM cves c
            LEFT JOIN mv_cve_scores cs ON cs.id = c.id
            WHERE {where}
            ORDER BY cs.composite_score DESC NULLS LAST
            LIMIT :lim
        """), params).fetchall()
    return [serialize_row(r) for r in rows]


def get_cve(cve_id: str) -> dict | None:
    """Get a single CVE by ID with full details."""
    with readonly_engine.connect() as conn:
        row = conn.execute(text("""
            SELECT c.*, cs.composite_score, cs.quality_tier,
                   cs.severity, cs.exploitability, cs.exposure
            FROM cves c
            LEFT JOIN mv_cve_scores cs ON cs.id = c.id
            WHERE c.cve_id = :cid
        """), {"cid": cve_id}).fetchone()
    return serialize_row(row) if row else None


def search_software(q: str | None = None, limit: int = 20) -> list[dict]:
    with readonly_engine.connect() as conn:
        params = {"lim": min(limit, 100)}
        where = "1=1"
        if q:
            where = "s.name ILIKE :q"
            params["q"] = f"%{q}%"
        rows = conn.execute(text(f"""
            SELECT s.name, s.cpe_id, ss.composite_score, ss.quality_tier,
                   ss.severity, ss.exploitability, ss.exposure
            FROM software s
            LEFT JOIN mv_software_scores ss ON ss.id = s.id
            WHERE {where}
            ORDER BY ss.composite_score DESC NULLS LAST
            LIMIT :lim
        """), params).fetchall()
    return [serialize_row(r) for r in rows]


def search_vendors(q: str | None = None, limit: int = 20) -> list[dict]:
    with readonly_engine.connect() as conn:
        params = {"lim": min(limit, 100)}
        where = "1=1"
        if q:
            where = "v.name ILIKE :q"
            params["q"] = f"%{q}%"
        rows = conn.execute(text(f"""
            SELECT v.name, v.slug, vs.composite_score, vs.quality_tier,
                   vs.active_threat, vs.exploit_availability
            FROM vendors v
            LEFT JOIN mv_vendor_scores vs ON vs.id = v.id
            WHERE {where}
            ORDER BY vs.composite_score DESC NULLS LAST
            LIMIT :lim
        """), params).fetchall()
    return [serialize_row(r) for r in rows]


def search_weaknesses(q: str | None = None, limit: int = 20) -> list[dict]:
    with readonly_engine.connect() as conn:
        params = {"lim": min(limit, 100)}
        where = "1=1"
        if q:
            where = "(w.cwe_id ILIKE :q OR w.name ILIKE :q)"
            params["q"] = f"%{q}%"
        rows = conn.execute(text(f"""
            SELECT w.cwe_id, w.name, ws.composite_score, ws.quality_tier,
                   ws.active_threat, ws.exploit_availability
            FROM weaknesses w
            LEFT JOIN mv_weakness_scores ws ON ws.id = w.id
            WHERE {where}
            ORDER BY ws.composite_score DESC NULLS LAST
            LIMIT :lim
        """), params).fetchall()
    return [serialize_row(r) for r in rows]


def search_techniques(q: str | None = None, limit: int = 20) -> list[dict]:
    with readonly_engine.connect() as conn:
        params = {"lim": min(limit, 100)}
        where = "1=1"
        if q:
            where = "(t.technique_id ILIKE :q OR t.name ILIKE :q)"
            params["q"] = f"%{q}%"
        rows = conn.execute(text(f"""
            SELECT t.technique_id, t.name, ts.composite_score, ts.quality_tier,
                   ts.active_threat, ts.exploit_availability
            FROM techniques t
            LEFT JOIN mv_technique_scores ts ON ts.id = t.id
            WHERE {where}
            ORDER BY ts.composite_score DESC NULLS LAST
            LIMIT :lim
        """), params).fetchall()
    return [serialize_row(r) for r in rows]


def search_patterns(q: str | None = None, limit: int = 20) -> list[dict]:
    with readonly_engine.connect() as conn:
        params = {"lim": min(limit, 100)}
        where = "1=1"
        if q:
            where = "(ap.capec_id ILIKE :q OR ap.name ILIKE :q)"
            params["q"] = f"%{q}%"
        rows = conn.execute(text(f"""
            SELECT ap.capec_id, ap.name, ps.composite_score, ps.quality_tier,
                   ps.active_threat, ps.exploit_availability
            FROM attack_patterns ap
            LEFT JOIN mv_pattern_scores ps ON ps.id = ap.id
            WHERE {where}
            ORDER BY ps.composite_score DESC NULLS LAST
            LIMIT :lim
        """), params).fetchall()
    return [serialize_row(r) for r in rows]
