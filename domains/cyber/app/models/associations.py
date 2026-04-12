"""Junction/association tables for cross-entity relationships in the cybersecurity knowledge graph."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from domains.cyber.app.models.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class CveSoftware(Base):
    """CVE-to-software link with affected version ranges from CPE matches."""
    __tablename__ = "cve_software"
    __table_args__ = (
        UniqueConstraint("cve_id", "software_id", name="uq_cs_cve_software"),
        Index("ix_cs_cve_id", "cve_id"),
        Index("ix_cs_software_id", "software_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cve_id: Mapped[int] = mapped_column(Integer, ForeignKey("cves.id"), nullable=False)
    software_id: Mapped[int] = mapped_column(Integer, ForeignKey("software.id"), nullable=False)
    version_start: Mapped[str | None] = mapped_column(String(100))
    version_end: Mapped[str | None] = mapped_column(String(100))
    version_start_type: Mapped[str | None] = mapped_column(String(20))  # including, excluding
    version_end_type: Mapped[str | None] = mapped_column(String(20))
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    cve = relationship("CVE", back_populates="software_links")
    software = relationship("Software", back_populates="cve_links")


class CveVendor(Base):
    """Denormalized CVE-to-vendor link for fast vendor-level queries."""
    __tablename__ = "cve_vendors"
    __table_args__ = (
        UniqueConstraint("cve_id", "vendor_id", name="uq_cv_cve_vendor"),
        Index("ix_cv_cve_id", "cve_id"),
        Index("ix_cv_vendor_id", "vendor_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cve_id: Mapped[int] = mapped_column(Integer, ForeignKey("cves.id"), nullable=False)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id"), nullable=False)

    # Relationships
    cve = relationship("CVE", back_populates="vendor_links")
    vendor = relationship("Vendor", back_populates="cve_links")


class CveWeakness(Base):
    """CVE-to-weakness (CWE) classification from NVD."""
    __tablename__ = "cve_weaknesses"
    __table_args__ = (
        UniqueConstraint("cve_id", "weakness_id", "source", name="uq_cw_cve_weakness_source"),
        Index("ix_cw_cve_id", "cve_id"),
        Index("ix_cw_weakness_id", "weakness_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cve_id: Mapped[int] = mapped_column(Integer, ForeignKey("cves.id"), nullable=False)
    weakness_id: Mapped[int] = mapped_column(Integer, ForeignKey("weaknesses.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="nvd")  # nvd, cna

    # Relationships
    cve = relationship("CVE", back_populates="weakness_links")
    weakness = relationship("Weakness", back_populates="cve_links")


class CveExploit(Base):
    """Public exploit references for CVEs from Exploit-DB and other sources."""
    __tablename__ = "cve_exploits"
    __table_args__ = (
        UniqueConstraint("cve_id", "exploit_db_id", name="uq_ce_cve_exploit"),
        Index("ix_ce_cve_id", "cve_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cve_id: Mapped[int] = mapped_column(Integer, ForeignKey("cves.id"), nullable=False)
    exploit_db_id: Mapped[str] = mapped_column(String(20), nullable=False)
    exploit_type: Mapped[str | None] = mapped_column(String(50))  # local, remote, webapps, dos
    platform: Mapped[str | None] = mapped_column(String(100))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(30), default="exploit_db")
    source_url: Mapped[str | None] = mapped_column(Text)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    cve = relationship("CVE", back_populates="exploit_links")


class WeaknessPattern(Base):
    """CWE-to-CAPEC mapping: which attack patterns exploit which weaknesses."""
    __tablename__ = "weakness_patterns"
    __table_args__ = (
        UniqueConstraint("weakness_id", "pattern_id", name="uq_wp_weakness_pattern"),
        Index("ix_wp_weakness_id", "weakness_id"),
        Index("ix_wp_pattern_id", "pattern_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    weakness_id: Mapped[int] = mapped_column(Integer, ForeignKey("weaknesses.id"), nullable=False)
    pattern_id: Mapped[int] = mapped_column(Integer, ForeignKey("attack_patterns.id"), nullable=False)

    # Relationships
    weakness = relationship("Weakness", back_populates="pattern_links")
    pattern = relationship("AttackPattern", back_populates="weakness_links")


class PatternTechnique(Base):
    """CAPEC-to-ATT&CK mapping: which techniques use which attack patterns."""
    __tablename__ = "pattern_techniques"
    __table_args__ = (
        UniqueConstraint("pattern_id", "technique_id", name="uq_pt_pattern_technique"),
        Index("ix_pt_pattern_id", "pattern_id"),
        Index("ix_pt_technique_id", "technique_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern_id: Mapped[int] = mapped_column(Integer, ForeignKey("attack_patterns.id"), nullable=False)
    technique_id: Mapped[int] = mapped_column(Integer, ForeignKey("techniques.id"), nullable=False)

    # Relationships
    pattern = relationship("AttackPattern", back_populates="technique_links")
    technique = relationship("Technique", back_populates="pattern_links")


class TechniqueTactic(Base):
    """ATT&CK technique-to-tactic mapping."""
    __tablename__ = "technique_tactics"
    __table_args__ = (
        UniqueConstraint("technique_id", "tactic_id", name="uq_tt_technique_tactic"),
        Index("ix_tt_technique_id", "technique_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    technique_id: Mapped[int] = mapped_column(Integer, ForeignKey("techniques.id"), nullable=False)
    tactic_id: Mapped[str] = mapped_column(String(30), nullable=False)  # e.g. "TA0001"
    tactic_name: Mapped[str | None] = mapped_column(String(100))  # e.g. "Initial Access"

    # Relationships
    technique = relationship("Technique", back_populates="tactic_links")
