from app.core.settings import EdgeBaseSettings


class Settings(EdgeBaseSettings):
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/cyber_edge"
    API_KEY_PREFIX: str = "cye_"
    NVD_API_KEY: str = ""  # NVD API — empty = 5 req/30s, with key = 50 req/30s
    ANTHROPIC_API_KEY: str = ""  # future LLM features; empty = skipped
    GEMINI_API_KEY: str = ""  # Google Gemini API key; empty = Gemini disabled
    GEMINI_MODEL: str = "gemini-2.5-flash"
    OPENAI_RPM: int = 400  # OpenAI rate limit (500 RPM, use 400 for safety)
    RENDER_API_KEY: str = ""  # worker self-deploy after successful ingest
    RENDER_SERVICE_ID: str = ""  # Render service ID for the ingest worker

    model_config = {"env_file": "domains/cyber/.env", "case_sensitive": True, "extra": "ignore"}


settings = Settings()
