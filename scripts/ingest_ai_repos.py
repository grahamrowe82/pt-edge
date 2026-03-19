"""Run weekly AI repos GitHub crawl (separated from daily ingest)."""
import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from app.ingest.ai_repos import ingest_ai_repos

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crawl GitHub for AI repos")
    parser.add_argument("--full", action="store_true", help="Force full crawl (skip incremental mode)")
    parser.add_argument("domains", nargs="*", help="Specific domain keys to crawl")
    args = parser.parse_args()

    start = time.time()
    try:
        results = asyncio.run(ingest_ai_repos(
            domains=args.domains or None,
            force_full=args.full,
        ))
        elapsed = time.time() - start
        print(f"\n✓ AI repos crawl complete ({elapsed:.0f}s)")
        print(f"  {results}")
        sys.exit(0)
    except Exception as e:
        elapsed = time.time() - start
        print(f"\n⚠ AI repos crawl failed after {elapsed:.0f}s: {e}")
        sys.exit(1)
