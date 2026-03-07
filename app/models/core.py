from datetime import datetime, timezone

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.models.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Lab(Base):
    __tablename__ = "labs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    blog_url: Mapped[str | None] = mapped_column(Text)
    github_org: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    projects: Mapped[list["Project"]] = relationship(back_populates="lab")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_category", "category"),
        Index("ix_projects_lab_id", "lab_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    lab_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("labs.id"))
    github_owner: Mapped[str | None] = mapped_column(String(100))
    github_repo: Mapped[str | None] = mapped_column(String(200))
    pypi_package: Mapped[str | None] = mapped_column(String(200))
    npm_package: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    tier_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distribution_type: Mapped[str | None] = mapped_column(String(20), nullable=True, default="package")
    hf_model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    topics: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    embedding = mapped_column(Vector(1536), nullable=True)
    repo_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    lab: Mapped[Lab | None] = relationship(back_populates="projects")


class ProjectCandidate(Base):
    __tablename__ = "project_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    github_owner: Mapped[str | None] = mapped_column(String(100))
    github_repo: Mapped[str | None] = mapped_column(String(200))
    name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    stars: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_detail: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    topics: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    repo_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commit_trend: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contributor_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FrontierModel(Base):
    __tablename__ = "frontier_models"
    __table_args__ = (
        Index("ix_frontier_models_lab_id", "lab_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lab_id: Mapped[int] = mapped_column(Integer, ForeignKey("labs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    openrouter_id: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    context_window: Mapped[int | None] = mapped_column(Integer)
    max_completion_tokens: Mapped[int | None] = mapped_column(Integer)
    pricing_input: Mapped[str | None] = mapped_column(String(50))    # e.g. "$3.00/MTok"
    pricing_output: Mapped[str | None] = mapped_column(String(50))   # e.g. "$15.00/MTok"
    modality: Mapped[str | None] = mapped_column(String(100))        # e.g. "text+image->text"
    capabilities: Mapped[dict | None] = mapped_column(JSONB)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, deprecated
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    lab: Mapped[Lab] = relationship()


class LabEvent(Base):
    __tablename__ = "lab_events"
    __table_args__ = (
        Index("ix_lab_events_lab_id", "lab_id"),
        Index("ix_lab_events_event_date", "event_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lab_id: Mapped[int] = mapped_column(Integer, ForeignKey("labs.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
        # product_launch, model_launch, capability, api_change, pricing_change, protocol, deprecation
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_hn_id: Mapped[int | None] = mapped_column(Integer)
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    lab: Mapped[Lab] = relationship()
