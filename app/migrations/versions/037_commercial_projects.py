"""Add commercial_projects table for closed-source AI tool tracking.

Revision ID: 037
"""

from alembic import op
import sqlalchemy as sa

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE commercial_projects (
            id SERIAL PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            slug VARCHAR(200) NOT NULL UNIQUE,
            url TEXT,
            category VARCHAR(100),
            description TEXT,
            pricing_model VARCHAR(50),
            last_verified_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Seed ~20 significant closed-source AI projects
    op.execute("""
        INSERT INTO commercial_projects (name, slug, url, category, description, pricing_model) VALUES
        ('Devin', 'devin', 'https://devin.ai', 'ai-coding', 'Autonomous AI software engineer by Cognition', 'paid'),
        ('Cursor', 'cursor', 'https://cursor.com', 'ai-coding', 'AI-first code editor built on VS Code', 'freemium'),
        ('Windsurf', 'windsurf', 'https://windsurf.com', 'ai-coding', 'AI-powered IDE by Codeium', 'freemium'),
        ('Replit Agent', 'replit-agent', 'https://replit.com', 'ai-coding', 'AI agent for building apps on Replit', 'freemium'),
        ('GitHub Copilot', 'github-copilot', 'https://github.com/features/copilot', 'ai-coding', 'AI pair programmer by GitHub/Microsoft', 'freemium'),
        ('Amazon Q Developer', 'amazon-q-developer', 'https://aws.amazon.com/q/developer/', 'ai-coding', 'AI coding assistant by AWS', 'freemium'),
        ('Tabnine', 'tabnine', 'https://www.tabnine.com', 'ai-coding', 'AI code completion with local and cloud models', 'freemium'),
        ('v0', 'v0', 'https://v0.dev', 'ai-coding', 'AI UI generator by Vercel', 'freemium'),
        ('Bolt', 'bolt', 'https://bolt.new', 'ai-coding', 'AI full-stack app builder by StackBlitz', 'freemium'),
        ('Lovable', 'lovable', 'https://lovable.dev', 'ai-coding', 'AI app builder for non-technical users', 'freemium'),
        ('Claude', 'claude', 'https://claude.ai', 'llm-consumer', 'AI assistant by Anthropic', 'freemium'),
        ('ChatGPT', 'chatgpt', 'https://chat.openai.com', 'llm-consumer', 'AI assistant by OpenAI', 'freemium'),
        ('Gemini', 'gemini', 'https://gemini.google.com', 'llm-consumer', 'AI assistant by Google DeepMind', 'freemium'),
        ('Grok', 'grok', 'https://grok.x.ai', 'llm-consumer', 'AI assistant by xAI', 'freemium'),
        ('Perplexity', 'perplexity', 'https://perplexity.ai', 'llm-consumer', 'AI-powered search engine', 'freemium'),
        ('Jasper', 'jasper', 'https://www.jasper.ai', 'content-generation', 'AI content creation platform for marketing', 'paid'),
        ('Copy.ai', 'copy-ai', 'https://www.copy.ai', 'content-generation', 'AI-powered copywriting and workflow automation', 'freemium'),
        ('Writer', 'writer', 'https://writer.com', 'content-generation', 'Enterprise AI content platform', 'enterprise'),
        ('Vercel AI SDK', 'vercel-ai-sdk', 'https://sdk.vercel.ai', 'ai-infra', 'AI SDK for building AI-powered web apps', 'free'),
        ('Notion AI', 'notion-ai', 'https://www.notion.so/product/ai', 'productivity', 'AI features integrated into Notion workspace', 'freemium')
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS commercial_projects")
