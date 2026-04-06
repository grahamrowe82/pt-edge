# Resource Budget Infrastructure

*6 April 2026*

## The Problem

PT-Edge makes thousands of external API calls per day across 11 providers (GitHub, Gemini, OpenAI, PyPI, npm, HuggingFace, Docker Hub, HN Algolia, V2EX, crates.io, VS Code Marketplace). Rate limiting is scattered across the codebase:

- **Budget tracking is inaccurate.** The worker decrements the budget by 1 per task claim, but coarse-grained tasks make many actual API calls. `enrich_hn_match` makes ~250 Gemini calls per task. `enrich_project_brief` makes ~10. The budget says we used 9,600 calls but the real number is 10,000+.

- **Budget windows don't align with provider windows.** Google Gemini resets at midnight Pacific Time. Our budget uses a rolling 24-hour window from `period_start`. If our window straddles two Google days unevenly, we exceed their limit while staying within ours.

- **No adaptive backoff.** When 429s occur, the in-process retry loop burns 3 retries on a problem that won't resolve for hours (daily budget) or minutes (RPM burst). The task fails permanently. The worker immediately claims the next task, which also 429s. No system-level learning.

- **Rate limits are scattered.** `GEMINI_RPM` and `OPENAI_RPM` are in `settings.py`. Semaphore sizes are hardcoded per file. `sleep(0.6)` is in `hf_common.py`. `sleep(6.0)` is in `v2ex.py`. No central place to see or tune all limits.

- **In-memory state doesn't survive restarts.** The `RateLimiter` class tracks `_last_call` in memory. Worker restart = rate limiter resets = potential burst.

## The Principle

**The database is the source of truth.** Workers and API call sites are stateless. If a task needs to know a fact — budget remaining, whether a provider is backed off, how fast to call — it reads it from the database. Intelligence and memory live in the database, not in ephemeral processes.

This means:
- Provider configuration (reset windows, RPM limits, daily budgets) lives in `resource_budgets`, not in `settings.py` or hardcoded constants
- Budget consumption is tracked per actual API call, not per task claim
- Backoff state is written to the database so all workers see it immediately
- Tuning happens via `psql UPDATE`, not code deploys

## Current State

### `resource_budgets` table

```
resource_type | period_hours | budget | consumed | period_start
--------------+--------------+--------+----------+--------------
github_api    |            1 |   4500 |      ... | ...
gemini        |           24 |   9600 |      ... | ...
openai        |            1 |  24000 |      ... | ...
pypi          |            1 |   5000 |      ... | ...
npm           |            1 |   5000 |      ... | ...
huggingface   |            1 |   1000 |      ... | ...
dockerhub     |            1 |   1000 |      ... | ...
hn_algolia    |            1 |  10000 |      ... | ...
v2ex          |            1 |    120 |      ... | ...
crates        |            1 |   3600 |      ... | ...
db_only       |           24 | 999999 |      ... | ...
```

### Rate limiting per provider

| Provider | Budget | RPM enforcement | 429 handling | Notes |
|----------|--------|----------------|-------------|-------|
| GitHub | 4500/hr (DB) | Semaphore(5) | Global `_github_available` flag | Pre-flight `/rate_limit` check |
| Gemini | 9600/24h (DB) | 800 RPM in-memory (`settings.py`) | 3 retries, exponential backoff | Window misaligned with Google |
| OpenAI | 24000/hr (DB) | 400 RPM in-memory (`settings.py`) | None visible | Embeddings only |
| PyPI | 5000/hr (DB) | Semaphore(3) | `sleep(30)` on 429 | |
| npm | 5000/hr (DB) | Semaphore(3) | `sleep(30)` on 429 | |
| HuggingFace | 1000/hr (DB) | `sleep(0.6)` hardcoded | None | Documented 1.67 req/s |
| Docker Hub | 1000/hr (DB) | `sleep(0.5)` + Semaphore(3) | None | |
| HN Algolia | 10000/hr (DB) | `sleep(1.0)` + Semaphore(2) | None | |
| V2EX | 120/hr (DB) | `sleep(6.0)` hardcoded | None | Matches API hard limit |
| crates.io | 3600/hr (DB) | `sleep(1.0)` hardcoded | `sleep(60)` on 429 | 1 req/s |

---

## Design

### Schema extension

Add columns to `resource_budgets` for provider-aware resets, RPM limits, and backoff state:

```sql
ALTER TABLE resource_budgets
  ADD COLUMN reset_mode    text NOT NULL DEFAULT 'rolling',
  ADD COLUMN reset_tz      text NOT NULL DEFAULT 'UTC',
  ADD COLUMN reset_hour    smallint NOT NULL DEFAULT 0,
  ADD COLUMN rpm           int,
  ADD COLUMN last_call_at  timestamptz,
  ADD COLUMN backoff_until timestamptz,
  ADD COLUMN backoff_count smallint NOT NULL DEFAULT 0;
```

| Column | Type | Purpose |
|--------|------|---------|
| `reset_mode` | `text` | `rolling` = existing behaviour (reset after `period_hours`). `calendar` = reset at a wall-clock time in a specific timezone. |
| `reset_tz` | `text` | IANA timezone for calendar resets. e.g. `America/Los_Angeles` for Google. Ignored for rolling mode. |
| `reset_hour` | `smallint` | Hour of day (0-23) when the calendar budget resets. e.g. `0` for midnight. |
| `rpm` | `int` | Requests per minute limit. NULL = no RPM enforcement. Replaces `GEMINI_RPM` and `OPENAI_RPM` from `settings.py`. |
| `last_call_at` | `timestamptz` | Timestamp of the last actual API call. Used for RPM spacing. Replaces the in-memory `_last_call` in `RateLimiter`. |
| `backoff_until` | `timestamptz` | NULL = healthy. Future timestamp = resource is backed off, stop claiming tasks until then. |
| `backoff_count` | `smallint` | Number of consecutive 429 events. Drives exponential backoff schedule. Resets to 0 on success. |

Provider-specific seed data:

```sql
-- Gemini: calendar reset at midnight Pacific, 800 RPM, 10K/day
UPDATE resource_budgets
SET reset_mode = 'calendar',
    reset_tz = 'America/Los_Angeles',
    reset_hour = 0,
    rpm = 800,
    budget = 10000
WHERE resource_type = 'gemini';

-- OpenAI: rolling reset, 400 RPM
UPDATE resource_budgets
SET rpm = 400
WHERE resource_type = 'openai';

-- All other providers: rolling reset (default), no RPM column needed
-- (their RPM is effectively enforced by budget / period_hours)
```

### Core API: `app/ingest/budget.py`

A new module with three functions and two exception classes. Every external API call goes through `acquire_budget` before making the HTTP request.

#### `acquire_budget(resource_type: str) -> bool`

Single DB round-trip. Returns `True` if the call is allowed, `False` if budget exhausted or backed off.

The implementation is a single atomic `UPDATE ... RETURNING` that does everything in one query:

1. **Check backoff.** If `backoff_until > now()`, the WHERE clause excludes the row. No update, returns `False`.

2. **Check and reset the budget window.** Two modes:
   - `rolling`: if `now() >= period_start + period_hours`, reset `consumed = 0` and `period_start = now()` inline via CASE.
   - `calendar`: compute the most recent reset boundary (`reset_hour` in `reset_tz`). If `period_start` is before that boundary and `now()` is after it, reset `consumed = 0` and set `period_start` to the boundary.

3. **Check remaining budget.** If `consumed >= budget` (after any reset), the WHERE clause excludes the row. Returns `False`.

4. **Decrement.** `consumed += 1`, `last_call_at = now()`.

5. **Enforce RPM.** The RETURNING clause includes `rpm` and the time since `last_call_at`. If `rpm` is set and the interval is too short, the Python wrapper `await asyncio.sleep(interval)` before returning `True`.

```sql
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
    WHEN <window-expired conditions from above>
    THEN 1
    WHEN consumed < budget
    THEN consumed + 1
    ELSE consumed  -- should not reach here due to WHERE clause
  END,
  last_call_at = now()
WHERE resource_type = :rt
  AND (backoff_until IS NULL OR now() >= backoff_until)
  AND (
    -- Budget has remaining capacity (accounting for possible reset)
    CASE
      WHEN <window-expired conditions> THEN true  -- will reset, always has capacity
      ELSE consumed < budget
    END
  )
RETURNING rpm,
  EXTRACT(EPOCH FROM (now() - COALESCE(last_call_at, '1970-01-01'::timestamptz)))
    AS seconds_since_last
```

The Python wrapper:

```python
async def acquire_budget(resource_type: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(ACQUIRE_SQL, {"rt": resource_type}).fetchone()
        conn.commit()
        if row is None:
            return False
        rpm, seconds_since_last = row
        if rpm and seconds_since_last < 60.0 / rpm:
            await asyncio.sleep(60.0 / rpm - seconds_since_last)
        return True
```

#### `record_throttle(resource_type: str) -> None`

Called when an API returns 429 (or equivalent rate-limit signal). Sets exponential backoff:

```sql
UPDATE resource_budgets
SET backoff_count = backoff_count + 1,
    backoff_until = now() + CASE backoff_count
      WHEN 0 THEN interval '1 minute'
      WHEN 1 THEN interval '5 minutes'
      WHEN 2 THEN interval '30 minutes'
      WHEN 3 THEN interval '2 hours'
      ELSE interval '8 hours'
    END
WHERE resource_type = :rt
```

Backoff schedule: **1 min, 5 min, 30 min, 2 hours, 8 hours** (capped). The 8-hour cap covers worst-case daily budget exhaustion — Google resets at midnight PT, so the longest wait is ~8 hours if we exhaust the budget at 4 PM PT.

Self-healing: when `backoff_until` expires, the worker's existing one-task-per-resource-slot design means exactly one task runs as a probe. If it succeeds, `record_success` clears the backoff. If it 429s again, `record_throttle` extends the backoff.

#### `record_success(resource_type: str) -> None`

Called after a successful API response. Clears backoff state if active:

```sql
UPDATE resource_budgets
SET backoff_count = 0, backoff_until = NULL
WHERE resource_type = :rt AND backoff_count > 0
```

No-op when the resource is healthy (the `AND backoff_count > 0` avoids unnecessary writes on every successful call).

#### Exception classes

```python
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
```

These are infrastructure signals, not task failures. The worker requeues the task without counting it as a retry.

### Worker changes (`app/queue/worker.py`)

#### Claim query

The `budget_check` CTE in `_CLAIM_FOR_RESOURCE_SQL` and `_CLAIM_ANY_SQL` gains:

1. **Backoff check.** If `backoff_until IS NOT NULL AND now() < backoff_until`, set `remaining = 0`.
2. **Calendar reset.** Alongside the existing rolling reset logic, add the calendar boundary check.

The claim query remains a read-only gate — it prevents claiming tasks for exhausted or backed-off resources, but no longer modifies `resource_budgets`.

#### Remove budget decrement

Delete `_DECREMENT_BUDGET_SQL` (lines 88-101) and the call at line 121 in `claim_next_task`. Budget is now decremented at the actual API call site via `acquire_budget`.

#### New exception handling in `_execute_task`

```python
except ResourceExhaustedError:
    requeue(task_id, "Budget exhausted")
    # Do NOT increment retry_count — this is not a task failure
except ResourceThrottledError:
    requeue(task_id, "Provider throttled")
    # Do NOT increment retry_count
except Exception as e:
    # existing retry logic unchanged
```

### Scheduler changes (`app/queue/scheduler.py`)

Update `reset_expired_budgets()` to handle both modes:

```python
def reset_expired_budgets() -> int:
    with engine.connect() as conn:
        # Rolling resets (existing logic)
        r1 = conn.execute(text("""
            UPDATE resource_budgets
            SET consumed = 0, period_start = now()
            WHERE reset_mode = 'rolling'
              AND now() >= period_start + (period_hours || ' hours')::interval
        """))

        # Calendar resets
        r2 = conn.execute(text("""
            UPDATE resource_budgets
            SET consumed = 0,
                period_start = (
                    date_trunc('day', now() AT TIME ZONE reset_tz)
                    + (reset_hour || ' hours')::interval
                ) AT TIME ZONE reset_tz
            WHERE reset_mode = 'calendar'
              AND period_start < (
                  date_trunc('day', now() AT TIME ZONE reset_tz)
                  + (reset_hour || ' hours')::interval
              ) AT TIME ZONE reset_tz
              AND now() >= (
                  date_trunc('day', now() AT TIME ZONE reset_tz)
                  + (reset_hour || ' hours')::interval
              ) AT TIME ZONE reset_tz
        """))

        conn.commit()
        return r1.rowcount + r2.rowcount
```

This is a safety net — `acquire_budget` also handles resets inline. The scheduler reset catches any edge cases where no calls are being made but the period should still reset.

### Call site changes (`app/ingest/llm.py`)

The Gemini call site is the first and most important migration.

**Before:**
```python
for attempt in range(retries):
    await GEMINI_LIMITER.acquire()        # in-memory rate limiter
    resp = await client.post(url, ...)
    if resp.status_code == 429:
        await asyncio.sleep(2**attempt * 15)  # in-process retry
        continue
```

**After:**
```python
if not await acquire_budget("gemini"):
    raise ResourceExhaustedError("gemini")

for attempt in range(retries):
    resp = await client.post(url, ...)
    if resp.status_code == 429:
        await record_throttle("gemini")
        raise ResourceThrottledError("gemini")
    # ... handle other errors with existing retry logic ...

await record_success("gemini")
```

Key changes:
- `acquire_budget` replaces `GEMINI_LIMITER.acquire()` — handles both RPM spacing and daily budget in one call
- 429s trigger `record_throttle` and raise immediately instead of retrying in-process — the system-level backoff handles recovery
- Success triggers `record_success` to clear any active backoff
- Non-429 errors (network timeouts, 500s) still retry in-process — those are transient

### Rate limiter changes (`app/ingest/rate_limit.py`)

The `RateLimiter` class stays for RPM spacing (a DB round-trip per 75ms interval is excessive), but is initialised from the DB value instead of `settings.py`:

```python
def get_rpm(resource_type: str) -> int | None:
    """Read RPM from resource_budgets."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT rpm FROM resource_budgets WHERE resource_type = :rt"
        ), {"rt": resource_type}).fetchone()
        return row[0] if row else None
```

The DB is the source of truth for what the RPM value *is*. The in-memory spacer enforces timing between consecutive calls within a single process.

### Settings changes (`app/settings.py`)

Remove `GEMINI_RPM` and `OPENAI_RPM`. These now live in `resource_budgets.rpm`.

---

## Implementation: PR Sequence

### PR A: Schema + Core Infrastructure

**No behaviour change.** Lays the foundation.

**Files:**

| File | Change |
|------|--------|
| `app/migrations/versions/081_resource_budget_provider_config.py` | New migration: add columns, seed Gemini/OpenAI values |
| `app/models/queue.py` | Add 7 columns to `ResourceBudget` model |
| `app/ingest/budget.py` | **New file:** `acquire_budget`, `record_throttle`, `record_success`, `ResourceExhaustedError`, `ResourceThrottledError` |

**What ships:** The new columns exist in the DB. The new module exists in code. Nothing calls it yet. The existing system continues to work unchanged.

**Verification:** Run migration, confirm columns exist, confirm `gemini` row has `reset_mode='calendar'` and `rpm=800`.

### PR B: Worker + Gemini Integration

**Fixes the Gemini 429 problem.** This is the critical PR.

**Files:**

| File | Change |
|------|--------|
| `app/queue/worker.py` | Update claim query (backoff + calendar check). Remove `_DECREMENT_BUDGET_SQL` and decrement call. Add `ResourceExhaustedError`/`ResourceThrottledError` handling in `_execute_task`. |
| `app/ingest/llm.py` | Replace `GEMINI_LIMITER.acquire()` with `acquire_budget("gemini")`. Replace in-process 429 retry with `record_throttle` + raise. Add `record_success` on success. |
| `app/queue/scheduler.py` | Update `reset_expired_budgets` to handle calendar mode. |
| `app/ingest/rate_limit.py` | Read Gemini RPM from DB instead of `settings.py`. |
| `app/settings.py` | Remove `GEMINI_RPM`. |

**What changes:**
- Gemini budget tracks actual API calls (not task claims) — coarse-grained tasks are correctly counted
- Budget resets at midnight Pacific (aligned with Google) — no more window overlap
- 429s trigger system-level backoff — worker stops claiming Gemini tasks until backoff expires, then probes with one task
- Tasks requeued on throttle/exhaustion without burning retries — they run when the resource recovers

**Verification:**
1. Deploy and monitor `resource_budgets`: `consumed` should increment per actual Gemini API call
2. Check `backoff_until` populates on 429 and clears after recovery
3. Verify no Gemini tasks are claimed while `backoff_until > now()`
4. Confirm budget resets at midnight PT by checking `period_start` after midnight
5. Tune budget from psql: `UPDATE resource_budgets SET budget = 10000 WHERE resource_type = 'gemini'` — takes effect immediately

### PR C: Other Call Sites (Incremental)

**Extends the infrastructure to all providers.** Can be split into sub-PRs per provider.

**Files:**

| File | Change |
|------|--------|
| `app/embeddings.py` | Replace `OPENAI_LIMITER.acquire()` with `acquire_budget("openai")` |
| `app/ingest/github.py` | Add `acquire_budget("github_api")` to HTTP calls. Replace `_github_available` flag with DB backoff. |
| `app/ingest/downloads.py` | Replace `sleep(0.3)` / `sleep(30)` with `acquire_budget` for PyPI, npm, crates.io |
| `app/ingest/hf_common.py` | Replace `sleep(0.6)` with `acquire_budget("huggingface")` |
| `app/ingest/dockerhub.py` | Replace `sleep(0.5)` with `acquire_budget("dockerhub")` |
| `app/ingest/hn.py` | Replace `sleep(1.0)` with `acquire_budget("hn_algolia")` |
| `app/ingest/v2ex.py` | Replace `sleep(6.0)` with `acquire_budget("v2ex")` |
| `app/settings.py` | Remove `OPENAI_RPM` |

**What changes:** All providers use the same `acquire_budget` / `record_throttle` / `record_success` pattern. Rate limits, budgets, and backoff state are visible and tunable from a single DB table. Hardcoded sleeps and scattered semaphores are replaced by centralised, DB-driven enforcement.

---

## After Implementation

### What the table looks like

```
resource_type | reset_mode | reset_tz            | reset_hour | rpm  | period_hours | budget  | consumed | backoff_until | backoff_count
--------------+------------+---------------------+------------+------+--------------+---------+----------+---------------+--------------
github_api    | rolling    | UTC                 |          0 | NULL |            1 |    4500 |     1200 | NULL          |             0
gemini        | calendar   | America/Los_Angeles |          0 |  800 |           24 |   10000 |     4500 | NULL          |             0
openai        | rolling    | UTC                 |          0 |  400 |            1 |   24000 |      300 | NULL          |             0
pypi          | rolling    | UTC                 |          0 | NULL |            1 |    5000 |      100 | NULL          |             0
...
```

### Operational benefits

- **Tune any limit without deploying:** `UPDATE resource_budgets SET budget = 15000 WHERE resource_type = 'gemini'`
- **See all provider state at a glance:** `SELECT resource_type, consumed, budget, backoff_until, backoff_count FROM resource_budgets`
- **Manual backoff clear:** `UPDATE resource_budgets SET backoff_until = NULL, backoff_count = 0 WHERE resource_type = 'gemini'`
- **Add a new provider:** `INSERT INTO resource_budgets (resource_type, period_hours, budget, rpm) VALUES ('new_api', 1, 1000, 60)`

### Self-healing behaviour

1. Worker calls Gemini. `acquire_budget` checks DB: budget remaining, not backed off. Decrements consumed, returns True.
2. Gemini returns 429. Handler calls `record_throttle("gemini")`. DB now has `backoff_until = now() + 1 minute`, `backoff_count = 1`. Handler raises `ResourceThrottledError`.
3. Worker catches the exception, requeues the task (no retry count increment).
4. Worker tries to claim next Gemini task. Claim query checks `backoff_until > now()` — returns no rows. Worker moves on to other resource slots.
5. One minute later, `backoff_until` has passed. Worker claims one Gemini task (one slot per resource type).
6. If the call succeeds: `record_success` clears `backoff_count = 0, backoff_until = NULL`. Normal operation resumes.
7. If the call 429s again: `record_throttle` sets `backoff_until = now() + 5 minutes`, `backoff_count = 2`. Backoff extends.
8. This continues up the schedule (1m, 5m, 30m, 2h, 8h cap) until the provider recovers.
9. No manual intervention needed. No deploys. The system adapts and heals on its own.
