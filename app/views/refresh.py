import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import engine
from app.db import SessionLocal
from app.models import SyncLog

logger = logging.getLogger(__name__)

VIEWS_IN_ORDER = [
    "mv_momentum",             # base: no dependencies
    "mv_hype_ratio",           # base: no dependencies
    "mv_lab_velocity",         # base: no dependencies
    "mv_project_tier",         # base: no dependencies
    "mv_velocity",             # base: no dependencies
    "mv_download_trends",      # base: no MV dependencies (uses download_snapshots)
    "mv_lifecycle",            # depends on: mv_momentum
    "mv_traction_score",       # depends on: mv_velocity, mv_download_trends
    "mv_project_summary",      # depends on: mv_momentum, mv_hype_ratio, mv_project_tier, mv_velocity, mv_lifecycle, mv_traction_score, mv_download_trends
    "mv_usage_sessions",       # standalone: tool_usage only
    "mv_usage_daily_summary",  # depends on: mv_usage_sessions
    "mv_ai_repo_ecosystem",    # standalone: ai_repos stats by domain+subcategory
    "mv_mcp_quality",          # standalone: quality scores for MCP-domain repos
    "mv_agents_quality",       # standalone: quality scores for agents-domain repos
    "mv_rag_quality",          # standalone: quality scores for rag-domain repos
    "mv_ai_coding_quality",    # standalone: quality scores for ai-coding-domain repos
    "mv_voice_ai_quality",     # standalone: quality scores for voice-ai-domain repos
    "mv_diffusion_quality",    # standalone: quality scores for diffusion-domain repos
    "mv_vector_db_quality",    # standalone: quality scores for vector-db-domain repos
    "mv_embeddings_quality",   # standalone: quality scores for embeddings-domain repos
    "mv_prompt_eng_quality",   # standalone: quality scores for prompt-engineering-domain repos
    "mv_ml_frameworks_quality",  # standalone: quality scores for ml-frameworks-domain repos
    "mv_llm_tools_quality",      # standalone: quality scores for llm-tools-domain repos
    "mv_nlp_quality",            # standalone: quality scores for nlp-domain repos
    "mv_transformers_quality",   # standalone: quality scores for transformers-domain repos
    "mv_generative_ai_quality",  # standalone: quality scores for generative-ai-domain repos
    "mv_computer_vision_quality",# standalone: quality scores for computer-vision-domain repos
    "mv_data_engineering_quality",# standalone: quality scores for data-engineering-domain repos
    "mv_mlops_quality",          # standalone: quality scores for mlops-domain repos
]


def refresh_all_views():
    """Refresh all materialized views in dependency order."""
    started_at = datetime.now(timezone.utc)
    refreshed = 0
    errors = []

    with engine.connect() as conn:
        for view_name in VIEWS_IN_ORDER:
            try:
                conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view_name}"))
                conn.commit()
                refreshed += 1
                logger.info(f"Refreshed {view_name}")
            except Exception as e:
                # CONCURRENTLY requires unique index; fall back to regular refresh
                conn.rollback()
                try:
                    conn.execute(text(f"REFRESH MATERIALIZED VIEW {view_name}"))
                    conn.commit()
                    refreshed += 1
                    logger.info(f"Refreshed {view_name} (non-concurrent)")
                except Exception as e2:
                    conn.rollback()
                    errors.append(f"{view_name}: {e2}")
                    logger.error(f"Failed to refresh {view_name}: {e2}")

    # Snapshot lifecycle stages for transition tracking
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO lifecycle_history (project_id, lifecycle_stage, snapshot_date)
                SELECT project_id, lifecycle_stage, CURRENT_DATE
                FROM mv_lifecycle
                ON CONFLICT (project_id, snapshot_date) DO UPDATE
                SET lifecycle_stage = EXCLUDED.lifecycle_stage
            """))
            conn.commit()
            logger.info("Snapshotted lifecycle stages to lifecycle_history")
    except Exception as e:
        logger.warning(f"Could not snapshot lifecycle stages: {e}")

    # Snapshot MCP quality scores for historical tracking
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO mcp_quality_snapshots
                    (repo_id, snapshot_date, quality_score, quality_tier,
                     maintenance_score, adoption_score, maturity_score,
                     community_score, risk_flags)
                SELECT id, CURRENT_DATE, quality_score, quality_tier,
                       maintenance_score, adoption_score, maturity_score,
                       community_score, risk_flags
                FROM mv_mcp_quality
                ON CONFLICT (repo_id, snapshot_date) DO UPDATE SET
                    quality_score = EXCLUDED.quality_score,
                    quality_tier = EXCLUDED.quality_tier,
                    maintenance_score = EXCLUDED.maintenance_score,
                    adoption_score = EXCLUDED.adoption_score,
                    maturity_score = EXCLUDED.maturity_score,
                    community_score = EXCLUDED.community_score,
                    risk_flags = EXCLUDED.risk_flags
            """))
            conn.commit()
            logger.info("Snapshotted MCP quality scores")
    except Exception as e:
        logger.warning(f"Could not snapshot MCP quality scores: {e}")

    # Snapshot quality scores for agents, rag, ai-coding domains
    for domain, view in [
        ("agents", "mv_agents_quality"), ("rag", "mv_rag_quality"), ("ai-coding", "mv_ai_coding_quality"),
        ("voice-ai", "mv_voice_ai_quality"), ("diffusion", "mv_diffusion_quality"),
        ("vector-db", "mv_vector_db_quality"), ("embeddings", "mv_embeddings_quality"),
        ("prompt-engineering", "mv_prompt_eng_quality"),
        ("ml-frameworks", "mv_ml_frameworks_quality"), ("llm-tools", "mv_llm_tools_quality"),
        ("nlp", "mv_nlp_quality"), ("transformers", "mv_transformers_quality"),
        ("generative-ai", "mv_generative_ai_quality"), ("computer-vision", "mv_computer_vision_quality"),
        ("data-engineering", "mv_data_engineering_quality"), ("mlops", "mv_mlops_quality"),
    ]:
        try:
            with engine.connect() as conn:
                conn.execute(text(f"""
                    INSERT INTO quality_snapshots
                        (repo_id, domain, snapshot_date, quality_score, quality_tier,
                         maintenance_score, adoption_score, maturity_score,
                         community_score, risk_flags)
                    SELECT id, :domain, CURRENT_DATE, quality_score, quality_tier,
                           maintenance_score, adoption_score, maturity_score,
                           community_score, risk_flags
                    FROM {view}
                    ON CONFLICT (repo_id, snapshot_date) DO UPDATE SET
                        quality_score = EXCLUDED.quality_score,
                        quality_tier = EXCLUDED.quality_tier,
                        maintenance_score = EXCLUDED.maintenance_score,
                        adoption_score = EXCLUDED.adoption_score,
                        maturity_score = EXCLUDED.maturity_score,
                        community_score = EXCLUDED.community_score,
                        risk_flags = EXCLUDED.risk_flags
                """), {"domain": domain})
                conn.commit()
                logger.info(f"Snapshotted {domain} quality scores")
        except Exception as e:
            logger.warning(f"Could not snapshot {domain} quality scores: {e}")

    # Snapshot ai_repo metrics for historical tracking
    try:
        import time as _time
        t0 = _time.time()
        with engine.connect() as conn:
            result = conn.execute(text("""
                INSERT INTO ai_repo_snapshots
                    (repo_id, snapshot_date, stars, forks, downloads_monthly, commits_30d)
                SELECT id, CURRENT_DATE, stars, forks, downloads_monthly, commits_30d
                FROM ai_repos
                ON CONFLICT (repo_id, snapshot_date) DO UPDATE SET
                    stars = EXCLUDED.stars,
                    forks = EXCLUDED.forks,
                    downloads_monthly = EXCLUDED.downloads_monthly,
                    commits_30d = EXCLUDED.commits_30d
            """))
            conn.commit()
            elapsed = _time.time() - t0
            logger.info(f"Snapshotted {result.rowcount} ai_repo metrics in {elapsed:.1f}s")
    except Exception as e:
        logger.warning(f"Could not snapshot ai_repo metrics: {e}")

    # Log sync
    session = SessionLocal()
    try:
        log = SyncLog(
            sync_type="views",
            status="success" if not errors else "partial",
            records_written=refreshed,
            error_message="; ".join(errors) if errors else None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        session.add(log)
        session.commit()
    finally:
        session.close()

    return {"refreshed": refreshed, "errors": errors}
