from app.core.settings import EdgeBaseSettings


class Settings(EdgeBaseSettings):
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/pt_edge"
    API_KEY_PREFIX: str = "pte_"
    GITHUB_TOKEN: str = ""
    GITHUB_RATE_LIMIT: float = 10.0  # requests per second
    GITHUB_APP_ID: str = ""  # GitHub App ID -- when set, uses App auth instead of PAT
    GITHUB_APP_INSTALLATION_ID: str = ""  # Installation ID for App auth
    GITHUB_APP_PRIVATE_KEY_FILE: str = ""  # Path to PEM file for App auth
    V2EX_TOKEN: str = ""  # Personal Access Token from v2ex.com; empty = V2EX ingest skipped
    RENDER_API_KEY: str = ""  # Render API key for MCP integration; not used by app code
    RENDER_DEPLOY_HOOK_URL: str = ""  # Render deploy webhook for static site rebuilds
    SEMANTIC_SCHOLAR_API_KEY: str = ""  # optional; unauthenticated access works
    REDDIT_CLIENT_ID: str = ""  # empty = Reddit ingest skipped
    REDDIT_CLIENT_SECRET: str = ""
    GEMINI_API_KEY: str = ""  # Google Gemini API key; empty = Gemini disabled
    GEMINI_MODEL: str = "gemini-2.5-flash"  # Gemini model ID
    GSC_CLIENT_ID: str = ""
    GSC_CLIENT_SECRET: str = ""
    GSC_REFRESH_TOKEN: str = ""
    GSC_PROPERTY: str = "sc-domain:mcp.phasetransitions.ai"  # GSC property URI
    UMAMI_DATABASE_URL: str = ""  # Umami analytics DB (external); empty = Umami signals skipped
    UMAMI_WEBSITE_ID: str = ""  # Umami website ID to filter events
    LLM_BUDGET_MULTIPLIER: float = 5.0  # scales content pipeline LLM spend; 5.0 = 20K summaries/day on Gemini
    CANONICAL_HOST: str = ""  # set in production; empty = host redirect disabled

    model_config = {"env_file": "domains/ai/.env", "case_sensitive": True, "extra": "ignore"}


settings = Settings()
