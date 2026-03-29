#!/bin/sh
set -e

# Start uvicorn first so Render sees the port immediately
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 &
UVICORN_PID=$!

# Generate static sites in the background (DB queries can take minutes)
echo "Generating static directory sites..."
for domain in mcp agents rag ai-coding voice-ai diffusion vector-db embeddings prompt-engineering ml-frameworks llm-tools nlp transformers generative-ai computer-vision data-engineering mlops; do
  if [ "$domain" = "mcp" ]; then
    python scripts/generate_site.py --domain $domain --output-dir site || echo "Failed: $domain"
  else
    python scripts/generate_site.py --domain $domain --output-dir site/$domain || echo "Failed: $domain"
  fi
done
echo "Static site generation complete"

# Wait for uvicorn
wait $UVICORN_PID
