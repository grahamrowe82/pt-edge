import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ingest.dockerhub import ingest_dockerhub

logging.basicConfig(level=logging.INFO)
asyncio.run(ingest_dockerhub())
