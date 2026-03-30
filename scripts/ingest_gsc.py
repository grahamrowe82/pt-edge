"""Fetch Google Search Console data into Postgres."""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

import asyncio

from app.ingest.gsc import ingest_gsc

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest GSC search analytics")
    parser.add_argument(
        "--days", type=int, default=3,
        help="Days to backfill (default 3, max ~16 months)",
    )
    args = parser.parse_args()

    start = time.time()
    try:
        result = asyncio.run(ingest_gsc(days_back=args.days))
        elapsed = time.time() - start
        print(f"\n✓ GSC ingest complete: {result['rows']} rows, {result['days']} days ({elapsed:.0f}s)")
        sys.exit(0)
    except Exception as e:
        logging.exception("GSC ingest failed")
        print(f"\n⚠ Failed: {e}")
        sys.exit(1)
