from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class HTTPAccessLog(Base):
    __tablename__ = "http_access_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String(200), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="GET")
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    user_agent: Mapped[str | None] = mapped_column(String(300))
    client_ip: Mapped[str | None] = mapped_column(String(45))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
