"""Core cybersecurity entity models: CVE, Software, Vendor, Weakness, Technique, AttackPattern."""

from datetime import datetime, timezone

from sqlalchemy import (
    ARRAY, Boolean, Date, DateTime, Float, ForeignKey, Index,
    Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from domains.cyber.app.models.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class CVE(Base):
    __tablename__ = "cves"
    __table_args__ = (
        Index("ix_cves_cve_id", "cve_id"),
        Index("ix_cves_cvss_base_score", "cvss_base_score"),
        Index("ix_cves_published_date", "published_date"),
        Index("ix_cves_is_kev", "is_kev"),
        Index("ix_cves_epss_score", "epss_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cve_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    published_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    modified_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # CVSS v3.x fields
    cvss_base_score: Mapped[float | None] = mapped_column(Float)
    cvss_vector: Mapped[str | None] = mapped_column(String(100))
    cvss_version: Mapped[str | None] = mapped_column(String(10))
    attack_vector: Mapped[str | None] = mapped_column(String(20))  # NETWORK, ADJACENT, LOCAL, PHYSICAL
    attack_complexity: Mapped[str | None] = mapped_column(String(10))  # LOW, HIGH
    privileges_required: Mapped[str | None] = mapped_column(String(10))  # NONE, LOW, HIGH
    user_interaction: Mapped[str | None] = mapped_column(String(10))  # NONE, REQUIRED
    scope: Mapped[str | None] = mapped_column(String(10))  # UNCHANGED, CHANGED
    # Enrichment fields (populated by later ingest phases)
    epss_score: Mapped[float | None] = mapped_column(Float)
    epss_percentile: Mapped[float | None] = mapped_column(Float)
    is_kev: Mapped[bool] = mapped_column(Boolean, default=False)
    kev_date_added: Mapped[datetime | None] = mapped_column(Date)
    references: Mapped[dict | None] = mapped_column(JSONB)
    embedding = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    software_links: Mapped[list["CveSoftware"]] = relationship(back_populates="cve")
    vendor_links: Mapped[list["CveVendor"]] = relationship(back_populates="cve")
    weakness_links: Mapped[list["CveWeakness"]] = relationship(back_populates="cve")
    exploit_links: Mapped[list["CveExploit"]] = relationship(back_populates="cve")


class Software(Base):
    __tablename__ = "software"
    __table_args__ = (
        Index("ix_software_cpe_id", "cpe_id"),
        Index("ix_software_name", "name"),
        Index("ix_software_vendor_id", "vendor_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cpe_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    version: Mapped[str | None] = mapped_column(String(100))
    vendor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("vendors.id"))
    part: Mapped[str | None] = mapped_column(String(5))  # a (application), o (OS), h (hardware)
    product_category: Mapped[str | None] = mapped_column(String(100))
    embedding = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    vendor: Mapped["Vendor | None"] = relationship(back_populates="products")
    cve_links: Mapped[list["CveSoftware"]] = relationship(back_populates="software")


class Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = (
        Index("ix_vendors_slug", "slug"),
        Index("ix_vendors_cpe_vendor", "cpe_vendor"),
        Index("ix_vendors_name", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    cpe_vendor: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    website: Mapped[str | None] = mapped_column(String(500))
    product_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    products: Mapped[list[Software]] = relationship(back_populates="vendor")
    cve_links: Mapped[list["CveVendor"]] = relationship(back_populates="vendor")


class Weakness(Base):
    __tablename__ = "weaknesses"
    __table_args__ = (
        Index("ix_weaknesses_cwe_id", "cwe_id"),
        Index("ix_weaknesses_abstraction", "abstraction"),
        Index("ix_weaknesses_parent_id", "parent_weakness_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cwe_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    abstraction: Mapped[str | None] = mapped_column(String(20))  # Pillar, Class, Base, Variant
    parent_weakness_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("weaknesses.id"))
    common_consequences: Mapped[dict | None] = mapped_column(JSONB)
    detection_methods: Mapped[dict | None] = mapped_column(JSONB)
    embedding = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    cve_links: Mapped[list["CveWeakness"]] = relationship(back_populates="weakness")
    pattern_links: Mapped[list["WeaknessPattern"]] = relationship(back_populates="weakness")


class Technique(Base):
    __tablename__ = "techniques"
    __table_args__ = (
        Index("ix_techniques_technique_id", "technique_id"),
        Index("ix_techniques_parent_id", "parent_technique_id"),
        Index("ix_techniques_is_subtechnique", "is_subtechnique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    technique_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    platforms: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    data_sources: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    detection: Mapped[str | None] = mapped_column(Text)
    is_subtechnique: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_technique_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("techniques.id"))
    embedding = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    pattern_links: Mapped[list["PatternTechnique"]] = relationship(back_populates="technique")
    tactic_links: Mapped[list["TechniqueTactic"]] = relationship(back_populates="technique")


class AttackPattern(Base):
    __tablename__ = "attack_patterns"
    __table_args__ = (
        Index("ix_attack_patterns_capec_id", "capec_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    capec_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(String(20))  # Very High, High, Medium, Low, Very Low
    likelihood: Mapped[str | None] = mapped_column(String(20))
    embedding = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    weakness_links: Mapped[list["WeaknessPattern"]] = relationship(back_populates="pattern")
    technique_links: Mapped[list["PatternTechnique"]] = relationship(back_populates="pattern")


# Forward reference imports for relationship type hints
from domains.cyber.app.models.associations import (  # noqa: E402
    CveSoftware, CveVendor, CveWeakness, CveExploit,
    WeaknessPattern, PatternTechnique, TechniqueTactic,
)
