"""Bulk backfill AI summaries for repos.

Usage:
    python scripts/backfill_summaries.py [--limit 2000] [--min-score 50]

Processes repos in descending quality score order. Run multiple times
to work through the backlog faster than the daily 200-per-run ingest.
"""
import asyncio
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.ingest.ai_repo_summaries import generate_ai_summaries


async def main():
    parser = argparse.ArgumentParser(description="Bulk backfill AI summaries")
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--min-score", type=int, default=50)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    result = await generate_ai_summaries(limit=args.limit, min_score=args.min_score)
    print(f"\nDone: {result}")


if __name__ == "__main__":
    asyncio.run(main())
