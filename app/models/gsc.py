from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class GSCSearchData(Base):
    __tablename__ = "gsc_search_data"
    __table_args__ = (
        UniqueConstraint("search_date", "query", "page", name="uq_gsc_date_query_page"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_date: Mapped[date] = mapped_column(Date, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[str] = mapped_column(Text, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ctr: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    position: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    device: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
