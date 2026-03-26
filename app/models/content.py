from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
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
    llm_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    dependency_count: Mapped[int] = mapped_column(Integer, default=0)
    deps_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subcategory: Mapped[str | None] = mapped_column(String(50))
    crate_package: Mapped[str | None] = mapped_column(String(200))
    commits_30d: Mapped[int | None] = mapped_column(Integer)
    commits_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublicAPI(Base):
    __tablename__ = "public_apis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    service_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    categories: Mapped[list | None] = mapped_column(ARRAY(Text))
    openapi_version: Mapped[str | None] = mapped_column(String(20))
    spec_url: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(Text)
    contact_url: Mapped[str | None] = mapped_column(Text)
    api_version: Mapped[str | None] = mapped_column(String(50))
    added_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    embedding = mapped_column(Vector(256), nullable=True)
    spec_json: Mapped[dict | None] = mapped_column(JSONB)
    spec_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    spec_error: Mapped[str | None] = mapped_column(String(500))


class PackageDep(Base):
    __tablename__ = "package_deps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(Integer, ForeignKey("ai_repos.id"), nullable=False)
    dep_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dep_spec: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    is_dev: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class HFDataset(Base):
    __tablename__ = "hf_datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hf_id: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    pretty_name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(200))
    tags: Mapped[list | None] = mapped_column(ARRAY(Text))
    task_categories: Mapped[list | None] = mapped_column(ARRAY(Text))
    languages: Mapped[list | None] = mapped_column(ARRAY(Text))
    downloads: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    embedding = mapped_column(Vector(256), nullable=True)


class BuilderTool(Base):
    __tablename__ = "builder_tools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)

    # MCP status
    mcp_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unchecked")
    mcp_type: Mapped[str | None] = mapped_column(String(30))
    mcp_endpoint: Mapped[str | None] = mapped_column(Text)
    mcp_repo_slug: Mapped[str | None] = mapped_column(String(300))
    mcp_npm_package: Mapped[str | None] = mapped_column(String(300))
    mcp_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Provenance
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="apis_guru")
    source_ref: Mapped[str | None] = mapped_column(String(300))

    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

class CommercialProject(Base):
    __tablename__ = "commercial_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    pricing_model: Mapped[str | None] = mapped_column(String(50))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    semantic_scholar_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    arxiv_id: Mapped[str | None] = mapped_column(String(50))
    doi: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[dict | None] = mapped_column(JSONB)
    abstract: Mapped[str | None] = mapped_column(Text)
    venue: Mapped[str | None] = mapped_column(String(300))
    year: Mapped[int | None] = mapped_column(Integer)
    publication_date: Mapped[datetime | None] = mapped_column(Date)
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    open_access_url: Mapped[str | None] = mapped_column(Text)
    project_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("projects.id"))
    lab_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("labs.id"))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PaperSnapshot(Base):
    __tablename__ = "paper_snapshots"
    __table_args__ = (UniqueConstraint("paper_id", "snapshot_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), nullable=False)
    snapshot_date: Mapped[datetime] = mapped_column(Date, nullable=False, server_default=func.current_date())
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RedditPost(Base):
    __tablename__ = "reddit_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reddit_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    subreddit: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    selftext: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(100))
    score: Mapped[int] = mapped_column(Integer, default=0)
    num_comments: Mapped[int] = mapped_column(Integer, default=0)
    permalink: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    project_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("projects.id"))
    lab_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("labs.id"))


class HFModel(Base):
    __tablename__ = "hf_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hf_id: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    pretty_name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(200))
    tags: Mapped[list | None] = mapped_column(ARRAY(Text))
    pipeline_tag: Mapped[str | None] = mapped_column(String(100))
    library_name: Mapped[str | None] = mapped_column(String(100))
    languages: Mapped[list | None] = mapped_column(ARRAY(Text))
    downloads: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    embedding = mapped_column(Vector(256), nullable=True)
