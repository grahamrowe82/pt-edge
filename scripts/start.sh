#!/bin/sh
set -e

echo "Generating static directory sites..."
python scripts/generate_site.py --domain mcp --output-dir site
python scripts/generate_site.py --domain agents --output-dir site/agents
python scripts/generate_site.py --domain rag --output-dir site/rag
python scripts/generate_site.py --domain ai-coding --output-dir site/ai-coding

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
