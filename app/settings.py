from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/pt_edge"
    API_TOKEN: str = "dev-token"
    GITHUB_TOKEN: str = ""
    GITHUB_RATE_LIMIT: float = 10.0  # requests per second
    DATABASE_URL_READONLY: str = ""  # separate read-only connection for query(); falls back to DATABASE_URL
    OPENAI_API_KEY: str = ""  # empty = embeddings disabled, everything still works
    ANTHROPIC_API_KEY: str = ""  # for newsletter LLM extraction; empty = entries stored without summaries
    V2EX_TOKEN: str = ""  # Personal Access Token from v2ex.com; empty = V2EX ingest skipped
    RENDER_API_KEY: str = ""  # Render API key for MCP integration; not used by app code
    RENDER_DEPLOY_HOOK_URL: str = ""  # Render deploy webhook for static site rebuilds
    SEMANTIC_SCHOLAR_API_KEY: str = ""  # optional; unauthenticated access works
    REDDIT_CLIENT_ID: str = ""  # empty = Reddit ingest skipped
    REDDIT_CLIENT_SECRET: str = ""
    ANTHROPIC_RPM: int = 120  # Anthropic rate limit (Tier 2 = 1000 RPM, use 120 for safety)
    OPENAI_RPM: int = 400  # OpenAI rate limit (500 RPM, use 400 for safety)
    GEMINI_API_KEY: str = ""  # Google Gemini API key; empty = Gemini disabled
    GEMINI_RPM: int = 1000  # Gemini rate limit (paid tier supports 2000+, start conservative)
    GEMINI_MODEL: str = "gemini-2.5-flash"  # Gemini model ID
    SNAPSHOT_RETENTION_DAYS: int = 365  # how long to keep daily snapshots (not wired to pruning yet)
    GSC_CLIENT_ID: str = ""
    GSC_CLIENT_SECRET: str = ""
    GSC_REFRESH_TOKEN: str = ""
    GSC_PROPERTY: str = "sc-domain:mcp.phasetransitions.ai"  # GSC property URI
    UMAMI_DATABASE_URL: str = ""  # Umami analytics DB (external); empty = Umami signals skipped
    UMAMI_WEBSITE_ID: str = ""  # Umami website ID to filter events
    LLM_BUDGET_MULTIPLIER: float = 2.0  # scales content pipeline LLM spend; 2.0 = double output

    model_config = {"env_file": ".env", "case_sensitive": True}


settings = Settings()
