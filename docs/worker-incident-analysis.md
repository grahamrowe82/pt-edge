# Worker Incident Analysis — 5 Whys for Every Failure Class

**Date:** 2026-04-07
**Scope:** All 19,588 failed tasks in the `tasks` table
**Success rate:** 92,086 done vs 19,588 failed (82.5% success, 17.5% failure)

## Failure Taxonomy

| Error Class | Failed Rows | Unique Subjects | Wasted Retries | Status |
|---|---|---|---|---|
| `github_rate_limited` | 9,240 | 6,028 | ~27,720 | Ongoing — re-enqueued every 15min |
| `github_301_redirect` | 7,524 | 298 | ~22,572 | Ongoing — re-enqueued every 15min |
| `float_vs_decimal` | 2,325 | 2,325 | ~6,975 | Fixed on Apr 5 |
| `sql_cast_syntax` | 425 | 350 | ~1,275 | Fixed on Apr 6 (PR #216) |
| `github_451_dmca` | 53 | 1 | ~159 | Ongoing — 1 DMCA'd repo in infinite loop |
| `llm_no_result` | 14 | 14 | — | Acceptable — LLM sometimes can't summarise |
| `sql_dict_adapt` | 3 | 1 | ~9 | Fixed on Apr 5 |
| `unknown_task_type` | 2 | 1 | — | Stale task types from removed handlers |
| `ssl_dropped` | 1 | 1 | — | Transient infra — Render DB dropped connection |
| `manually_killed` | 1 | 1 | — | Intentional manual intervention |

---

## Incident 1: Rate-Limited Repos (9,240 rows / 6,028 repos)

### What happened
`backfill_created_at` tasks hit GitHub 403 rate limits. Each failure counts against the retry budget (retry_count incremented). After 3 retries the task is marked `failed`. The scheduler sees `created_at IS NULL` and enqueues a fresh task. Repos that sit near the tail of the queue repeatedly hit rate limits and fail permanently, only to be re-enqueued and fail again.

### 5 Whys

1. **Why did requests get rate-limited?** Because `backfill_created_at` makes one GitHub API call per repo, and 225K repos with `created_at IS NULL` need backfilling. At 4,500/hr budget, this takes ~50 hours of continuous processing, frequently hitting the rate limit boundary.

2. **Why does a rate limit burn a retry?** Because the handler raises a generic `RuntimeError` on 403. The worker treats all `RuntimeError` as application errors and increments `retry_count`. It should raise `ResourceThrottledError` instead — the worker already has special handling for that: it requeues *without* incrementing `retry_count` and backs off the resource type.

3. **Why are the same repos failing 13-15 times?** Because the scheduler re-enqueues any repo where `created_at IS NULL`. The dedup index only covers `pending`/`claimed` states, so `failed` tasks don't block new inserts. The new task starts with `retry_count = 0` — a clean slate to burn 3 more retries.

4. **Why is there no feedback loop between failures and scheduling?** The scheduler doesn't check whether a repo has recently failed. It only checks the data condition (`created_at IS NULL`). There's no concept of "this repo has failed 15 times, maybe stop trying."

5. **Why doesn't the worker/scheduler surface this pattern?** No observability. The data is in the DB but nothing aggregates it or raises an alert. You'd only discover 6,028 repos in a rate-limit death spiral by running a query manually.

### Root cause
The handler raises the wrong exception type. Rate limits are an infrastructure constraint, not an application error. The worker's own `ResourceThrottledError` mechanism was designed exactly for this case but isn't being used.

### Blast radius
~27,720 wasted GitHub API calls (9,240 rows × 3 retries). That's ~6 hours of GitHub API budget burned on requests that were never going to succeed on retry because the rate limit doesn't reset between immediate retries.

---

## Incident 2: GitHub 301 Redirects (7,524 rows / 298 repos)

### What happened
Repos were renamed or transferred on GitHub. The stale `full_name` in `ai_repos` triggers a 301 redirect. Handlers without `follow_redirects=True` treat 301 as an error. Task retries 3 times (same stale name → same 301), fails permanently, scheduler re-enqueues. One repo was enqueued **66 separate times**.

### 5 Whys

1. **Why do requests return 301?** Because the repo was renamed/transferred on GitHub. The API returns `301 Moved Permanently` pointing to `/repositories/{numeric_id}`.

2. **Why is the name stale?** Because the main ingest (`github.py`) uses `follow_redirects=True` and silently gets the right data, but never checks whether the `full_name` in the API response differs from the database. It doesn't update `ai_repos.full_name`. The name rots.

3. **Why do some handlers fail on 301 while the main ingest doesn't?** Inconsistent httpx client configuration. `github.py`, `candidates.py`, `releases.py` all have `follow_redirects=True`. `fetch_readme.py` and `backfill_created_at.py` don't. Written at different times, no shared client configuration.

4. **Why does the same repo get enqueued 66 times?** Same mechanism as rate limits: the data condition that triggers scheduling (`created_at IS NULL`) is never satisfied because the task keeps failing. The dedup index doesn't cover `failed` state. Every 15 minutes → new task row → 3 more wasted API calls.

5. **Why does nobody notice 298 repos failing repeatedly for 2+ days?** No observability. No post-run summary, no anomaly detection, no error aggregation. The information exists in the DB but is invisible without manual queries.

### Root cause (proximate)
Missing `follow_redirects=True` in two handlers.

### Root cause (actual)
No rename detection at the source. The main ingest follows the redirect silently but never updates the canonical name, leaving a landmine for every downstream handler.

### Root cause (systemic)
No shared GitHub client configuration. Each handler independently configures httpx, leading to inconsistency.

### Blast radius
~22,572 wasted API calls (7,524 × 3). 298 repos with permanently stale names. Every future handler that hits GitHub with a stale name will discover this bug independently.

---

## Incident 3: Float vs Decimal Type Mismatch (2,325 rows)

### What happened
`enrich_repo_brief` (1,946) and `enrich_summary` (379) both failed with `TypeError: unsupported operand type(s) for -: 'float' and 'decimal.Decimal'`. All on 2026-04-05, all with `retry_count = 3`.

### 5 Whys

1. **Why the type error?** A numeric column comes back from Postgres as `decimal.Decimal` (psycopg2's default for `numeric` types). Python code does arithmetic with a `float` literal against this value. Python doesn't auto-coerce `float - Decimal`.

2. **Why did it retry 3 times?** Because the error is a generic `TypeError`, not classified as deterministic. The worker treats it identically to a transient network error. But a type mismatch will never self-resolve — every retry hits the exact same code path with the exact same types.

3. **Why were 2,325 repos affected?** The code path runs for every repo that enters the enrichment pipeline. Any repo with a non-NULL value in the affected numeric column triggers the bug. This was a universal code defect, not a data anomaly.

4. **Why was the bug introduced?** Likely a schema change (adding a `numeric` column or changing a column type) without updating the Python arithmetic that operates on it. No type-level contract between the DB schema and the Python code.

5. **Why wasn't this caught in dev?** No staging database. No type tests. The first execution on production data was the test.

### Status
Reported as fixed on Apr 5. Residual 2,325 failed rows remain in the table. The repos affected need their enrichment tasks re-created to recover.

### Blast radius
2,325 repos are missing briefs/summaries. ~6,975 wasted LLM calls (if enrich tasks make LLM calls before the arithmetic, or 0 if the arithmetic happens first).

---

## Incident 4: SQL Cast Syntax Error (425 rows / 350 subjects)

### What happened
The `mark_done()` function in `worker.py` used `:result::jsonb` (PostgreSQL cast syntax) inside a SQLAlchemy `text()` query. SQLAlchemy's parameter parser can't distinguish the bind marker `:result` from the cast operator `::`, causing a syntax error. Every task that succeeded in its handler but failed to save its result was marked as failed.

### 5 Whys

1. **Why the syntax error?** PR #207 changed `CAST(:result AS jsonb)` to `:result::jsonb`. Both are valid PostgreSQL, but SQLAlchemy `text()` only supports the `CAST()` form.

2. **Why was the PR merged?** Presumably the change looked correct (it is valid SQL) and wasn't caught in review because the difference is a SQLAlchemy parser subtlety, not a SQL correctness issue.

3. **Why were 350 repos affected?** The bug was in `mark_done()`, which is called for every successful task. All 425 tasks that completed successfully between PR #207 landing and PR #216 reverting it had their results silently discarded — the handler did the work (API calls, LLM calls, DB writes) but the task was marked `failed` instead of `done`.

4. **Why didn't the system notice?** No observability. A sudden spike in "tasks that complete their handler but fail to save results" would be an obvious anomaly, but nothing watches for it.

5. **Why was the bad fix attempted?** The original issue (Bug #2, `can't adapt type 'dict'`) was a real problem. The fix went through two iterations, and the second one introduced a new bug. No regression test confirmed the fix actually worked end-to-end.

### Status
Fixed in PR #216 (reverted to `CAST()`). But 425 tasks have wasted work: the handler did its job (API calls, LLM calls, writes) but the task is marked `failed` and the result is lost.

### Blast radius
425 tasks did real work (consumed API/LLM budget) then had their success silently discarded. The repos affected will be re-enqueued by the scheduler and the work will be redone — double the cost.

---

## Incident 5: GitHub 451 DMCA Takedown (53 rows / 1 repo)

### What happened
`IshaanLabs/Harry-Potter-Dataset` is DMCA'd. GitHub returns 451 (Unavailable for Legal Reasons). The handler treats this as an unknown error, retries 3 times, fails. The scheduler sees `created_at IS NULL` and re-enqueues. This has happened **53 times** for the same repo.

### 5 Whys

1. **Why 451?** The repo contains copyrighted Harry Potter content and has been taken down via DMCA.

2. **Why does the handler retry?** 451 falls into the `if resp.status_code != 200` catch-all, which raises `RuntimeError`. No special handling for 451.

3. **Why 53 re-enqueues?** Same scheduler loop as 301s and rate limits. `created_at IS NULL` → enqueue → fail → repeat.

4. **Why no exclusion list?** There's no mechanism to mark a repo as "permanently unfetchable" in `ai_repos`. No `is_archived`, `is_dmca`, or `skip_fetch` flag. The system assumes all repos are fetchable.

5. **Why doesn't anyone notice?** Same answer as every other incident: no observability.

### Root cause
No concept of permanent, non-retryable failure states in the data model. A DMCA'd repo will never return 200, but the system has no way to record "stop trying."

### Blast radius
Small (53 rows, 1 repo), but it's a class of problem: any removed, DMCA'd, or blocked repo will loop forever.

---

## Incident 6: Unknown Task Types (2 rows)

### What happened
Tasks with types `snapshot_bot_activity` and `detect_bot_sessions` were in the queue, but no handler is registered for them. The worker logs "Unknown task type" and marks them failed.

### 5 Whys

1. **Why are they unknown?** The handlers were removed (code deleted) but tasks were already enqueued in the DB.

2. **Why weren't the tasks cleaned up?** No migration or cleanup step when removing a handler. The scheduler created them, the handler was removed, and the orphaned tasks sat in `pending` until the worker picked them up and failed them.

3. **Why only 2?** The scheduler code that enqueued them was presumably also removed, so no new tasks are created. These are just stragglers.

### Root cause
No lifecycle management for task types. Removing a handler should include a cleanup step: `DELETE FROM tasks WHERE task_type = 'X' AND state = 'pending'`.

### Blast radius
Minimal — 2 tasks, no ongoing damage.

---

## Incident 7: SSL Connection Drop (1 row)

### What happened
`snapshot_bot_activity` had the Render Postgres connection drop mid-query: `SSL connection has been closed unexpectedly`. The query involved a `LIKE` join against `ai_repos`.

### Root cause
Transient infrastructure issue — Render occasionally drops long-running connections. The query itself was also slow (LIKE join pattern), making it more vulnerable to timeouts.

### Blast radius
Minimal — 1 occurrence. The LIKE join pattern has been noted for rewrite (see the manually-killed task).

---

## Cross-Cutting Systemic Issues

### 1. The Re-Enqueue Death Spiral

The single biggest structural problem across incidents 1, 2, and 5. The pattern:

```
Scheduler: "created_at IS NULL → enqueue"
Worker: "same error → fail (retry_count=3)"
Scheduler: "created_at is still NULL → enqueue again" (dedup doesn't cover 'failed')
Worker: "same error → fail again (fresh retry_count=0)"
... forever
```

**298 repos × 66 re-enqueues × 3 retries = ~59,000 wasted API calls** just for 301s. Rate limits add another ~27,000. This is the same mechanism in every case — the scheduler and the worker have no shared memory about what's been tried and failed.

### 2. No Error Classification

The worker has exactly two categories: `ResourceExhausted/Throttled` (infrastructure, no retry penalty) and `Exception` (application, burn a retry). But the actual error landscape is:

| Category | Correct action | Current action |
|---|---|---|
| Rate limited (403) | Backoff, don't count retry | Counts retry, burns budget |
| Redirect (301) | Follow redirect or fix data | Counts retry, re-enqueues forever |
| DMCA (451) | Mark repo unfetchable, never retry | Counts retry, re-enqueues forever |
| Not found (404) | Already handled correctly | ✓ Returns `no_readme`/`not_found` |
| Type error | Fail immediately, don't retry | Retries 3× identically |
| LLM empty result | Retry is reasonable | ✓ Already correct |
| SQL bug in worker | Fail immediately | Retries 3× identically |

### 3. No Observability

Every single incident ends with "Why didn't anyone notice?" → "No observability." The data is in the DB. A single post-run query would surface all of these:

```sql
SELECT
  task_type,
  <error_class>,
  count(*),
  count(DISTINCT subject_id)
FROM tasks
WHERE state = 'failed'
  AND completed_at > now() - interval '24h'
GROUP BY 1, 2
ORDER BY 3 DESC;
```

Nobody runs this. The worker doesn't run it. There's no cron for it. The information exists but is invisible.

---

---

## Addendum: Orphaned Pipeline Tasks (2026-04-07, evening)

Discovered while verifying the cleanup deployment. Three critical pipeline tasks — `compute_mv_refresh`, `export_static_site`, and `compute_structural` — have been stuck in `pending` state, never claimed by the worker. MV refresh hasn't run since April 5, which means no content budget, no Gemini enrichment, and no site deploys for 2 days.

### What happened

On April 5, the task queue was introduced in two steps:

1. **19:39 (commit 81a04f0)** — Pipeline tasks (MV refresh, static site export, etc.) were migrated to the task queue. The worker at this point had a simple loop: `claim_next_task(WORKER_ID)` — no resource filtering. It claimed any pending task, including those with `resource_type = NULL`. MV refresh ran successfully.

2. **22:26 (commit 6914398, 3 hours later)** — The worker was refactored for resource-aware concurrency. The loop changed to iterate over a fixed list of named resource slots (`github_api`, `gemini`, `openai`, etc.) and only claim tasks matching each slot. A fallback query (`_CLAIM_ANY_SQL`) was written for NULL-resource tasks, but the worker loop never calls it. The code path is dead.

Tasks scheduled with `resource_type = NULL` — `compute_mv_refresh`, `export_static_site`, and `compute_content_budget` — became permanently unclaimable. The scheduler kept checking staleness and not re-creating them (because a `pending` task already existed), so they just sat there.

### 5 Whys

**1. Why didn't the worker claim these tasks?**

The worker loop iterates `CONCURRENT_RESOURCES` (9 named resource types) and calls `claim_next_task(worker_id, resource_type=resource)` for each. This uses `_CLAIM_FOR_RESOURCE_SQL`, which filters `WHERE t.resource_type = :target_resource`. NULL doesn't match any named resource. The `_CLAIM_ANY_SQL` query (which handles NULL) exists but is only called when `resource_type=None` is passed to `claim_next_task()`, which the worker loop never does.

**2. Why wasn't the dead code path caught during the refactor?**

The concurrency refactor was done 3 hours after the task queue migration, in the same session. MV refresh had just run successfully under the old code, and the sync_log showed a recent success. The scheduler's staleness check (`last success > 6h ago`) wouldn't fire until the window elapsed — by which time nobody was watching. The success of the first change masked the breakage of the second.

**3. Why did nobody notice for 2 days?**

`check_pipeline_freshness()` correctly detected the problem within hours and logged `HEALTH: MV refresh is stale` at ERROR level every 15 minutes — approximately 192 times over 2 days. All ignored, because log-based alerts are write-only. They produce signals but nothing ensures a human sees them. The alert fired correctly; the notification channel doesn't exist.

**4. Why is there no test that catches this class of bug?**

There is no integration test for the task lifecycle. Nothing verifies "for every task_type the scheduler creates, the worker can actually claim and execute it." The scheduler and worker are tested (if at all) in isolation — the scheduler creates tasks, the worker processes tasks, but nobody checks that the contract between them holds. A mismatch in `resource_type` between creation and claiming is invisible unless you run both together.

**5. Why is there no detection of orphaned tasks?**

The stale task reaper (`reap_stale_tasks()`) catches tasks stuck in `claimed` state with dead heartbeats — a worker crashed mid-execution. But it doesn't check for tasks stuck in `pending` state that were never claimed. A task that sits in `pending` for hours is a different failure mode: not a crashed worker, but a task the worker doesn't know how to pick up. Nothing monitors for this.

### Blast radius

The MV refresh → content budget → enrichment pipeline has been stalled for 2 days:

| Task | State | Stuck since | Downstream impact |
|---|---|---|---|
| `compute_mv_refresh` | pending | 2026-04-06 01:18 | No fresh materialized views |
| `compute_content_budget` | never created | — | Budget gate blocks all Gemini enrichment |
| `export_static_site` | pending | unknown | No site deploys |
| `compute_structural` | pending | unknown (id 25) | No weekly structural analysis |
| All Gemini enrichment | not scheduled | — | 10,000/day Gemini budget sitting unused |

### Cross-cutting issues this exposes

**1. Log-based health alerts are insufficient**

`check_pipeline_freshness()` detected the problem correctly and immediately. The mechanism works. The delivery doesn't. ERROR-level log lines are invisible unless someone is reading logs — which is the exact scenario these alerts are supposed to prevent. Health checks need a notification channel that reaches a human: a webhook, a daily email, or at minimum a table that accumulates alerts so they're visible in the failure summary.

**2. No orphan detection for pending tasks**

The system monitors two failure modes:
- Tasks that fail (error classification, failure summary) ✓
- Tasks stuck in claimed state (stale task reaper) ✓

It doesn't monitor:
- Tasks stuck in pending state that are never claimed ✗
- Task types the scheduler creates but the worker can't process ✗
- Pipeline stages that should have run but didn't ✗

A task in `pending` for >1 hour with `retry_count = 0` has never been claimed. That's always suspicious.

**3. Refactors done in the same session as migrations are invisible**

When you migrate a process to a new system and then refactor the new system in the same sitting, the old success masks the new breakage. The staleness window hasn't elapsed, so the scheduler thinks everything is fine. This is a human process issue, not a code issue — but orphan detection (above) would catch it mechanically.

**4. No contract test between scheduler and worker**

The scheduler creates tasks with specific `resource_type` values. The worker claims tasks by iterating a hardcoded list of resource types. These two lists are not derived from the same source. When they diverge — as they did here — tasks become unclaimable. A periodic check that every pending task's `resource_type` is either NULL (with a claiming path) or in the worker's `CONCURRENT_RESOURCES` list would catch this.

---

## Implementation Plan: Orphaned Task Fixes

### PR 6: Fix NULL-resource task claiming in worker loop

**Why first:** The pipeline is stalled. MV refresh, site export, and content budget are all blocked. This unblocks them immediately.

**Scope:**

Add a `None` slot to the worker loop so it claims NULL-resource tasks via the existing `_CLAIM_ANY_SQL` query. After iterating all named resource slots, attempt to claim one NULL-resource task if no slot is occupied for it:

```python
# After the CONCURRENT_RESOURCES loop, claim NULL-resource tasks
if "_none" not in running or running["_none"].done():
    if "_none" in running:
        del running["_none"]
    task = claim_next_task(WORKER_ID, resource_type=None)
    if task:
        running["_none"] = asyncio.create_task(
            _execute_task(task, TASK_HANDLERS)
        )
        claimed_any = True
```

Also delete the three stuck pending tasks so the scheduler can re-create them with a clean slate — they've been pending for over a day and may have stale staleness checks.

**Files:**
- `app/queue/worker.py` — add NULL-resource claiming to `worker_loop()`

**Verification:**
- Delete the stuck tasks: `DELETE FROM tasks WHERE id IN (1072614, 25, 1050);`
- Deploy, confirm scheduler creates fresh `compute_mv_refresh` task
- Confirm worker claims and executes it within one cycle
- Confirm `sync_log` shows a fresh MV refresh success
- Confirm content budget is computed and Gemini enrichment resumes

### PR 7: Add orphan detection to scheduler health checks

**Why second:** Prevents this class of bug from going unnoticed again. Even if the fix in PR 6 is correct today, a future refactor could re-introduce the same problem.

**Scope:**

Add `check_orphaned_tasks()` to the scheduler health checks. Query for tasks stuck in `pending` for over 1 hour with `retry_count = 0` (never claimed):

```sql
SELECT task_type, resource_type, count(*),
       min(created_at) AS oldest
FROM tasks
WHERE state = 'pending'
  AND created_at < now() - interval '1 hour'
  AND retry_count = 0
GROUP BY 1, 2
```

Log at ERROR level if any are found. Include the `resource_type` so the error message directly points at why the worker can't claim them.

Also add a contract check: verify that every `resource_type` in pending tasks is either NULL or present in the worker's `CONCURRENT_RESOURCES` list. Log ERROR if a pending task has a `resource_type` the worker doesn't know about.

**Files:**
- `app/queue/scheduler.py` — add `check_orphaned_tasks()`, call from `schedule_all()`
- `app/queue/worker.py` — export `CONCURRENT_RESOURCES` (it's already module-level, just needs to be importable)

**Verification:**
- Temporarily insert a task with a bogus `resource_type` (e.g. `'nonexistent'`)
- Confirm the health check logs an ERROR about it within one scheduler cycle
- Delete the test task

### PR 8 (future): Health check notification channel

**Why deferred:** Requires choosing an external service (Slack webhook, email, etc.) which is an infrastructure decision beyond a code fix. But this is the real gap — `check_pipeline_freshness()` has been correctly detecting the MV refresh stall for 2 days and logging 192 ERROR lines that nobody read.

**Options (from simplest to most robust):**
1. **Daily health digest to a DB table** — `health_alerts` table, one row per alert, queryable via psql or MCP. Lowest effort, still requires someone to look.
2. **Webhook to Slack/Discord** — Push alerts to a channel. Requires a webhook URL. Medium effort, actually reaches a human.
3. **Email via SendGrid/SES** — Daily digest of health alerts. Requires email service setup.

The right answer depends on what you actually look at daily. If you check Slack, use a webhook. If you check email, send a digest. If you only check psql, a table is fine. The mechanism matters less than "does it reach you?"

---

## Recovery Required



| Error Class | Rows | Recovery Action |
|---|---|---|
| `github_rate_limited` | 9,240 | Fix handler to use `ResourceThrottledError`. Clean up failed rows. Repos will be re-enqueued naturally. |
| `github_301_redirect` | 7,524 | Fix `follow_redirects`. Add rename detection in main ingest. Clean up failed rows. |
| `float_vs_decimal` | 2,325 | Already fixed. Delete failed rows so scheduler re-enqueues for enrichment. |
| `sql_cast_syntax` | 425 | Already fixed. Delete failed rows to allow re-processing. |
| `github_451_dmca` | 53 | Add repo-level skip flag. Mark DMCA'd repos. Delete failed rows. |
| `unknown_task_type` | 2 | Delete these rows. |
| `ssl_dropped` | 1 | Delete. Transient. |
| `manually_killed` | 1 | Leave as documentation. |
