#!/bin/sh
set -e

# Generate static MCP directory site before starting the server
echo "Generating static directory site..."
python scripts/generate_site.py --output-dir site || echo "Site generation failed, starting without directory"

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
