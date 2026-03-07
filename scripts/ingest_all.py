"""Run full ingest cycle."""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from app.ingest.runner import run_all

if __name__ == "__main__":
    results = asyncio.run(run_all())
    print(f"\nResults: {results}")
