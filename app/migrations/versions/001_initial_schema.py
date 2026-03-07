"""Initial schema: tables and materialized views

Revision ID: 001_initial
Revises:
Create Date: 2026-03-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Tables ---

    # labs
    op.create_table(
        "labs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("blog_url", sa.Text(), nullable=True),
        sa.Column("github_org", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("slug", name="uq_labs_slug"),
    )

    # projects
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("lab_id", sa.Integer(), sa.ForeignKey("labs.id"), nullable=True),
        sa.Column("github_owner", sa.String(100), nullable=True),
        sa.Column("github_repo", sa.String(200), nullable=True),
        sa.Column("pypi_package", sa.String(200), nullable=True),
        sa.Column("npm_package", sa.String(200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
    )
    op.create_index("ix_projects_category", "projects", ["category"])
    op.create_index("ix_projects_lab_id", "projects", ["lab_id"])

    # github_snapshots
    op.create_table(
        "github_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("stars", sa.Integer(), server_default=sa.text("0")),
        sa.Column("forks", sa.Integer(), server_default=sa.text("0")),
        sa.Column("open_issues", sa.Integer(), server_default=sa.text("0")),
        sa.Column("watchers", sa.Integer(), server_default=sa.text("0")),
        sa.Column("commits_30d", sa.Integer(), server_default=sa.text("0")),
        sa.Column("contributors", sa.Integer(), server_default=sa.text("0")),
        sa.Column("last_commit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("license", sa.String(100), nullable=True),
        sa.UniqueConstraint("project_id", "snapshot_date", name="uq_gh_project_day"),
    )

    # download_snapshots
    op.create_table(
        "download_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("downloads_daily", sa.BigInteger(), server_default=sa.text("0")),
        sa.Column("downloads_weekly", sa.BigInteger(), server_default=sa.text("0")),
        sa.Column("downloads_monthly", sa.BigInteger(), server_default=sa.text("0")),
        sa.UniqueConstraint("project_id", "source", "snapshot_date", name="uq_dl_project_source_day"),
    )

    # releases
    op.create_table(
        "releases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("lab_id", sa.Integer(), sa.ForeignKey("labs.id"), nullable=True),
        sa.Column("version", sa.String(100), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("source", sa.String(50), server_default=sa.text("'github'")),
        sa.UniqueConstraint("url", name="uq_releases_url"),
    )

    # hn_posts
    op.create_table(
        "hn_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hn_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("author", sa.String(100), nullable=False),
        sa.Column("points", sa.Integer(), server_default=sa.text("0")),
        sa.Column("num_comments", sa.Integer(), server_default=sa.text("0")),
        sa.Column("post_type", sa.String(20), server_default=sa.text("'link'")),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.UniqueConstraint("hn_id", name="uq_hn_posts_hn_id"),
    )

    # corrections
    op.create_table(
        "corrections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic", sa.String(300), nullable=False),
        sa.Column("correction", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("submitted_by", sa.String(200), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("status", sa.String(20), server_default=sa.text("'active'")),
        sa.Column("upvotes", sa.Integer(), server_default=sa.text("0")),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=True),
    )
    op.create_index("ix_corrections_topic", "corrections", ["topic"])

    # tool_usage
    op.create_table(
        "tool_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_size", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # sync_log
    op.create_table(
        "sync_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sync_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("records_written", sa.Integer(), server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- Materialized Views ---

    # mv_momentum
    op.execute("""
CREATE MATERIALIZED VIEW mv_momentum AS
WITH latest AS (
    SELECT DISTINCT ON (project_id)
        project_id, snapshot_date, stars
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
prev_7d AS (
    SELECT DISTINCT ON (gs.project_id)
        gs.project_id, gs.stars
    FROM github_snapshots gs
    JOIN latest l ON gs.project_id = l.project_id
    WHERE gs.snapshot_date <= l.snapshot_date - 7
    ORDER BY gs.project_id, gs.snapshot_date DESC
),
prev_30d AS (
    SELECT DISTINCT ON (gs.project_id)
        gs.project_id, gs.stars
    FROM github_snapshots gs
    JOIN latest l ON gs.project_id = l.project_id
    WHERE gs.snapshot_date <= l.snapshot_date - 30
    ORDER BY gs.project_id, gs.snapshot_date DESC
),
dl_latest AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
),
dl_prev_7d AS (
    SELECT DISTINCT ON (ds.project_id)
        ds.project_id, ds.downloads_monthly
    FROM download_snapshots ds
    JOIN (SELECT DISTINCT ON (project_id) project_id, snapshot_date FROM download_snapshots ORDER BY project_id, snapshot_date DESC) l
        ON ds.project_id = l.project_id
    WHERE ds.snapshot_date <= l.snapshot_date - 7
    ORDER BY ds.project_id, ds.snapshot_date DESC
),
dl_prev_30d AS (
    SELECT DISTINCT ON (ds.project_id)
        ds.project_id, ds.downloads_monthly
    FROM download_snapshots ds
    JOIN (SELECT DISTINCT ON (project_id) project_id, snapshot_date FROM download_snapshots ORDER BY project_id, snapshot_date DESC) l
        ON ds.project_id = l.project_id
    WHERE ds.snapshot_date <= l.snapshot_date - 30
    ORDER BY ds.project_id, ds.snapshot_date DESC
)
SELECT
    p.id AS project_id,
    p.name,
    p.category,
    COALESCE(l.stars, 0) AS stars_now,
    COALESCE(p7.stars, 0) AS stars_7d_ago,
    COALESCE(p30.stars, 0) AS stars_30d_ago,
    COALESCE(l.stars, 0) - COALESCE(p7.stars, 0) AS stars_7d_delta,
    COALESCE(l.stars, 0) - COALESCE(p30.stars, 0) AS stars_30d_delta,
    COALESCE(dl.downloads_monthly, 0) AS dl_monthly_now,
    COALESCE(dl7.downloads_monthly, 0) AS dl_monthly_7d_ago,
    COALESCE(dl30.downloads_monthly, 0) AS dl_monthly_30d_ago,
    COALESCE(dl.downloads_monthly, 0) - COALESCE(dl7.downloads_monthly, 0) AS dl_7d_delta,
    COALESCE(dl.downloads_monthly, 0) - COALESCE(dl30.downloads_monthly, 0) AS dl_30d_delta
FROM projects p
LEFT JOIN latest l ON p.id = l.project_id
LEFT JOIN prev_7d p7 ON p.id = p7.project_id
LEFT JOIN prev_30d p30 ON p.id = p30.project_id
LEFT JOIN dl_latest dl ON p.id = dl.project_id
LEFT JOIN dl_prev_7d dl7 ON p.id = dl7.project_id
LEFT JOIN dl_prev_30d dl30 ON p.id = dl30.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_momentum_project_id ON mv_momentum (project_id)")

    # mv_hype_ratio
    op.execute("""
CREATE MATERIALIZED VIEW mv_hype_ratio AS
WITH latest_stars AS (
    SELECT DISTINCT ON (project_id)
        project_id, stars
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_downloads AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
)
SELECT
    p.id AS project_id,
    p.name,
    p.category,
    COALESCE(s.stars, 0) AS stars,
    COALESCE(d.downloads_monthly, 0) AS monthly_downloads,
    CASE
        WHEN COALESCE(d.downloads_monthly, 0) > 0
        THEN ROUND(COALESCE(s.stars, 0)::numeric / d.downloads_monthly, 4)
        ELSE NULL
    END AS hype_ratio,
    CASE
        WHEN COALESCE(d.downloads_monthly, 0) = 0 THEN 'no_downloads'
        WHEN COALESCE(s.stars, 0)::numeric / d.downloads_monthly > 1.0 THEN 'hype'
        WHEN COALESCE(s.stars, 0)::numeric / d.downloads_monthly > 0.1 THEN 'balanced'
        ELSE 'quiet_adoption'
    END AS hype_bucket
FROM projects p
LEFT JOIN latest_stars s ON p.id = s.project_id
LEFT JOIN latest_downloads d ON p.id = d.project_id
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_hype_ratio_project_id ON mv_hype_ratio (project_id)")

    # mv_lab_velocity
    op.execute("""
CREATE MATERIALIZED VIEW mv_lab_velocity AS
WITH release_counts AS (
    SELECT
        lab_id,
        COUNT(*) FILTER (WHERE released_at >= NOW() - INTERVAL '30 days') AS releases_30d,
        COUNT(*) FILTER (WHERE released_at >= NOW() - INTERVAL '90 days') AS releases_90d
    FROM releases
    WHERE lab_id IS NOT NULL
    GROUP BY lab_id
),
release_gaps AS (
    SELECT
        lab_id,
        AVG(gap_days) AS avg_days_between_releases
    FROM (
        SELECT
            lab_id,
            EXTRACT(EPOCH FROM (released_at - LAG(released_at) OVER (PARTITION BY lab_id ORDER BY released_at))) / 86400.0 AS gap_days
        FROM releases
        WHERE lab_id IS NOT NULL
    ) sub
    WHERE gap_days IS NOT NULL
    GROUP BY lab_id
)
SELECT
    l.id AS lab_id,
    l.name AS lab_name,
    COALESCE(rc.releases_30d, 0) AS releases_30d,
    COALESCE(rc.releases_90d, 0) AS releases_90d,
    ROUND(COALESCE(rg.avg_days_between_releases, 0)::numeric, 1) AS avg_days_between_releases,
    CASE
        WHEN COALESCE(rc.releases_30d, 0) * 3 > COALESCE(rc.releases_90d, 0) THEN true
        ELSE false
    END AS is_accelerating
FROM labs l
LEFT JOIN release_counts rc ON l.id = rc.lab_id
LEFT JOIN release_gaps rg ON l.id = rg.lab_id
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_lab_velocity_lab_id ON mv_lab_velocity (lab_id)")

    # mv_project_summary (depends on mv_momentum and mv_hype_ratio)
    op.execute("""
CREATE MATERIALIZED VIEW mv_project_summary AS
WITH latest_gh AS (
    SELECT DISTINCT ON (project_id)
        project_id, stars, forks, commits_30d, last_commit_at
    FROM github_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_dl AS (
    SELECT DISTINCT ON (project_id)
        project_id, downloads_monthly
    FROM download_snapshots
    ORDER BY project_id, snapshot_date DESC
),
latest_release AS (
    SELECT DISTINCT ON (project_id)
        project_id, released_at AS last_release_at, title AS last_release_title
    FROM releases
    WHERE project_id IS NOT NULL
    ORDER BY project_id, released_at DESC
),
correction_counts AS (
    SELECT
        topic,
        COUNT(*) AS correction_count
    FROM corrections
    WHERE status = 'active'
    GROUP BY topic
)
SELECT
    p.id AS project_id,
    p.name,
    p.slug,
    p.category,
    l.name AS lab_name,
    COALESCE(gh.stars, 0) AS stars,
    COALESCE(gh.forks, 0) AS forks,
    COALESCE(dl.downloads_monthly, 0) AS monthly_downloads,
    COALESCE(m.stars_7d_delta, 0) AS stars_7d_delta,
    COALESCE(m.stars_30d_delta, 0) AS stars_30d_delta,
    COALESCE(m.dl_30d_delta, 0) AS dl_30d_delta,
    hr.hype_ratio,
    hr.hype_bucket,
    lr.last_release_at,
    lr.last_release_title,
    EXTRACT(DAY FROM NOW() - lr.last_release_at)::int AS days_since_release,
    gh.last_commit_at,
    COALESCE(gh.commits_30d, 0) AS commits_30d,
    COALESCE(cc.correction_count, 0) AS correction_count
FROM projects p
LEFT JOIN labs l ON p.lab_id = l.id
LEFT JOIN latest_gh gh ON p.id = gh.project_id
LEFT JOIN latest_dl dl ON p.id = dl.project_id
LEFT JOIN mv_momentum m ON p.id = m.project_id
LEFT JOIN mv_hype_ratio hr ON p.id = hr.project_id
LEFT JOIN latest_release lr ON p.id = lr.project_id
LEFT JOIN correction_counts cc ON LOWER(cc.topic) = LOWER(p.slug)
WHERE p.is_active = true
    """)
    op.execute("CREATE UNIQUE INDEX idx_mv_project_summary_project_id ON mv_project_summary (project_id)")


def downgrade() -> None:
    # Drop materialized views in reverse dependency order
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_project_summary CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_lab_velocity CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_hype_ratio CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_momentum CASCADE")

    # Drop tables in reverse dependency order
    op.drop_table("sync_log")
    op.drop_table("tool_usage")
    op.drop_table("corrections")
    op.drop_table("hn_posts")
    op.drop_table("releases")
    op.drop_table("download_snapshots")
    op.drop_table("github_snapshots")
    op.drop_table("projects")
    op.drop_table("labs")
