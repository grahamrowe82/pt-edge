from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.settings import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

# Read-only engine for the query() tool — uses a separate DB role if configured,
# otherwise falls back to the main engine (regex validation still applies).
_ro_url = settings.DATABASE_URL_READONLY or settings.DATABASE_URL
readonly_engine = create_engine(_ro_url, pool_pre_ping=True)
