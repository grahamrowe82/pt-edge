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
python scripts/generate_site.py --domain ml-frameworks --output-dir site/ml-frameworks
python scripts/generate_site.py --domain llm-tools --output-dir site/llm-tools
python scripts/generate_site.py --domain nlp --output-dir site/nlp
python scripts/generate_site.py --domain transformers --output-dir site/transformers
python scripts/generate_site.py --domain generative-ai --output-dir site/generative-ai
python scripts/generate_site.py --domain computer-vision --output-dir site/computer-vision
python scripts/generate_site.py --domain data-engineering --output-dir site/data-engineering
python scripts/generate_site.py --domain mlops --output-dir site/mlops

echo "Generating deep dive pages..."
python scripts/generate_deep_dives.py --output-dir site

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
