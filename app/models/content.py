from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.models.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("projects.id"))
    lab_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("labs.id"))
    version: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    source: Mapped[str] = mapped_column(String(50), default="github")  # github, blog, changelog
    embedding = mapped_column(Vector(1536), nullable=True)


class HNPost(Base):
    __tablename__ = "hn_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hn_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(100), nullable=False)
    points: Mapped[int] = mapped_column(Integer, default=0)
    num_comments: Mapped[int] = mapped_column(Integer, default=0)
    post_type: Mapped[str] = mapped_column(String(20), default="link")  # show, ask, link
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    project_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("projects.id"))
    lab_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("labs.id"))


class V2EXPost(Base):
    __tablename__ = "v2ex_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    v2ex_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(100), nullable=False)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    node_name: Mapped[str | None] = mapped_column(String(50))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    project_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("projects.id"))
    lab_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("labs.id"))


class NewsletterMention(Base):
    __tablename__ = "newsletter_mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed_slug: Mapped[str] = mapped_column(Text, nullable=False)
    entry_url: Mapped[str] = mapped_column(Text, nullable=False)
    topic_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    sentiment: Mapped[str | None] = mapped_column(Text)
    mentions: Mapped[list | None] = mapped_column(JSONB, default=list)
    raw_content: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    embedding = mapped_column(Vector(1536), nullable=True)


class AIRepo(Base):
    __tablename__ = "ai_repos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_owner: Mapped[str] = mapped_column(String, nullable=False)
    github_repo: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    stars: Mapped[int] = mapped_column(Integer, default=0)
    forks: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str | None] = mapped_column(String)
    topics: Mapped[list | None] = mapped_column(ARRAY(Text))
    license: Mapped[str | None] = mapped_column(String)
    last_pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    domain: Mapped[str] = mapped_column(String(50), nullable=False, default="uncategorized")
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    embedding = mapped_column(Vector(256), nullable=True)
    pypi_package: Mapped[str | None] = mapped_column(String(200))
    npm_package: Mapped[str | None] = mapped_column(String(200))
    downloads_monthly: Mapped[int] = mapped_column(BigInteger, default=0)
    downloads_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
