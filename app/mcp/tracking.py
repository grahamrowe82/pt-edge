import contextvars
import functools
import time
import logging
from collections import defaultdict
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models import ToolUsage

logger = logging.getLogger(__name__)

# Contextvar set by middleware/endpoint before tool execution
_request_client_ip: contextvars.ContextVar[str] = contextvars.ContextVar("client_ip", default="")
_request_user_agent: contextvars.ContextVar[str] = contextvars.ContextVar("user_agent", default="")
_session_key: contextvars.ContextVar[str] = contextvars.ContextVar("session_key", default="")


def set_request_context(client_ip: str, user_agent: str, session_key: str = ""):
    """Set request context for the current async task. Called from middleware."""
    _request_client_ip.set(client_ip)
    _request_user_agent.set(user_agent)
    _session_key.set(session_key)


# ---------------------------------------------------------------------------
# Session workspace — in-memory store for full tool results
# ---------------------------------------------------------------------------

# {session_key: {data_key: (value, timestamp)}}
_workspace: dict[str, dict[str, tuple[str, float]]] = defaultdict(dict)
_WORKSPACE_TTL = 3600  # 1 hour


def _workspace_store(key: str, value: str):
    """Save a value to the current session's workspace."""
    session = _session_key.get("")
    if not session:
        return
    _workspace[session][key] = (value, time.time())


def _workspace_recall(key: str) -> str | None:
    """Retrieve a value from the current session's workspace."""
    session = _session_key.get("")
    if not session:
        return None
    entry = _workspace.get(session, {}).get(key)
    if entry and (time.time() - entry[1]) < _WORKSPACE_TTL:
        return entry[0]
    return None


def _workspace_list() -> dict[str, int]:
    """List keys in current session's workspace with sizes."""
    session = _session_key.get("")
    if not session:
        return {}
    now = time.time()
    return {
        k: len(v) for k, (v, ts) in _workspace.get(session, {}).items()
        if (now - ts) < _WORKSPACE_TTL
    }


def _workspace_cleanup():
    """Remove expired entries. Called periodically."""
    now = time.time()
    expired_sessions = []
    for session, data in _workspace.items():
        live = {k: (v, ts) for k, (v, ts) in data.items() if (now - ts) < _WORKSPACE_TTL}
        if not live:
            expired_sessions.append(session)
        else:
            _workspace[session] = live
    for s in expired_sessions:
        del _workspace[s]


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def compact_response(max_chars=1500):
    """Decorator that truncates tool output and saves full result to workspace.

    If response <= max_chars, returns as-is.
    If response > max_chars, saves full result to workspace and returns
    truncated output with a recall() hint.
    If caller passes detail='full', skips truncation entirely.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # detail='full' bypasses truncation
            if kwargs.get("detail") == "full":
                kwargs.pop("detail")
                return await func(*args, **kwargs)

            result = await func(*args, **kwargs)

            if not result or len(result) <= max_chars:
                return result

            # Build workspace key from function name + first meaningful arg
            key = func.__name__
            if args:
                key = f"{func.__name__}:{args[0]}"
            elif kwargs:
                first_val = next(iter(kwargs.values()), None)
                if first_val and isinstance(first_val, str):
                    key = f"{func.__name__}:{first_val}"

            _workspace_store(key, result)

            # Truncate at last newline after 60% mark for clean output
            truncated = result[:max_chars]
            last_nl = truncated.rfind("\n")
            if last_nl > max_chars * 0.6:
                truncated = truncated[:last_nl]

            return truncated + f"\n\n... truncated. recall('{key}') for full output."

        return wrapper
    return decorator


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
