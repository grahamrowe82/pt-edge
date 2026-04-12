"""Snapshot tables for daily score captures across all entity types."""

from datetime import datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from domains.cyber.app.models.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class CveScoreSnapshot(Base):
    __tablename__ = "cve_score_snapshots"
    __table_args__ = (
        UniqueConstraint("cve_id", "snapshot_date", name="uq_css_cve_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cve_id: Mapped[int] = mapped_column(Integer, ForeignKey("cves.id"), nullable=False)
    snapshot_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    composite_score: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[int | None] = mapped_column(Integer)
    exploitability: Mapped[int | None] = mapped_column(Integer)
    exposure: Mapped[int | None] = mapped_column(Integer)
    patch_availability: Mapped[int | None] = mapped_column(Integer)
    quality_tier: Mapped[str | None] = mapped_column(String(30))


class SoftwareScoreSnapshot(Base):
    __tablename__ = "software_score_snapshots"
    __table_args__ = (
        UniqueConstraint("software_id", "snapshot_date", name="uq_sss_software_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    software_id: Mapped[int] = mapped_column(Integer, ForeignKey("software.id"), nullable=False)
    snapshot_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    composite_score: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[int | None] = mapped_column(Integer)
    exploitability: Mapped[int | None] = mapped_column(Integer)
    exposure: Mapped[int | None] = mapped_column(Integer)
    patch_availability: Mapped[int | None] = mapped_column(Integer)
    quality_tier: Mapped[str | None] = mapped_column(String(30))


class VendorScoreSnapshot(Base):
    __tablename__ = "vendor_score_snapshots"
    __table_args__ = (
        UniqueConstraint("vendor_id", "snapshot_date", name="uq_vss_vendor_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id"), nullable=False)
    snapshot_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    composite_score: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[int | None] = mapped_column(Integer)
    exploitability: Mapped[int | None] = mapped_column(Integer)
    exposure: Mapped[int | None] = mapped_column(Integer)
    patch_availability: Mapped[int | None] = mapped_column(Integer)
    quality_tier: Mapped[str | None] = mapped_column(String(30))


class WeaknessScoreSnapshot(Base):
    __tablename__ = "weakness_score_snapshots"
    __table_args__ = (
        UniqueConstraint("weakness_id", "snapshot_date", name="uq_wss_weakness_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    weakness_id: Mapped[int] = mapped_column(Integer, ForeignKey("weaknesses.id"), nullable=False)
    snapshot_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    composite_score: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[int | None] = mapped_column(Integer)
    exploitability: Mapped[int | None] = mapped_column(Integer)
    exposure: Mapped[int | None] = mapped_column(Integer)
    patch_availability: Mapped[int | None] = mapped_column(Integer)
    quality_tier: Mapped[str | None] = mapped_column(String(30))


class TechniqueScoreSnapshot(Base):
    __tablename__ = "technique_score_snapshots"
    __table_args__ = (
        UniqueConstraint("technique_id", "snapshot_date", name="uq_tss_technique_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    technique_id: Mapped[int] = mapped_column(Integer, ForeignKey("techniques.id"), nullable=False)
    snapshot_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    composite_score: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[int | None] = mapped_column(Integer)
    exploitability: Mapped[int | None] = mapped_column(Integer)
    exposure: Mapped[int | None] = mapped_column(Integer)
    patch_availability: Mapped[int | None] = mapped_column(Integer)
    quality_tier: Mapped[str | None] = mapped_column(String(30))


class PatternScoreSnapshot(Base):
    __tablename__ = "pattern_score_snapshots"
    __table_args__ = (
        UniqueConstraint("pattern_id", "snapshot_date", name="uq_pss_pattern_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern_id: Mapped[int] = mapped_column(Integer, ForeignKey("attack_patterns.id"), nullable=False)
    snapshot_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    composite_score: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[int | None] = mapped_column(Integer)
    exploitability: Mapped[int | None] = mapped_column(Integer)
    exposure: Mapped[int | None] = mapped_column(Integer)
    patch_availability: Mapped[int | None] = mapped_column(Integer)
    quality_tier: Mapped[str | None] = mapped_column(String(30))
