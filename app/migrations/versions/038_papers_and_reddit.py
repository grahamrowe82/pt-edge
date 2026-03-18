"""Add papers, paper_snapshots, and reddit_posts tables.

papers + paper_snapshots: Academic paper tracking via Semantic Scholar (Phase 3.1)
reddit_posts: Reddit social signal aggregation stub (Phase 3.2)

Revision ID: 038
"""

from alembic import op
import sqlalchemy as sa

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE papers (
            id SERIAL PRIMARY KEY,
            semantic_scholar_id VARCHAR(40) NOT NULL UNIQUE,
            arxiv_id VARCHAR(50),
            doi VARCHAR(200),
            title TEXT NOT NULL,
            authors JSONB,
            abstract TEXT,
            venue VARCHAR(300),
            year INTEGER,
            publication_date DATE,
            citation_count INTEGER DEFAULT 0,
            open_access_url TEXT,
            project_id INTEGER REFERENCES projects(id),
            lab_id INTEGER REFERENCES labs(id),
            discovered_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_papers_project_id ON papers (project_id)")
    op.execute("CREATE INDEX ix_papers_lab_id ON papers (lab_id)")
    op.execute("CREATE INDEX ix_papers_year ON papers (year)")
    op.execute("CREATE INDEX ix_papers_arxiv_id ON papers (arxiv_id)")

    op.execute("""
        CREATE TABLE paper_snapshots (
            id SERIAL PRIMARY KEY,
            paper_id INTEGER NOT NULL REFERENCES papers(id),
            snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
            citation_count INTEGER NOT NULL DEFAULT 0,
            captured_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(paper_id, snapshot_date)
        )
    """)

    op.execute("""
        CREATE TABLE reddit_posts (
            id SERIAL PRIMARY KEY,
            reddit_id VARCHAR(20) NOT NULL UNIQUE,
            subreddit VARCHAR(100) NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            selftext TEXT,
            author VARCHAR(100),
            score INTEGER DEFAULT 0,
            num_comments INTEGER DEFAULT 0,
            permalink TEXT,
            posted_at TIMESTAMPTZ NOT NULL,
            captured_at TIMESTAMPTZ DEFAULT NOW(),
            project_id INTEGER REFERENCES projects(id),
            lab_id INTEGER REFERENCES labs(id)
        )
    """)
    op.execute("CREATE INDEX ix_reddit_posts_subreddit ON reddit_posts (subreddit)")
    op.execute("CREATE INDEX ix_reddit_posts_project_id ON reddit_posts (project_id)")
    op.execute("CREATE INDEX ix_reddit_posts_posted_at ON reddit_posts (posted_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reddit_posts")
    op.execute("DROP TABLE IF EXISTS paper_snapshots")
    op.execute("DROP TABLE IF EXISTS papers")
