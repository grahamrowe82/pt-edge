"""Fix 12 new domain MVs: add missing columns from stale template.

Revision ID: 088
Revises: 087
Create Date: 2026-04-07

Migration 087 created 12 new domain quality views using a template
copied from migration 071, which predated migration 077's addition of
problem_domains, use_this_if, not_ideal_if. This migration drops and
recreates those views using the canonical template from
app/views/quality_template.py.
"""
from typing import Sequence, Union

from alembic import op

from app.views.quality_template import QUALITY_VIEW_SQL

revision: str = "088"
down_revision: Union[str, None] = "087"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_DOMAINS = [
    ("mv_llm_inference_quality", "llm-inference"),
    ("mv_ai_evals_quality", "ai-evals"),
    ("mv_fine_tuning_quality", "fine-tuning"),
    ("mv_document_ai_quality", "document-ai"),
    ("mv_ai_safety_quality", "ai-safety"),
    ("mv_recommendation_systems_quality", "recommendation-systems"),
    ("mv_audio_ai_quality", "audio-ai"),
    ("mv_synthetic_data_quality", "synthetic-data"),
    ("mv_time_series_quality", "time-series"),
    ("mv_multimodal_quality", "multimodal"),
    ("mv_3d_ai_quality", "3d-ai"),
    ("mv_scientific_ml_quality", "scientific-ml"),
]


def upgrade() -> None:
    for view_name, domain in NEW_DOMAINS:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view_name} CASCADE")
        op.execute(QUALITY_VIEW_SQL.substitute(view_name=view_name, domain=domain))
        op.execute(f"CREATE UNIQUE INDEX idx_{view_name}_id ON {view_name} (id)")


def downgrade() -> None:
    for view_name, _ in NEW_DOMAINS:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view_name} CASCADE")
