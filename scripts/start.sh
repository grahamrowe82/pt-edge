#!/bin/sh
set -e

echo "Generating static directory sites..."
python scripts/generate_site.py --domain mcp --output-dir site
python scripts/generate_site.py --domain agents --output-dir site/agents
python scripts/generate_site.py --domain rag --output-dir site/rag
python scripts/generate_site.py --domain ai-coding --output-dir site/ai-coding
python scripts/generate_site.py --domain voice-ai --output-dir site/voice-ai
python scripts/generate_site.py --domain diffusion --output-dir site/diffusion
python scripts/generate_site.py --domain vector-db --output-dir site/vector-db
python scripts/generate_site.py --domain embeddings --output-dir site/embeddings
python scripts/generate_site.py --domain prompt-engineering --output-dir site/prompt-engineering

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
