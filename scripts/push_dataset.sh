#!/usr/bin/env bash
# Export PT-Edge datasets and push to the mcp-quality-index GitHub repo.
# Called by the daily ingest pipeline. Fails gracefully.
set -euo pipefail

REPO_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/grahamrowe82/mcp-quality-index.git"
WORK_DIR="/tmp/mcp-quality-index"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Clone (shallow) or pull
if [ -d "$WORK_DIR/.git" ]; then
    cd "$WORK_DIR" && git pull --ff-only
else
    git clone --depth 1 "$REPO_URL" "$WORK_DIR"
fi

# Run export
cd "$SCRIPT_DIR/.."
python scripts/export_dataset.py --output-dir "$WORK_DIR/data"

# Update badge count in README
cd "$WORK_DIR"
SCORES=$(python3 -c "import json; print(json.load(open('data/metadata.json'))['datasets']['mcp-scores.json']['records'])")
SCORES_FMT=$(printf "%'d" "$SCORES")
sed -i.bak "s|servers_scored-[0-9,]*-blue|servers_scored-${SCORES_FMT}-blue|" README.md
rm -f README.md.bak

# Commit and push (skip if no changes)
git add data/ README.md
if git diff --cached --quiet; then
    echo "No changes to push"
    exit 0
fi

git config user.name "PT-Edge Bot"
git config user.email "bot@phasetransitions.ai"
git commit -m "Daily update: ${SCORES_FMT} servers scored — $(date -u +%Y-%m-%d)"
git push
echo "Dataset pushed successfully"
