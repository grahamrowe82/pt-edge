"""Ingest GitHub stats only."""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from app.ingest.github import ingest_github

if __name__ == "__main__":
    result = asyncio.run(ingest_github())
    print(f"\nResult: {result}")
