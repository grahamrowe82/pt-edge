"""Database-centric budget tracking for external API calls.

Every external API call should go through acquire_budget() before making
the HTTP request, and call record_call() after the request fires.

The database is the source of truth for:
- Daily/hourly budget (consumed vs limit)
- Provider-specific reset windows (rolling or calendar)
- RPM spacing (last_call_at)
- Adaptive backoff state (backoff_until, backoff_count)

Flow:
  1. acquire_budget("gemini")  — checks limits, enforces RPM, does NOT decrement
  2. make the HTTP request
  3. record_call("gemini")     — decrements consumed (only after call actually fired)
  4. record_success("gemini")  — clears backoff (if active)
  OR
  4. record_throttle("gemini") — sets exponential backoff (on 429)

See docs/strategy/resource-budget-infrastructure.md for full design.
"""

import asyncio
import logging

from sqlalchemy import text

from app.db import engine

logger = logging.getLogger(__name__)


class ResourceExhaustedError(Exception):
    """Daily/hourly budget exhausted for a resource type."""

    def __init__(self, resource_type: str):
        self.resource_type = resource_type
        super().__init__(f"Budget exhausted for {resource_type}")


class ResourceThrottledError(Exception):
    """Provider returned 429; backoff recorded in DB."""

    def __init__(self, resource_type: str):
        self.resource_type = resource_type
        super().__init__(f"Resource throttled: {resource_type}")


# Check budget and backoff, enforce RPM spacing. Does NOT decrement consumed.
_CHECK_SQL = text("""
    SELECT
      rpm,
      EXTRACT(EPOCH FROM (
        now() - COALESCE(last_call_at, '1970-01-01'::timestamptz)
      )) AS seconds_since_last,
      CASE
        -- Backed off
        WHEN backoff_until IS NOT NULL AND now() < backoff_until
        THEN 0
        -- Rolling: period expired, full budget available
        WHEN reset_mode = 'rolling'
          AND now() >= period_start + (period_hours || ' hours')::interval
        THEN budget
        -- Calendar: period expired, full budget available
        WHEN reset_mode = 'calendar'
          AND period_start < (
            date_trunc('day', now() AT TIME ZONE reset_tz)
            + (reset_hour || ' hours')::interval
          ) AT TIME ZONE reset_tz
          AND now() >= (
            date_trunc('day', now() AT TIME ZONE reset_tz)
            + (reset_hour || ' hours')::interval
          ) AT TIME ZONE reset_tz
        THEN budget
        -- Window still active
        ELSE budget - consumed
      END AS remaining
    FROM resource_budgets
    WHERE resource_type = :rt
""")

# Decrement budget and update last_call_at. Called AFTER the API call fires.
_RECORD_CALL_SQL = text("""
    UPDATE resource_budgets
    SET
      period_start = CASE
        WHEN reset_mode = 'rolling'
          AND now() >= period_start + (period_hours || ' hours')::interval
        THEN now()
        WHEN reset_mode = 'calendar'
          AND period_start < (
            date_trunc('day', now() AT TIME ZONE reset_tz)
            + (reset_hour || ' hours')::interval
          ) AT TIME ZONE reset_tz
          AND now() >= (
            date_trunc('day', now() AT TIME ZONE reset_tz)
            + (reset_hour || ' hours')::interval
          ) AT TIME ZONE reset_tz
        THEN (
          date_trunc('day', now() AT TIME ZONE reset_tz)
          + (reset_hour || ' hours')::interval
        ) AT TIME ZONE reset_tz
        ELSE period_start
      END,
      consumed = CASE
        WHEN reset_mode = 'rolling'
          AND now() >= period_start + (period_hours || ' hours')::interval
        THEN 1
        WHEN reset_mode = 'calendar'
          AND period_start < (
            date_trunc('day', now() AT TIME ZONE reset_tz)
            + (reset_hour || ' hours')::interval
          ) AT TIME ZONE reset_tz
          AND now() >= (
            date_trunc('day', now() AT TIME ZONE reset_tz)
            + (reset_hour || ' hours')::interval
          ) AT TIME ZONE reset_tz
        THEN 1
        ELSE consumed + 1
      END,
      last_call_at = now()
    WHERE resource_type = :rt
""")

_THROTTLE_SQL = text("""
    UPDATE resource_budgets
    SET backoff_count = backoff_count + 1,
        backoff_until = now() + LEAST(
          CASE backoff_count
            WHEN 0 THEN interval '1 minute'
            WHEN 1 THEN interval '5 minutes'
            WHEN 2 THEN interval '30 minutes'
            WHEN 3 THEN interval '2 hours'
            ELSE interval '8 hours'
          END,
          (period_hours || ' hours')::interval
        )
    WHERE resource_type = :rt
""")

_SUCCESS_SQL = text("""
    UPDATE resource_budgets
    SET backoff_count = 0, backoff_until = NULL
    WHERE resource_type = :rt AND backoff_count > 0
""")


async def acquire_budget(resource_type: str) -> bool:
    """Check budget and enforce RPM spacing. Does NOT decrement consumed.

    Returns True if the call is allowed. Returns False if budget is
    exhausted or the resource is backed off. Callers should raise
    ResourceExhaustedError when this returns False.

    After the API call fires, call record_call() to decrement the budget.
    """
    with engine.connect() as conn:
        row = conn.execute(_CHECK_SQL, {"rt": resource_type}).fetchone()

    if row is None:
        return False

    rpm, seconds_since_last, remaining = row
    if remaining <= 0:
        return False

    if rpm and seconds_since_last is not None:
        interval = 60.0 / float(rpm)
        gap = float(seconds_since_last)
        if gap < interval:
            await asyncio.sleep(interval - gap)

    return True


async def record_call(resource_type: str) -> None:
    """Record that an API call was made. Decrements consumed.

    Call this AFTER the HTTP request fires, regardless of the response
    status. This ensures we only count calls that actually happened.
    """
    with engine.connect() as conn:
        conn.execute(_RECORD_CALL_SQL, {"rt": resource_type})
        conn.commit()


async def record_throttle(resource_type: str) -> None:
    """Record a 429/rate-limit response. Sets exponential backoff.

    Backoff schedule: 1 min, 5 min, 30 min, 2 hours, 8 hours (cap).
    The worker will stop claiming tasks for this resource until
    backoff_until expires, then probe with one task.
    """
    with engine.connect() as conn:
        conn.execute(_THROTTLE_SQL, {"rt": resource_type})
        conn.commit()
    logger.warning(f"Recorded throttle for {resource_type}, backoff extended")


async def record_success(resource_type: str) -> None:
    """Clear backoff state after a successful API call.

    No-op when the resource is healthy (backoff_count = 0).
    """
    with engine.connect() as conn:
        result = conn.execute(_SUCCESS_SQL, {"rt": resource_type})
        conn.commit()
    if result.rowcount > 0:
        logger.info(f"Cleared backoff for {resource_type}")
