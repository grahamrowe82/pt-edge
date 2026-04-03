"""Run full ingest cycle: all data sources + materialized view refresh."""
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from app.ingest.runner import run_all, acquire_ingest_lock, release_ingest_lock

if __name__ == "__main__":
    if not acquire_ingest_lock():
        print("Another ingest is already running — exiting")
        sys.exit(0)

    try:
        start = time.time()
        results = asyncio.run(run_all())
        elapsed = time.time() - start

        errors = [k for k, v in results.items() if isinstance(v, dict) and "error" in v]
        if errors:
            print(f"\n⚠ Ingest completed with errors in: {', '.join(errors)}")
            for k in errors:
                print(f"  {k}: {results[k]['error'][:200]}")
            print(f"  Elapsed: {elapsed:.0f}s")
            sys.exit(1)
        else:
            print(f"\n✓ Ingest complete ({elapsed:.0f}s)")
            for k, v in results.items():
                print(f"  {k}: {v}")
            sys.exit(0)
    finally:
        release_ingest_lock()
