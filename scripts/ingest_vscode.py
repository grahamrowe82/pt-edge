import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ingest.vscode_marketplace import ingest_vscode

logging.basicConfig(level=logging.INFO)
asyncio.run(ingest_vscode())
