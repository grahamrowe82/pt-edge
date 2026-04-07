# Worker Fix Plan — Implementation PRs

**Date:** 2026-04-07 (revised after code audit)
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

Add a NOT EXISTS clause to each fine-grained scheduler that checks for recent failures of the same subject. The `subject_id` format differs per scheduler, so each must use the correct join:

**`schedule_backfill_created_at()`** — subject_id is `ar.id::text`:
```sql
AND NOT EXISTS (
    SELECT 1 FROM tasks t
    WHERE t.task_type = 'backfill_created_at'
      AND t.subject_id = ar.id::text
      AND t.state = 'failed'
      AND t.completed_at > now() - interval '7 days'
)
```

Also add `AND ar.archived = false` — this scheduler currently lacks it, unlike the other fine-grained schedulers. Without it, archived/DMCA'd repos are re-enqueued forever.

**`schedule_fetch_readmes()`** — subject_id is `ar.full_name`:
```sql
AND NOT EXISTS (
    SELECT 1 FROM tasks t
    WHERE t.task_type = 'fetch_readme'
      AND t.subject_id = ar.full_name
      AND t.state = 'failed'
      AND t.completed_at > now() - interval '7 days'
)
```

**`schedule_enrich_summaries()`** — subject_id is `ar.full_name`:
```sql
AND NOT EXISTS (
    SELECT 1 FROM tasks t
    WHERE t.task_type = 'enrich_summary'
      AND t.subject_id = ar.full_name
      AND t.state = 'failed'
      AND t.completed_at > now() - interval '7 days'
)
```

**`schedule_enrich_repo_briefs()`** — subject_id is `ar.id::text`:
```sql
AND NOT EXISTS (
    SELECT 1 FROM tasks t
    WHERE t.task_type = 'enrich_repo_brief'
      AND t.subject_id = ar.id::text
      AND t.state = 'failed'
      AND t.completed_at > now() - interval '7 days'
)
```

The 7-day window means: after a code fix is deployed, failed tasks age out within a week and the scheduler naturally retries them. No manual recovery needed. This aligns with the existing `cleanup_old_tasks()` which deletes failed tasks after 30 days.

**Not included:** `schedule_enrich_comparisons()` — it selects from `comparison_sentences` (not `ai_repos`), has a different failure profile, and zero current re-enqueue problems.

**Files:**
- `app/queue/scheduler.py` — modify `schedule_backfill_created_at()`, `schedule_fetch_readmes()`, `schedule_enrich_summaries()`, `schedule_enrich_repo_briefs()`

**Verification:**
- Count current failed rows per task_type before deploy
- After one scheduler cycle, confirm the scheduler logged 0 new tasks for types with all-failed subjects
- Manually delete a few failed rows and confirm the scheduler picks them up on the next cycle

---

## PR 3: Error classification — fix requeue and raise the right exceptions

**Why third:** With observability (PR 1) and the death spiral broken (PR 2), the remaining waste is retrying deterministic failures. This PR fixes two things: the broken requeue path for infrastructure errors, and the lack of immediate failure for permanent errors.

**Scope:**

### 3a: Fix `requeue()` so infrastructure errors don't burn retries

`requeue()` in `worker.py` (line 175) unconditionally does `retry_count = retry_count + 1`. This means `ResourceThrottledError` — which the worker catches separately and is *documented* as "requeue without counting as a retry" — actually does count. The comment is a lie. Rate-limited tasks still exhaust `max_retries` and fail permanently.

Add an `increment_retry` parameter to `requeue()`:

```python
def requeue(task_id: int, error: str, increment_retry: bool = True) -> None:
    """Return a task to pending state for retry."""
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE tasks
            SET state = 'pending',
                retry_count = retry_count + :inc,
                error_message = :error,
                claimed_by = NULL,
                claimed_at = NULL,
                heartbeat_at = NULL
            WHERE id = :id
        """), {"id": task_id, "error": error[:2000], "inc": 1 if increment_retry else 0})
        conn.commit()
```

Then update the `ResourceThrottledError`/`ResourceExhaustedError` handler in `_execute_task()`:
```python
except (ResourceExhaustedError, ResourceThrottledError) as e:
    requeue(task_id, str(e), increment_retry=False)
```

All other callers of `requeue()` (the generic `Exception` handler, `reap_stale_tasks()`) keep the default `increment_retry=True`.

### 3b: Rate limits → ResourceThrottledError in handlers

In `fetch_readme.py` and `backfill_created_at.py`, change the 403 handler:
```python
# Before
raise RuntimeError(f"GitHub rate limited (403) for {full_name}")

# After
from app.ingest.budget import ResourceThrottledError
raise ResourceThrottledError(f"GitHub rate limited (403) for {full_name}")
```

With 3a in place, this means rate-limited tasks requeue indefinitely without burning retries, and the worker backs off the `github_api` resource until the budget resets.

### 3c: Permanent HTTP errors → immediate failure, no retry

Add a custom exception class in `app/queue/errors.py`:
```python
class PermanentTaskError(Exception):
    """Error that will never resolve on retry. Fails immediately, no retries."""
    pass
```

In `worker.py` `_execute_task()`, add a handler between `ResourceThrottledError` and generic `Exception`:
```python
except PermanentTaskError as e:
    mark_failed(task_id, str(e))
    logger.warning(f"Task {task_id} permanently failed (non-retryable): {e}")
```

In handlers, use it for 451 (DMCA takedown) and 410 (Gone):
```python
if resp.status_code in (451, 410):
    raise PermanentTaskError(f"GitHub {resp.status_code} for {full_name}")
```

**Note:** 301 is NOT included. PR 4 adds `follow_redirects=True`, which resolves 301s automatically — the handler never sees a 301 status code. The 301 problem is solved by redirect following + rename detection, not error classification.

**Files:**
- `app/queue/errors.py` (new — single class, 4 lines)
- `app/queue/worker.py` — fix `requeue()` signature, add `PermanentTaskError` handler, pass `increment_retry=False` for infrastructure errors
- `app/queue/handlers/fetch_readme.py` — use `ResourceThrottledError` for 403, `PermanentTaskError` for 451/410
- `app/queue/handlers/backfill_created_at.py` — same

**Verification:**
- Manually insert a test task pointing at the DMCA'd repo (subject_id for `IshaanLabs/Harry-Potter-Dataset`)
- Confirm it fails immediately (1 attempt, not 3) with `PermanentTaskError` in the error message
- Simulate a rate limit: confirm the task requeues with `retry_count` unchanged (check DB before and after)

---

## PR 4: Add `follow_redirects=True` and rename detection

**Why fourth:** With the death spiral broken (PR 2) and error classification in place (PR 3), 301s are no longer amplified. This PR eliminates them at the source: follow redirects so handlers get the right data, and update stale names when a rename is detected.

**Scope:**

### 4a: follow_redirects=True in handlers

Add `follow_redirects=True` to the two httpx clients that are missing it:
- `app/queue/handlers/fetch_readme.py` line 57: `httpx.AsyncClient(timeout=30)` → `httpx.AsyncClient(timeout=30, follow_redirects=True)`
- `app/queue/handlers/backfill_created_at.py` line 52: `httpx.AsyncClient(headers=headers, timeout=10)` → `httpx.AsyncClient(headers=headers, timeout=10, follow_redirects=True)`

After this change, 301 redirects are followed automatically and handlers see the final 200/404 response. No handler code ever sees a 301 status.

### 4b: Rename detection in fine-grained handlers

The stale `full_name` values live in `ai_repos`. The `projects` table (used by `app/ingest/github.py` main ingest) is a completely separate system and does NOT touch `ai_repos`. Rename detection belongs in the handlers that look up `full_name` from `ai_repos` and hit GitHub with it.

**In `backfill_created_at.py`**, after following the redirect and getting a 200:
```python
data = resp.json()
api_full_name = data.get("full_name", "")
if api_full_name and api_full_name.lower() != full_name.lower():
    logger.info(f"Repo renamed: {full_name} → {api_full_name}")
    new_owner, new_repo = api_full_name.split("/", 1)
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE ai_repos
            SET full_name = :new_name,
                github_owner = :new_owner,
                github_repo = :new_repo
            WHERE id = :id
        """), {
            "new_name": api_full_name,
            "new_owner": new_owner,
            "new_repo": new_repo,
            "id": repo_id,
        })
        conn.commit()
```

The handler already has `repo_id` (from the task's `subject_id`) and `full_name` (looked up from `ai_repos`), so the comparison and update are straightforward.

**In `fetch_readme.py`**, rename detection is harder because the README endpoint doesn't return `full_name` in its response body. Two options:
1. Check `resp.url` after redirect — if it contains a different owner/repo, that signals a rename. httpx exposes `resp.url` as the final URL after redirects.
2. Skip rename detection here and let `backfill_created_at` handle it — the README handler's job is to fetch content, not maintain metadata.

**Option 2 is simpler.** `backfill_created_at` already hits `/repos/{full_name}` which returns the full repo object including `full_name`. Let it be the single rename detector.

### 4c: Update orphaned `raw_cache` rows

There are no foreign key constraints on `full_name` anywhere — `raw_cache.subject_id` is plain TEXT with string-match joins. When a rename is detected in `backfill_created_at`, also update `raw_cache`:
```sql
UPDATE raw_cache
SET subject_id = :new_name
WHERE source = 'github_readme'
  AND subject_id = :old_name
```

This prevents orphaned README cache entries that would never match the new `full_name`.

**Files:**
- `app/queue/handlers/fetch_readme.py` — add `follow_redirects=True`
- `app/queue/handlers/backfill_created_at.py` — add `follow_redirects=True`, add rename detection + `raw_cache` update

**Verification:**
- Query for the 298 known-stale repos (from failed tasks with 301 errors): join `tasks` to `ai_repos` to get their IDs
- After deploy, these repos will be re-enqueued (failed tasks age out via PR 2's 7-day window, or clean up via PR 5)
- Confirm `backfill_created_at` succeeds and updates `ai_repos.full_name` for a previously-301'd repo
- Confirm `raw_cache.subject_id` is updated to the new name

---

## PR 5: Clean up residual failed tasks and mark unfetchable repos

**Why last:** With all structural fixes deployed, clean up the historical damage so the scheduler can re-process affected repos.

**Scope:**

### 5a: Delete failed tasks that will now succeed

One-time cleanup (script or migration):
```sql
-- Tasks fixed by follow_redirects (PR 4)
DELETE FROM tasks WHERE state = 'failed'
  AND error_message LIKE 'RuntimeError: GitHub 301%';

-- Tasks fixed by ResourceThrottledError (PR 3) + death spiral (PR 2)
DELETE FROM tasks WHERE state = 'failed'
  AND error_message LIKE 'RuntimeError: GitHub rate limited%';

-- Tasks fixed by earlier code changes (already deployed)
DELETE FROM tasks WHERE state = 'failed'
  AND error_message LIKE 'TypeError:%float%decimal%';
DELETE FROM tasks WHERE state = 'failed'
  AND error_message LIKE 'ProgrammingError%syntax error%';
DELETE FROM tasks WHERE state = 'failed'
  AND error_message LIKE 'ProgrammingError%can''t adapt%';

-- Permanent failures that will never succeed
DELETE FROM tasks WHERE state = 'failed'
  AND error_message LIKE 'RuntimeError: GitHub 451%';
DELETE FROM tasks WHERE state = 'failed'
  AND error_message LIKE 'Unknown task type%';
```

### 5b: Mark unfetchable repos as archived

The DMCA'd repo (`IshaanLabs/Harry-Potter-Dataset`, ai_repos id `101335`) will loop forever unless excluded. `schedule_backfill_created_at()` doesn't check `archived` today, but PR 2 adds that guard. Mark it:

```sql
UPDATE ai_repos SET archived = true WHERE id = 101335;
```

This works because PR 2 adds `AND ar.archived = false` to `schedule_backfill_created_at()`. For the other schedulers (`fetch_readmes`, `enrich_summaries`, `enrich_repo_briefs`), the `archived = false` guard already exists.

### 5c: Verify the schedulers re-enqueue

After deleting the failed rows, the NOT EXISTS clauses from PR 2 will no longer block re-enqueueing (there are no recent failed tasks to match). The schedulers will naturally create fresh tasks for the affected repos on their next cycle.

**Files:**
- `scripts/cleanup_failed_tasks.sql` (run manually via psql — not an Alembic migration, since this is a one-time data fix, not a schema change)

**Verification:**
- Before: `SELECT state, count(*) FROM tasks GROUP BY state` — expect ~19K failed
- Run cleanup
- After: failed count should drop to ~15 (the LLM/SSL/killed stragglers)
- Next scheduler cycle: confirm repos are being re-enqueued and succeeding

---

## PR Dependency Graph

```
PR 1 (observability)     PR 2 (death spiral)
         \                    /
          \                  /
    can develop in parallel; PR 1 lets you verify PR 2
                  |
             PR 3 (error classification)
                  |
                  |  ← depends on PR 2; otherwise PermanentTaskError
                  |    just shifts waste to re-enqueue
                  |
             PR 4 (redirects + renames)
                  |
                  |  ← independent of PR 3 (no 301 in error classification)
                  |    but logically follows it
                  |
             PR 5 (cleanup)
                  |
                  ← must be last; runs after all fixes are deployed
```

PRs 1 and 2 can be developed and merged in parallel. PR 3 depends on PR 2. PR 4 is independent of PR 3 but logically follows it. PR 5 is always last.

---

## What this does NOT cover (intentionally)

- **Circuit breaker / auto-pause:** Useful but not needed yet. With PR 1 (observability) and PR 2 (death spiral), you'll see novel failure patterns in logs and they won't amplify. A circuit breaker is a future optimisation once the baseline is healthy.
- **Shared GitHub client factory:** Would prevent future inconsistency in httpx config, but is a refactor with no immediate incident to justify. Defer until the next time a handler is added.
- **Rename detection in `github.py` main ingest:** The main ingest writes to `projects`/`github_snapshots`, not `ai_repos`. Renames detected there wouldn't fix the stale `ai_repos.full_name` values causing 301s. The fine-grained handler approach (PR 4b) targets the correct table.
- **Dashboard / alerting:** The post-run summary (PR 1) is sufficient for a single-operator system. If the team grows or the worker runs unattended for longer, revisit.
- **Metrics / Prometheus / Grafana:** Overkill for current scale. The data lives in the DB and is queryable with psql.
