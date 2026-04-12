"""MCP tool usage tracking decorator."""

import functools
import logging
import time

from sqlalchemy import text

from domains.cyber.app.db import engine

logger = logging.getLogger(__name__)


def track_usage(func):
    """Decorator to track MCP tool invocations. Fire-and-forget."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        tool_name = func.__name__
        t0 = time.time()
        success = True
        error_msg = None
        result_size = 0

        try:
            result = await func(*args, **kwargs)
            result_size = len(result) if isinstance(result, str) else 0
            return result
        except Exception as e:
            success = False
            error_msg = str(e)[:500]
            raise
        finally:
            duration_ms = int((time.time() - t0) * 1000)
            try:
                with engine.connect() as conn:
                    conn.execute(text("""
                        INSERT INTO tool_usage (tool_name, params, duration_ms, success, error_message, result_size)
                        VALUES (:tn, :params, :dur, :ok, :err, :rs)
                    """), {
                        "tn": tool_name,
                        "params": str(kwargs)[:500] if kwargs else None,
                        "dur": duration_ms,
                        "ok": success,
                        "err": error_msg,
                        "rs": result_size,
                    })
                    conn.commit()
            except Exception:
                pass  # never break tool execution

    return wrapper
