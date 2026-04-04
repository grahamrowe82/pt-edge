"""Generate properly capitalised display labels for all categories.

Uses Haiku to convert hyphenated slugs to display labels, preserving
acronyms (MCP, AI, TTS, LLM, API, NLP, ONNX, OCR, etc).

Usage:
    python scripts/fix_category_labels.py              # generate + save
    python scripts/fix_category_labels.py --apply      # apply from saved file
"""
import argparse
import asyncio
import json
import logging
import os
import sys

from sqlalchemy import text as sql_text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db import engine, readonly_engine
from app.ingest.llm import call_llm_text

logger = logging.getLogger(__name__)

SAVE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "category_labels.json")

PROMPT = """Convert these hyphenated category slugs to properly capitalised display labels.

Rules:
- Preserve ALL acronyms in uppercase: MCP, AI, TTS, STT, LLM, API, NLP, ONNX, OCR, FPGA, HPC, ASR, DNA, RNA, EEG, MEG, CFD, MNIST, CIFAR, GPU, CPU, TPU, GAN, VAE, BERT, GPT, SQL, SSH, AWS, GCP, CLI, IDE, PDF, CSV, JSON, XML, REST, HTTP, SSE, RBAC, OAuth, WebRTC, ComfyUI, FastAPI, PyTorch, TensorFlow, LangChain, LlamaIndex, MongoDB, PostgreSQL, MySQL, Redis, Docker, Kubernetes, GitHub, GitLab, VS Code, npm, PyPI
- Normal title case for everything else
- Keep proper nouns capitalised: Rust, Python, Go, Java, TypeScript, JavaScript, React, Vue, Angular, Swift, Kotlin
- Keep product names as they are: ComfyUI, FastMCP, OpenAI, Anthropic, DeepSeek, HuggingFace

Input (one per line):
{slugs}

Output (one per line, same order, just the label):"""


def fetch_all_labels():
    with readonly_engine.connect() as conn:
        rows = conn.execute(sql_text(
            "SELECT DISTINCT domain, label FROM category_centroids ORDER BY domain, label"
        )).fetchall()
    return [(r._mapping["domain"], r._mapping["label"]) for r in rows]


async def generate_labels(labels):
    """Batch labels to Haiku for capitalisation. Process in chunks of 50."""
    results = {}
    chunk_size = 50

    for i in range(0, len(labels), chunk_size):
        chunk = labels[i:i + chunk_size]
        slugs = "\n".join(label for _, label in chunk)

        result = await call_llm_text(
            PROMPT.format(slugs=slugs),
            max_tokens=2000,
        )
        if not result:
            # Fall back to .title() for this chunk
            for domain, label in chunk:
                results[(domain, label)] = label.replace("-", " ").title()
            continue

        lines = [l.strip() for l in result.strip().split("\n") if l.strip()]
        for j, (domain, label) in enumerate(chunk):
            if j < len(lines):
                results[(domain, label)] = lines[j]
            else:
                results[(domain, label)] = label.replace("-", " ").title()

        print(f"  {i + len(chunk)}/{len(labels)} labels generated")

    return results


def save_labels(results, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Convert tuple keys to strings for JSON
    data = {f"{d}|{l}": display for (d, l), display in results.items()}
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(data)} labels to {path}")


def load_labels(path):
    with open(path) as f:
        data = json.load(f)
    return {tuple(k.split("|", 1)): v for k, v in data.items()}


def apply_labels(results):
    with engine.connect() as conn:
        for (domain, label), display in results.items():
            conn.execute(sql_text("""
                UPDATE category_centroids
                SET display_label = :display
                WHERE domain = :domain AND label = :label
            """), {"display": display, "domain": domain, "label": label})
        conn.commit()
    print(f"Applied {len(results)} display labels to category_centroids")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply from saved file only")
    parser.add_argument("--save-path", default=SAVE_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if args.apply:
        results = load_labels(args.save_path)
        apply_labels(results)
        return

    print("Fetching category labels...")
    labels = fetch_all_labels()
    print(f"  {len(labels)} labels to process")

    print("Generating display labels via Haiku...")
    results = await generate_labels(labels)

    save_labels(results, args.save_path)
    apply_labels(results)

    # Show samples
    print("\nSamples:")
    for (d, l), display in list(results.items())[:20]:
        print(f"  {d}: {l} → {display}")


if __name__ == "__main__":
    asyncio.run(main())
