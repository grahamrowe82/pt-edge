"""Ingest releases only."""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from app.ingest.releases import ingest_releases

if __name__ == "__main__":
    result = asyncio.run(ingest_releases())
    print(f"\nResult: {result}")
