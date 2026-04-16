"""Run a single task handler in an isolated subprocess.

Used by the subprocess wrapper to execute heavy handlers (UMAP, Gemini,
embeddings) in a process that exits cleanly when done, returning all
memory to the OS.

Usage:
    echo '{"id": 1, "task_type": "product_guidance", ...}' | \
        python domains/cyber/scripts/run_handler.py \
            domains.cyber.app.queue.handlers.product_guidance \
            _run_guidance_pipeline

Exit codes:
    0 — success (result JSON on stdout)
    1 — retryable error
    2 — PermanentTaskError
    3 — ResourceExhaustedError
"""
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path

# Match ingest_worker.py: add repo root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

# Capture real stdout before redirecting — only the result goes here.
_result_fd = os.fdopen(os.dup(1), "w")
sys.stdout = sys.stderr  # all prints/logging go to stderr

# Patch app.db to point at the cyber database (same as worker.py lines 10-15)
import app.db as _app_db  # noqa: E402
from domains.cyber.app.db import engine, SessionLocal, readonly_engine  # noqa: E402

_app_db.engine = engine
_app_db.SessionLocal = SessionLocal
_app_db.readonly_engine = readonly_engine


def _write_error(exit_code: int, exc: Exception) -> None:
    """Write structured error JSON to stderr and exit."""
    error = {"type": type(exc).__name__, "message": str(exc)[:500]}
    if hasattr(exc, "resource_type"):
        error["resource_type"] = exc.resource_type
    sys.stderr.write(json.dumps(error))
    sys.exit(exit_code)


async def _run(module_path: str, func_name: str, task: dict) -> dict:
    mod = importlib.import_module(module_path)
    func = getattr(mod, func_name)
    result = await func(task)
    return result if result is not None else {}


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <module_path> <func_name>", file=sys.stderr)
        sys.exit(1)

    module_path = sys.argv[1]
    func_name = sys.argv[2]
    task = json.loads(sys.stdin.read())

    try:
        result = asyncio.run(_run(module_path, func_name, task))
        _result_fd.write(json.dumps(result))
        _result_fd.flush()
        sys.exit(0)
    except Exception as exc:
        from app.core.queue.errors import PermanentTaskError
        from app.core.ingest.budget import ResourceExhaustedError

        if isinstance(exc, PermanentTaskError):
            _write_error(2, exc)
        elif isinstance(exc, ResourceExhaustedError):
            _write_error(3, exc)
        else:
            _write_error(1, exc)


if __name__ == "__main__":
    main()
