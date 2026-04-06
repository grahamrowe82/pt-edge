from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=5)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    resource_type: Mapped[str | None] = mapped_column(Text)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
    claimed_by: Mapped[str | None] = mapped_column(Text)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ResourceBudget(Base):
    __tablename__ = "resource_budgets"

    resource_type: Mapped[str] = mapped_column(Text, primary_key=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    period_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    budget: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reset_mode: Mapped[str] = mapped_column(Text, nullable=False, default="rolling")
    reset_tz: Mapped[str] = mapped_column(Text, nullable=False, default="UTC")
    reset_hour: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    rpm: Mapped[int | None] = mapped_column(Integer)
    last_call_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backoff_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backoff_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class RawCache(Base):
    __tablename__ = "raw_cache"

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_id: Mapped[str] = mapped_column(Text, primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    payload: Mapped[str | None] = mapped_column(Text)
