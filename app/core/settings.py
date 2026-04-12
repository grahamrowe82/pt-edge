from pydantic_settings import BaseSettings as PydanticBaseSettings


class EdgeBaseSettings(PydanticBaseSettings):
    """Base settings shared across all *-edge sites. Domain-specific settings subclass this."""
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/edge"
    DATABASE_URL_READONLY: str = ""
    API_TOKEN: str = "dev-token"
    OPENAI_API_KEY: str = ""
    SNAPSHOT_RETENTION_DAYS: int = 365

    # Domain subclasses override these
    API_KEY_PREFIX: str = "edge_"
    API_KEY_LENGTH: int = 36  # prefix + hex
    RATE_LIMIT_TIERS: dict = {"anonymous": 100, "free": 1_000, "pro": 10_000}

    model_config = {"env_file": ".env", "case_sensitive": True, "extra": "ignore"}
