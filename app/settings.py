from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/pt_edge"
    API_TOKEN: str = "dev-token"
    GITHUB_TOKEN: str = ""
    GITHUB_RATE_LIMIT: float = 10.0  # requests per second
    OPENAI_API_KEY: str = ""  # empty = embeddings disabled, everything still works

    model_config = {"env_file": ".env", "case_sensitive": True}


settings = Settings()
