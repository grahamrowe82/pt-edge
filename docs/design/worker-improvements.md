# Worker Improvement Plan

*5 April 2026. Based on observing the first live run of the task queue.*

Each improvement is a single PR. They're ordered by impact and can be done independently — no PR depends on another.

---

## PR 1: Cap pending tasks and fix prerequisite checks

**Problem:** The scheduler dumps the entire backlog into the tasks table on its first pass. Right now there are 230K `fetch_readme` and 230K `enrich_repo_brief` tasks pending — 461K rows for work that will take weeks to process. The `backfill_created_at` scheduler already has the right pattern (caps at 500 pending, creates batches of 1,000), but the other fine-grained schedulers don't.

Additionally, `enrich_repo_brief` tasks are being created for repos that don't have summaries yet. The handler claims them, finds no data, and returns immediately — wasting a claim cycle.

**Changes:**
- `scheduler.py`: Add pending-count cap (500) to `schedule_fetch_readmes()`, `schedule_enrich_summaries()`, `schedule_enrich_comparisons()`, and `schedule_enrich_repo_briefs()`, matching the `backfill_created_at` pattern
- `scheduler.py`: Add `AND ar.ai_summary IS NOT NULL` to `schedule_enrich_repo_briefs()` — briefs only make sense for repos that have already been enriched
- Delete the 461K orphaned pending tasks that were already created:
  ```sql
  DELETE FROM tasks WHERE task_type IN ('fetch_readme', 'enrich_repo_brief') AND state = 'pending';
  ```

**Files:** `app/queue/scheduler.py`

---

## PR 2: Background heartbeating during task execution

**Problem:** The worker only heartbeats between tasks, not during them. Coarse tasks like `fetch_github` (5 min), `enrich_subcategory` (potentially 30+ min with 7,500 LLM calls), or `compute_structural` (unknown duration) run without updating their heartbeat. If a task takes more than 10 minutes, the reaper reclaims it — and then two instances run simultaneously, wasting budget and potentially causing data conflicts.

**Changes:**
- `worker.py`: Start a background asyncio task that updates `heartbeat_at` every 60 seconds for the currently claimed task. Cancel it when the task completes (done, failed, or requeued).

**Files:** `app/queue/worker.py`

---

## PR 3: Import structural functions instead of shelling out

**Problem:** `handle_compute_structural()` is the only handler that runs a subprocess (`scripts/weekly_structural.py`). Every other handler imports functions directly. The subprocess approach loses structured error reporting, doesn't heartbeat, and is harder to test.

**Changes:**
- Refactor `scripts/weekly_structural.py` so its key functions (`discover_comparison_pairs`, `recompute_centroids`, `label_new_categories`) are importable from `app/` (move them to `app/ingest/structural.py` or similar, keep the script as a thin CLI wrapper)
- Update `handle_compute_structural()` to import and call the functions directly

**Files:** `scripts/weekly_structural.py`, `app/ingest/structural.py` (new), `app/queue/handlers/compute_post_process.py`

---

## PR 4: Accurate budget tracking for coarse tasks

**Problem:** Coarse tasks like `fetch_github` consume ~3,000 GitHub API calls internally but decrement the resource budget by 1 (one task claimed = one unit consumed). The budget table says `github_api consumed: 1` when the real number is 3,000. This makes the budget numbers useless for observability and would cause concurrent overload if we ever run multiple workers.

**Changes:**
- Add a `decrement_budget(resource_type, count)` function to `worker.py`
- Have coarse handlers that wrap existing functions update the budget with their actual consumption. The existing functions already track their call counts in their return dicts (e.g., `ingest_github()` returns `{"projects": N}`). The handler reads the return dict and decrements accordingly.
- For handlers where internal call count isn't available, estimate from the return value (e.g., `fetch_releases` processes ~800 projects = ~800 GitHub calls)

**Files:** `app/queue/worker.py`, `app/queue/handlers/fetch_github.py`, `app/queue/handlers/fetch_releases.py`, `app/queue/handlers/fetch_data.py` (for `fetch_ai_repo_commits`)

---

## PR 5: Concurrent task execution by resource type

**Problem:** The worker processes one task at a time. While a GitHub task runs (5 min, I/O-bound), Gemini budget sits idle. While a Gemini task runs, GitHub budget sits idle. The whole point of the architecture is that tasks with different resource types don't compete — but the single-threaded worker can't exploit this.

**Changes:**
- `worker.py`: Replace the single claim-execute loop with a resource-aware concurrent executor. The worker maintains one active task per resource type (github_api, gemini, openai, none). When a task completes, it claims the next task for that resource type. Tasks with `resource_type = None` run sequentially to avoid overloading the database.
- Keep it simple: `asyncio.gather` with up to 4 concurrent tasks (one per resource type). No thread pool, no complex scheduling.

**Files:** `app/queue/worker.py`

---

## PR 6: Add resource types for external APIs

**Problem:** Most coarse tasks have `resource_type = None`, bypassing budget checks. Tasks like `fetch_downloads` (hits PyPI/npm), `fetch_huggingface` (hits HF API), and `fetch_newsletters` (HTTP fetches) use external APIs but aren't budget-tracked. Today this is fine because they run one at a time, but with concurrent execution (PR 5) they could fire simultaneously.

**Changes:**
- Add resource budget rows for `pypi`, `npm`, `huggingface`, `hn_algolia`
- Update `_schedule_coarse_task` calls in `scheduler.py` to assign appropriate resource types
- The handlers themselves don't change — the budget gating happens at claim time

**Files:** `app/queue/scheduler.py`, new Alembic migration for budget seed rows

---

## Delivery Plan

Two PRs, grouped by theme:

### PR A: Fix scheduler discipline (PRs 1-3 above)

Make the system robust. Cap pending tasks, add prerequisite checks, add background heartbeating, import structural functions. One theme: the scheduler and worker should do basic things correctly.

**Urgent.** The tasks table is bloated with 461K useless rows and long tasks risk duplicate execution.

### PR B: Resource-aware concurrency (PRs 4-6 above)

Unlock throughput. Accurate budget tracking, concurrent execution by resource type, resource types for external APIs. One theme: let the worker use multiple resources simultaneously.

**When throughput becomes the bottleneck.** Not urgent today with a single worker processing tasks sequentially.
