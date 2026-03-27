#!/usr/bin/env bash
# Push MCP Quality Index datasets to Hugging Face.
#
# Prerequisites:
#   1. pip install huggingface_hub
#   2. Create a HF dataset repo: huggingface-cli repo create mcp-quality-index --type dataset
#   3. Set HF_TOKEN env var (write-access token)
#
# Usage:
#   HF_TOKEN=hf_xxx bash scripts/push_to_huggingface.sh
#
set -euo pipefail

HF_REPO="grahamrowe82/mcp-quality-index"
WORK_DIR="/tmp/mcp-quality-index"
HF_DIR="/tmp/hf-mcp-quality-index"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "${HF_TOKEN:-}" ]; then
    echo "Error: HF_TOKEN is not set"
    exit 1
fi

# Clone or pull the GitHub data repo
if [ -d "$WORK_DIR/.git" ]; then
    cd "$WORK_DIR" && git pull --ff-only
else
    git clone --depth 1 "https://github.com/${HF_REPO}.git" "$WORK_DIR"
fi

# Clone or pull the HF repo
if [ -d "$HF_DIR/.git" ]; then
    cd "$HF_DIR" && git pull --ff-only
else
    git clone "https://huggingface:${HF_TOKEN}@huggingface.co/datasets/${HF_REPO}" "$HF_DIR"
fi

# Copy dataset card and data files
cp "$WORK_DIR/huggingface/README.md" "$HF_DIR/README.md"
cp "$WORK_DIR/data/"*.json "$HF_DIR/"

# Commit and push
cd "$HF_DIR"
git add -A
if git diff --cached --quiet; then
    echo "No changes to push to Hugging Face"
    exit 0
fi

git config user.name "PT-Edge Bot"
git config user.email "bot@phasetransitions.ai"
git commit -m "Daily update: $(date -u +%Y-%m-%d)"
git push
echo "Dataset pushed to Hugging Face successfully"
