import contextvars
import functools
import time
import logging
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models import ToolUsage

logger = logging.getLogger(__name__)

# Contextvar set by middleware/endpoint before tool execution
_request_client_ip: contextvars.ContextVar[str] = contextvars.ContextVar("client_ip", default="")
_request_user_agent: contextvars.ContextVar[str] = contextvars.ContextVar("user_agent", default="")


def set_request_context(client_ip: str, user_agent: str):
    """Set request context for the current async task. Called from middleware."""
    _request_client_ip.set(client_ip)
    _request_user_agent.set(user_agent)


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

        client_ip = _request_client_ip.get("") or None
        user_agent = _request_user_agent.get("") or None

        usage = ToolUsage(
            tool_name=tool_name,
            params=params_json,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
            result_size=result_size,
            client_ip=client_ip,
            user_agent=user_agent[:500] if user_agent and len(user_agent) > 500 else user_agent,
        )
        session.add(usage)
        session.commit()
        session.close()
    except Exception:
        logger.debug(f"Failed to log usage for {tool_name}", exc_info=True)
