"""Run a handler function in an isolated subprocess.

Heavy handlers (UMAP, Gemini backfills, embedding pipelines) are delegated
to a subprocess so the worker process never loads their dependencies and
all memory is reclaimed by the OS when the subprocess exits.

Follows the pattern established by handle_compute_structural in
app/queue/handlers/compute_post_process.py.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

from app.core.ingest.budget import ResourceExhaustedError
from app.core.queue.errors import PermanentTaskError

logger = logging.getLogger(__name__)

_PROJECT_ROOT = str(
    Path(__file__).resolve().parent.parent.parent.parent.parent
)
_RUNNER_SCRIPT = str(
    Path(_PROJECT_ROOT) / "domains" / "cyber" / "scripts" / "run_handler.py"
)


async def run_in_subprocess(
    module_path: str,
    func_name: str,
    task: dict,
    timeout: int = 3600,
) -> dict:
    """Run a handler function in a subprocess and return its result.

    Args:
        module_path: Dotted module path (e.g. "domains.cyber.app.queue.handlers.product_guidance")
        func_name: Function name within the module (e.g. "_run_guidance_pipeline")
        task: Task dict (serialised to JSON on stdin)
        timeout: Seconds before killing the subprocess (default 1 hour)

    Returns:
        The handler's return dict.

    Raises:
        PermanentTaskError: Handler raised PermanentTaskError (exit code 2)
        ResourceExhaustedError: Budget exhausted (exit code 3)
        RuntimeError: Any other failure (exit code 1, timeout, etc.)
    """
    logger.info(
        f"Spawning subprocess: {module_path}.{func_name} "
        f"(timeout={timeout}s)"
    )

    proc = await asyncio.create_subprocess_exec(
        sys.executable, _RUNNER_SCRIPT, module_path, func_name,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=_PROJECT_ROOT,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(json.dumps(task).encode()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(
            f"{module_path}.{func_name} timed out after {timeout}s"
        )

    stderr_text = stderr.decode().strip() if stderr else ""

    if proc.returncode == 0:
        stdout_text = stdout.decode().strip() if stdout else ""
        if stdout_text:
            return json.loads(stdout_text)
        return {"status": "ok"}

    # Parse structured error from stderr
    error_info = {}
    if stderr_text:
        try:
            error_info = json.loads(stderr_text)
        except json.JSONDecodeError:
            error_info = {"message": stderr_text[:500]}

    error_msg = error_info.get("message", f"exit code {proc.returncode}")

    if proc.returncode == 2:
        raise PermanentTaskError(error_msg)
    elif proc.returncode == 3:
        resource = error_info.get("resource_type", "unknown")
        raise ResourceExhaustedError(resource)
    else:
        raise RuntimeError(
            f"{module_path}.{func_name} failed: {error_msg}"
        )
