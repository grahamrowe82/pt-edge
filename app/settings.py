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
    ANTHROPIC_RPM: int = 40  # Anthropic rate limit (Tier 1 = 50 RPM, use 40 for safety)
    OPENAI_RPM: int = 400  # OpenAI rate limit (500 RPM, use 400 for safety)

    model_config = {"env_file": ".env", "case_sensitive": True}


settings = Settings()
