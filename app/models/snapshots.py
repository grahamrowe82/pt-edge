from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


def _today():
    return date.today()


class GitHubSnapshot(Base):
    __tablename__ = "github_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "snapshot_date", name="uq_gh_project_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, default=_today)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    stars: Mapped[int] = mapped_column(Integer, default=0)
    forks: Mapped[int] = mapped_column(Integer, default=0)
    open_issues: Mapped[int] = mapped_column(Integer, default=0)
    watchers: Mapped[int] = mapped_column(Integer, default=0)
    commits_30d: Mapped[int] = mapped_column(Integer, default=0)
    contributors: Mapped[int] = mapped_column(Integer, default=0)
    last_commit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    license: Mapped[str | None] = mapped_column(String(100))


class DownloadSnapshot(Base):
    __tablename__ = "download_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "source", "snapshot_date", name="uq_dl_project_source_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, default=_today)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # pypi, npm
    downloads_daily: Mapped[int] = mapped_column(BigInteger, default=0)
    downloads_weekly: Mapped[int] = mapped_column(BigInteger, default=0)
    downloads_monthly: Mapped[int] = mapped_column(BigInteger, default=0)


class AIRepoSnapshot(Base):
    __tablename__ = "ai_repo_snapshots"
    __table_args__ = (
        UniqueConstraint("repo_id", "snapshot_date", name="uq_ai_repo_snap_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(Integer, ForeignKey("ai_repos.id"), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, default=_today)
    stars: Mapped[int | None] = mapped_column(Integer)
    forks: Mapped[int | None] = mapped_column(Integer)
    downloads_monthly: Mapped[int | None] = mapped_column(BigInteger)
    commits_30d: Mapped[int | None] = mapped_column(Integer)
