"""Initial schema: 6 entity tables, 7 association tables, 6 snapshot tables, support tables.

Revision ID: 001
Create Date: 2026-04-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # --- Entity tables ---

    op.create_table(
        "vendors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), unique=True, nullable=False),
        sa.Column("cpe_vendor", sa.String(200), unique=True, nullable=False),
        sa.Column("website", sa.String(500)),
        sa.Column("product_count", sa.Integer, server_default="0"),
        sa.Column("embedding", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_vendors_slug", "vendors", ["slug"])
    op.create_index("ix_vendors_cpe_vendor", "vendors", ["cpe_vendor"])
    op.create_index("ix_vendors_name", "vendors", ["name"])

    op.create_table(
        "cves",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cve_id", sa.String(20), unique=True, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("published_date", sa.DateTime(timezone=True)),
        sa.Column("modified_date", sa.DateTime(timezone=True)),
        sa.Column("cvss_base_score", sa.Float),
        sa.Column("cvss_vector", sa.String(100)),
        sa.Column("cvss_version", sa.String(10)),
        sa.Column("attack_vector", sa.String(20)),
        sa.Column("attack_complexity", sa.String(10)),
        sa.Column("privileges_required", sa.String(10)),
        sa.Column("user_interaction", sa.String(10)),
        sa.Column("scope", sa.String(10)),
        sa.Column("epss_score", sa.Float),
        sa.Column("epss_percentile", sa.Float),
        sa.Column("is_kev", sa.Boolean, server_default="false"),
        sa.Column("kev_date_added", sa.Date),
        sa.Column("references", JSONB),
        sa.Column("embedding", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_cves_cve_id", "cves", ["cve_id"])
    op.create_index("ix_cves_cvss_base_score", "cves", ["cvss_base_score"])
    op.create_index("ix_cves_published_date", "cves", ["published_date"])
    op.create_index("ix_cves_is_kev", "cves", ["is_kev"])
    op.create_index("ix_cves_epss_score", "cves", ["epss_score"])

    op.create_table(
        "software",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cpe_id", sa.String(200), unique=True, nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("version", sa.String(100)),
        sa.Column("vendor_id", sa.Integer, sa.ForeignKey("vendors.id")),
        sa.Column("part", sa.String(5)),
        sa.Column("product_category", sa.String(100)),
        sa.Column("embedding", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_software_cpe_id", "software", ["cpe_id"])
    op.create_index("ix_software_name", "software", ["name"])
    op.create_index("ix_software_vendor_id", "software", ["vendor_id"])

    op.create_table(
        "weaknesses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cwe_id", sa.String(20), unique=True, nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("abstraction", sa.String(20)),
        sa.Column("parent_weakness_id", sa.Integer, sa.ForeignKey("weaknesses.id")),
        sa.Column("common_consequences", JSONB),
        sa.Column("detection_methods", JSONB),
        sa.Column("embedding", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_weaknesses_cwe_id", "weaknesses", ["cwe_id"])
    op.create_index("ix_weaknesses_abstraction", "weaknesses", ["abstraction"])
    op.create_index("ix_weaknesses_parent_id", "weaknesses", ["parent_weakness_id"])

    op.create_table(
        "techniques",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("technique_id", sa.String(20), unique=True, nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("platforms", sa.ARRAY(sa.Text)),
        sa.Column("data_sources", sa.ARRAY(sa.Text)),
        sa.Column("detection", sa.Text),
        sa.Column("is_subtechnique", sa.Boolean, server_default="false"),
        sa.Column("parent_technique_id", sa.Integer, sa.ForeignKey("techniques.id")),
        sa.Column("embedding", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_techniques_technique_id", "techniques", ["technique_id"])
    op.create_index("ix_techniques_parent_id", "techniques", ["parent_technique_id"])
    op.create_index("ix_techniques_is_subtechnique", "techniques", ["is_subtechnique"])

    op.create_table(
        "attack_patterns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("capec_id", sa.String(20), unique=True, nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("severity", sa.String(20)),
        sa.Column("likelihood", sa.String(20)),
        sa.Column("embedding", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_attack_patterns_capec_id", "attack_patterns", ["capec_id"])

    # --- Association tables ---

    op.create_table(
        "cve_software",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cve_id", sa.Integer, sa.ForeignKey("cves.id"), nullable=False),
        sa.Column("software_id", sa.Integer, sa.ForeignKey("software.id"), nullable=False),
        sa.Column("version_start", sa.String(100)),
        sa.Column("version_end", sa.String(100)),
        sa.Column("version_start_type", sa.String(20)),
        sa.Column("version_end_type", sa.String(20)),
        sa.Column("last_updated", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("cve_id", "software_id", name="uq_cs_cve_software"),
    )
    op.create_index("ix_cs_cve_id", "cve_software", ["cve_id"])
    op.create_index("ix_cs_software_id", "cve_software", ["software_id"])

    op.create_table(
        "cve_vendors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cve_id", sa.Integer, sa.ForeignKey("cves.id"), nullable=False),
        sa.Column("vendor_id", sa.Integer, sa.ForeignKey("vendors.id"), nullable=False),
        sa.UniqueConstraint("cve_id", "vendor_id", name="uq_cv_cve_vendor"),
    )
    op.create_index("ix_cv_cve_id", "cve_vendors", ["cve_id"])
    op.create_index("ix_cv_vendor_id", "cve_vendors", ["vendor_id"])

    op.create_table(
        "cve_weaknesses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cve_id", sa.Integer, sa.ForeignKey("cves.id"), nullable=False),
        sa.Column("weakness_id", sa.Integer, sa.ForeignKey("weaknesses.id"), nullable=False),
        sa.Column("source", sa.String(30), server_default="nvd"),
        sa.UniqueConstraint("cve_id", "weakness_id", "source", name="uq_cw_cve_weakness_source"),
    )
    op.create_index("ix_cw_cve_id", "cve_weaknesses", ["cve_id"])
    op.create_index("ix_cw_weakness_id", "cve_weaknesses", ["weakness_id"])

    op.create_table(
        "cve_exploits",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cve_id", sa.Integer, sa.ForeignKey("cves.id"), nullable=False),
        sa.Column("exploit_db_id", sa.String(20), nullable=False),
        sa.Column("exploit_type", sa.String(50)),
        sa.Column("platform", sa.String(100)),
        sa.Column("verified", sa.Boolean, server_default="false"),
        sa.Column("source", sa.String(30), server_default="exploit_db"),
        sa.Column("source_url", sa.Text),
        sa.Column("last_updated", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("cve_id", "exploit_db_id", name="uq_ce_cve_exploit"),
    )
    op.create_index("ix_ce_cve_id", "cve_exploits", ["cve_id"])

    op.create_table(
        "weakness_patterns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("weakness_id", sa.Integer, sa.ForeignKey("weaknesses.id"), nullable=False),
        sa.Column("pattern_id", sa.Integer, sa.ForeignKey("attack_patterns.id"), nullable=False),
        sa.UniqueConstraint("weakness_id", "pattern_id", name="uq_wp_weakness_pattern"),
    )
    op.create_index("ix_wp_weakness_id", "weakness_patterns", ["weakness_id"])
    op.create_index("ix_wp_pattern_id", "weakness_patterns", ["pattern_id"])

    op.create_table(
        "pattern_techniques",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pattern_id", sa.Integer, sa.ForeignKey("attack_patterns.id"), nullable=False),
        sa.Column("technique_id", sa.Integer, sa.ForeignKey("techniques.id"), nullable=False),
        sa.UniqueConstraint("pattern_id", "technique_id", name="uq_pt_pattern_technique"),
    )
    op.create_index("ix_pt_pattern_id", "pattern_techniques", ["pattern_id"])
    op.create_index("ix_pt_technique_id", "pattern_techniques", ["technique_id"])

    op.create_table(
        "technique_tactics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("technique_id", sa.Integer, sa.ForeignKey("techniques.id"), nullable=False),
        sa.Column("tactic_id", sa.String(30), nullable=False),
        sa.Column("tactic_name", sa.String(100)),
        sa.UniqueConstraint("technique_id", "tactic_id", name="uq_tt_technique_tactic"),
    )
    op.create_index("ix_tt_technique_id", "technique_tactics", ["technique_id"])

    # --- Snapshot tables ---

    for prefix, fk_col, fk_table, uq_prefix in [
        ("cve", "cve_id", "cves", "css"),
        ("software", "software_id", "software", "sss"),
        ("vendor", "vendor_id", "vendors", "vss"),
        ("weakness", "weakness_id", "weaknesses", "wss"),
        ("technique", "technique_id", "techniques", "tss"),
        ("pattern", "pattern_id", "attack_patterns", "pss"),
    ]:
        table_name = f"{prefix}_score_snapshots"
        op.create_table(
            table_name,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(fk_col, sa.Integer, sa.ForeignKey(f"{fk_table}.id"), nullable=False),
            sa.Column("snapshot_date", sa.Date, nullable=False),
            sa.Column("composite_score", sa.Integer),
            sa.Column("severity", sa.Integer),
            sa.Column("exploitability", sa.Integer),
            sa.Column("exposure", sa.Integer),
            sa.Column("patch_availability", sa.Integer),
            sa.Column("quality_tier", sa.String(30)),
            sa.UniqueConstraint(fk_col, "snapshot_date", name=f"uq_{uq_prefix}_{prefix}_date"),
        )

    # --- Support tables ---

    op.create_table(
        "tool_usage",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("params", JSONB),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("success", sa.Boolean, server_default="true"),
        sa.Column("error_message", sa.Text),
        sa.Column("result_size", sa.Integer),
        sa.Column("client_ip", sa.String(45)),
        sa.Column("user_agent", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "sync_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sync_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("records_written", sa.Integer, server_default="0"),
        sa.Column("error_message", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "methodology",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("topic", sa.String(100), unique=True, nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("embedding", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("contact_email", sa.String(200), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False, server_default="free"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "api_usage",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("api_key_id", sa.Integer, sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("endpoint", sa.String(200), nullable=False),
        sa.Column("params", JSONB),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("status_code", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_api_usage_key_created", "api_usage", ["api_key_id", "created_at"])

    # --- Task queue tables (for future task queue port) ---

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(30), nullable=False),
        sa.Column("priority", sa.Integer, server_default="5"),
        sa.Column("state", sa.String(20), server_default="pending"),
        sa.Column("params", JSONB),
        sa.Column("result", JSONB),
        sa.Column("error_message", sa.Text),
        sa.Column("retry_count", sa.Integer, server_default="0"),
        sa.Column("max_retries", sa.Integer, server_default="3"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_tasks_state_priority", "tasks", ["state", "priority"])
    op.create_index("ix_tasks_resource_type", "tasks", ["resource_type"])

    op.create_table(
        "resource_budgets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("resource_type", sa.String(30), unique=True, nullable=False),
        sa.Column("budget", sa.Integer, nullable=False),
        sa.Column("consumed", sa.Integer, server_default="0"),
        sa.Column("rpm", sa.Integer),
        sa.Column("period_hours", sa.Integer, server_default="24"),
        sa.Column("period_start", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("reset_mode", sa.String(20), server_default="rolling"),
        sa.Column("reset_tz", sa.String(50), server_default="UTC"),
        sa.Column("reset_hour", sa.Integer, server_default="0"),
        sa.Column("last_call_at", sa.DateTime(timezone=True)),
        sa.Column("backoff_count", sa.Integer, server_default="0"),
        sa.Column("backoff_until", sa.DateTime(timezone=True)),
    )


def downgrade():
    # Drop in reverse dependency order
    op.drop_table("resource_budgets")
    op.drop_table("tasks")
    op.drop_table("api_usage")
    op.drop_table("api_keys")
    op.drop_table("methodology")
    op.drop_table("sync_log")
    op.drop_table("tool_usage")
    for prefix in ["pattern", "technique", "weakness", "vendor", "software", "cve"]:
        op.drop_table(f"{prefix}_score_snapshots")
    op.drop_table("technique_tactics")
    op.drop_table("pattern_techniques")
    op.drop_table("weakness_patterns")
    op.drop_table("cve_exploits")
    op.drop_table("cve_weaknesses")
    op.drop_table("cve_vendors")
    op.drop_table("cve_software")
    op.drop_table("attack_patterns")
    op.drop_table("techniques")
    op.drop_table("weaknesses")
    op.drop_table("software")
    op.drop_table("cves")
    op.drop_table("vendors")
