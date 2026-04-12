#!/bin/sh
set -e

echo "Generating static site..."
python domains/cyber/scripts/generate_site.py --output-dir domains/cyber/site --base-url https://cyber.phasetransitions.ai

exec uvicorn domains.cyber.app.main:app --host 0.0.0.0 --port 8000 --workers 2
