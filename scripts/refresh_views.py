"""Refresh all materialized views."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from app.views.refresh import refresh_all_views

if __name__ == "__main__":
    result = refresh_all_views()
    print(f"\nResult: {result}")
