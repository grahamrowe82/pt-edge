# Worker Fix Plan — Implementation PRs

**Date:** 2026-04-07
**Companion doc:** [worker-incident-analysis.md](worker-incident-analysis.md)
**Principle:** Fix from the bottom up — deeper structural fixes prevent entire classes of future problems, not just today's bugs.

---

## PR 1: Worker observability — post-run error summary

**Why first:** Every other incident was invisible. No fix matters if the next novel failure class also goes unnoticed for weeks.

**Scope:**
- At the end of each `schedule_all()` cycle in `scheduler.py`, run a summary query against the `tasks` table:
  ```sql
  SELECT task_type,
         substring(error_message from 1 for 80) AS error_class,
         count(*) AS n,
         count(DISTINCT subject_id) AS unique_subjects
  FROM tasks
  WHERE state = 'failed'
    AND completed_at > now() - interval '24 hours'
  GROUP BY 1, 2
  ORDER BY n DESC
  LIMIT 20
  ```
- Log the result as a single structured block at WARNING level (so it's visible even in normal log filtering)
- If zero failures in the window, log a single INFO line: "No task failures in the last 24h"
- No new tables, no new dependencies, no dashboards — just a query the scheduler already has the connection to run

**Files:**
- `app/queue/scheduler.py` — add `report_failure_summary()`, call it from `schedule_all()`

**Verification:**
- Run the query manually via psql to confirm it returns the expected output
- Deploy, wait one scheduler cycle (15min), check logs for the summary block

---

## PR 2: Break the re-enqueue death spiral

**Why second:** The death spiral is the amplifier — it turns every bug into an infinite loop. 9,240 rate-limit rows + 7,524 redirect rows + 53 DMCA rows are all the same structural failure: the scheduler re-enqueues work that has repeatedly failed, with no memory.

**Scope:**
- Change the `schedule_backfill_created_at()` query to exclude repos that have recently failed:
  ```sql
  AND NOT EXISTS (
      SELECT 1 FROM tasks t
      WHERE t.task_type = 'backfill_created_at'
        AND t.subject_id = ar.id::text
        AND t.state = 'failed'
        AND t.completed_at > now() - interval '7 days'
  )
  ```
- Apply the same pattern to `schedule_fetch_readmes()` and `schedule_enrich_summaries()` — all fine-grained schedulers that select from `ai_repos` and use ON CONFLICT with the partial unique index
- The 7-day window means: after a code fix is deployed, failed tasks age out within a week and the scheduler naturally retries them. No manual recovery needed.
- This aligns with the existing `cleanup_old_tasks()` which deletes failed tasks after 30 days — the 7-day cooldown is well within the retention window

**Files:**
- `app/queue/scheduler.py` — modify `schedule_backfill_created_at()`, `schedule_fetch_readmes()`, `schedule_enrich_summaries()`, `schedule_enrich_repo_briefs()`, `schedule_enrich_comparisons()`

**Verification:**
- Count current failed rows per task_type before deploy
- After one scheduler cycle, confirm the scheduler logged 0 new tasks for types with all-failed subjects
- Manually delete a few failed rows and confirm the scheduler picks them up on the next cycle

---

## PR 3: Error classification — raise the right exceptions

**Why third:** With observability (PR 1) and the death spiral broken (PR 2), the remaining waste is retrying deterministic failures. This PR makes the worker's existing `ResourceThrottledError` machinery actually get used, and adds immediate failure for permanent errors.

**Scope:**

### 3a: Rate limits → ResourceThrottledError

In `fetch_readme.py` and `backfill_created_at.py`, change:
```python
# Before
raise RuntimeError(f"GitHub rate limited (403) for {full_name}")

# After
from app.ingest.budget import ResourceThrottledError
raise ResourceThrottledError(f"GitHub rate limited (403) for {full_name}")
```

The worker already handles this (line 221-226 of `worker.py`): requeues without incrementing `retry_count` and backs off the resource type. This is exactly what rate limits need — the infrastructure exists, the handlers just aren't using it.

### 3b: Permanent HTTP errors → immediate failure, no retry

Add a custom exception class in `app/queue/errors.py`:
```python
class PermanentTaskError(Exception):
    """Error that will never resolve on retry. Fails immediately, no retries."""
    pass
```

In `worker.py` `_execute_task()`, add a handler before the generic `Exception` catch:
```python
except PermanentTaskError as e:
    mark_failed(task_id, str(e))
    logger.warning(f"Task {task_id} permanently failed (non-retryable): {e}")
```

In handlers, use it for known-permanent HTTP status codes:
```python
if resp.status_code in (301, 451):
    raise PermanentTaskError(f"GitHub {resp.status_code} for {full_name}")
```

This means: 301 and 451 fail immediately on first attempt, burn 0 retries, and the death-spiral protection from PR 2 prevents re-enqueue for 7 days.

**Files:**
- `app/queue/errors.py` (new — single class, 4 lines)
- `app/queue/worker.py` — add `PermanentTaskError` handler
- `app/queue/handlers/fetch_readme.py` — use `ResourceThrottledError` for 403, `PermanentTaskError` for 301/451
- `app/queue/handlers/backfill_created_at.py` — same

**Verification:**
- Manually insert a test task pointing at a known-renamed repo
- Confirm it fails immediately (1 attempt, not 3) with `PermanentTaskError` in the error message
- Confirm rate-limited tasks requeue without incrementing `retry_count`

---

## PR 4: Add `follow_redirects=True` and rename detection

**Why fourth:** With error classification in place, 301s now fail fast instead of looping. But the real fix is to stop producing stale names. This PR does both: defence-in-depth redirect following, and proactive rename detection at the source.

**Scope:**

### 4a: follow_redirects=True everywhere

Add `follow_redirects=True` to the two missing httpx clients:
- `app/queue/handlers/fetch_readme.py` line 57
- `app/queue/handlers/backfill_created_at.py` line 52

### 4b: Rename detection in main ingest

In `app/ingest/github.py` `fetch_repo()`, after getting a 200 response, compare the API response's `full_name` with the requested `owner/repo`. If they differ, log a warning and return a signal to the caller:
```python
data = resp.json()
api_name = data.get("full_name", "")
requested = f"{owner}/{repo}"
if api_name.lower() != requested.lower():
    logger.info(f"Repo renamed: {requested} → {api_name}")
    data["_renamed_from"] = requested
return data
```

In the caller that writes to the DB (the sync loop), when `_renamed_from` is present, update `ai_repos`:
```sql
UPDATE ai_repos
SET full_name = :new_name,
    github_owner = :new_owner,
    github_repo = :new_repo
WHERE full_name = :old_name
```

This also needs to update `raw_cache.subject_id` and any other tables that reference `full_name` as a foreign key. Audit all tables with a `full_name` or `subject_id` column that joins to `ai_repos`.

### 4c: Rename detection in fine-grained handlers

In `backfill_created_at.py`, after following the redirect and getting a 200, check if the response `full_name` differs from the DB. If so, update `ai_repos.full_name` inline. This catches renames that the main ingest hasn't seen yet.

**Files:**
- `app/queue/handlers/fetch_readme.py`
- `app/queue/handlers/backfill_created_at.py`
- `app/ingest/github.py`

**Verification:**
- Query `ai_repos` for the 298 known-stale repos (from the incident analysis, they have failed tasks with 301 errors). After deploy, the next ingest cycle should detect and fix their names.
- Confirm `fetch_readme` and `backfill_created_at` succeed for previously-301'd repos

---

## PR 5: Clean up residual failed tasks

**Why last:** With all structural fixes deployed, clean up the historical damage so the scheduler can re-process affected repos.

**Scope:**
- One-time SQL migration or script to delete failed tasks that are now fixable:
  ```sql
  -- Tasks fixed by code changes (will succeed on re-enqueue)
  DELETE FROM tasks WHERE state = 'failed'
    AND error_message LIKE 'RuntimeError: GitHub 301%';
  DELETE FROM tasks WHERE state = 'failed'
    AND error_message LIKE 'RuntimeError: GitHub rate limited%';
  DELETE FROM tasks WHERE state = 'failed'
    AND error_message LIKE 'TypeError:%float%decimal%';
  DELETE FROM tasks WHERE state = 'failed'
    AND error_message LIKE 'ProgrammingError%syntax error%';
  DELETE FROM tasks WHERE state = 'failed'
    AND error_message LIKE 'ProgrammingError%can''t adapt%';

  -- Tasks that will never succeed (permanent)
  DELETE FROM tasks WHERE state = 'failed'
    AND error_message LIKE 'RuntimeError: GitHub 451%';
  DELETE FROM tasks WHERE state = 'failed'
    AND error_message LIKE 'Unknown task type%';
  ```
- The 451 repo (`IshaanLabs/Harry-Potter-Dataset`) should also be marked in `ai_repos` so it's excluded from future scheduling. Options: set `archived = true`, or add an `exclude_reason` column. Setting `archived = true` is simpler and already has downstream effects (schedulers check `ar.archived = false`).

**Files:**
- `app/migrations/versions/XXX_cleanup_failed_tasks.py` (Alembic migration)
- OR a one-time script in `scripts/cleanup_failed_tasks.py` (run manually via psql)

**Verification:**
- Before: `SELECT state, count(*) FROM tasks GROUP BY state` — expect ~19K failed
- Run cleanup
- After: failed count should drop to ~15 (the LLM/SSL/killed stragglers)
- Next scheduler cycle: confirm repos are being re-enqueued and succeeding

---

## PR Dependency Graph

```
PR 1 (observability)
  ↓
PR 2 (death spiral)     ← can merge independently of PR 1, but PR 1 lets you verify it's working
  ↓
PR 3 (error classification)  ← depends on PR 2 being in place, otherwise PermanentTaskError just shifts waste to re-enqueue
  ↓
PR 4 (redirects + renames)   ← depends on PR 3 for 301 handling; rename detection is independent
  ↓
PR 5 (cleanup)               ← must be last; runs after all fixes are deployed
```

PRs 1 and 2 can be developed in parallel. PR 3 should land after PR 2. PR 4 after PR 3. PR 5 is always last.

---

## What this does NOT cover (intentionally)

- **Circuit breaker / auto-pause:** Useful but not needed yet. With PR 1 (observability) and PR 2 (death spiral), you'll see novel failure patterns in logs and they won't amplify. A circuit breaker is a future optimisation once the baseline is healthy.
- **Shared GitHub client factory:** Would prevent future inconsistency in httpx config, but is a refactor with no immediate incident to justify. Defer until the next time a handler is added.
- **Dashboard / alerting:** The post-run summary (PR 1) is sufficient for a single-operator system. If the team grows or the worker runs unattended for longer, revisit.
- **Metrics / Prometheus / Grafana:** Overkill for current scale. The data lives in the DB and is queryable with psql.
