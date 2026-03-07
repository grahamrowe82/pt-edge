import functools
import json
import time
import logging
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models import ToolUsage

logger = logging.getLogger(__name__)


def track_usage(func):
    """Decorator that logs MCP tool usage. Swallows its own errors."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.time()
        tool_name = func.__name__
        try:
            result = await func(*args, **kwargs)
            duration_ms = int((time.time() - start) * 1000)
            _log_usage(
                tool_name, kwargs, duration_ms, True, None,
                len(str(result)) if result else 0,
            )
            return result
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            _log_usage(tool_name, kwargs, duration_ms, False, str(e)[:500], 0)
            raise

    return wrapper


def _log_usage(tool_name, params, duration_ms, success, error_message, result_size):
    """Fire-and-forget: never let tracking break a tool."""
    try:
        session = SessionLocal()
        # Truncate large params
        params_json = {}
        for k, v in (params or {}).items():
            s = str(v)
            params_json[k] = s[:200] if len(s) > 200 else s

        usage = ToolUsage(
            tool_name=tool_name,
            params=params_json,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
            result_size=result_size,
        )
        session.add(usage)
        session.commit()
        session.close()
    except Exception:
        logger.debug(f"Failed to log usage for {tool_name}", exc_info=True)
