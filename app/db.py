# Re-export from core for backward compatibility
from app.core.db import engine, SessionLocal, readonly_engine

__all__ = ["engine", "SessionLocal", "readonly_engine"]
