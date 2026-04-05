# Worker Architecture Design

*First draft: 5 April 2026. Written from memory before auditing the codebase.*

## Intent

Replace the monolithic sequential `runner.py` pipeline (and its Saturday/Sunday cron variants) with a database-driven work queue architecture. The goal is a system of small, independent, stateless units that share one source of truth: the database.

There is no concept of a "daily run", a "Sunday run", or a "Saturday run." There is a queue of work, ordered by priority, constrained by resource budgets. Workers process it continuously. The day of the week is irrelevant.

## Architecture: Three Layers

### Layer 1: The Work Queue (Postgres)

Every unit of work is a row in a `tasks` table. A task has:

- **What** to do (`task_type` + `subject_id`)
- **How important** it is (`priority`, 1-10)
- **What resources** it needs (`resource_type`: github_api, gemini, none)
- **What it costs** (`estimated_cost_usd`)
- **Where it is** in its lifecycle (`state`: pending, claimed, done, failed)
- **Who's working on it** (`claimed_by`, `claimed_at`, `heartbeat_at`)

No worker decides what to do by reading code. It asks the database: "give me the highest-priority pending task whose resource requirements I can afford right now."

```sql
-- Claim the next task
UPDATE tasks
SET state = 'claimed', claimed_by = :worker_id, claimed_at = now()
WHERE id = (
    SELECT t.id FROM tasks t
    JOIN resource_budgets rb ON rb.resource_type = t.resource_type
    WHERE t.state = 'pending'
      AND rb.remaining > 0
    ORDER BY t.priority DESC, t.created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING *;
```

### Layer 2: Workers (Stateless, Interchangeable)

A worker is a loop:

1. Claim the highest-priority affordable task
2. Read inputs from the database (cached README, repo metadata, etc.)
3. Do the work (API call, LLM call, computation)
4. Write the result to the database
5. Mark the task done
6. Decrement the resource budget
7. Repeat

Workers don't know what ran before them. They don't know what's running beside them. They read from the database, write to the database. If a worker crashes, its claimed task hasn't heartbeated in N minutes, so the scheduler (or a reaper) returns it to pending. Another worker picks it up.

Because workers are stateless, you can run one or five. You can restart them without losing progress. You can deploy new code and restart without disrupting in-flight work (the incomplete task just gets reclaimed).

On the current Render standard plan, this is likely a single worker process. But the architecture doesn't care — it works identically with multiple workers.

### Layer 3: The Scheduler (Thin, Dumb)

The scheduler creates tasks. It never executes them. It runs periodically (every 15 minutes, every hour — doesn't matter much) and asks:

- "Which repos haven't had their GitHub metadata refreshed in 24 hours?" → Create `fetch_github` tasks at priority 7
- "Which repos have no cached README?" → Create `fetch_readme` tasks at priority 8
- "Which repos have a cached README but no problem brief?" → Create `enrich_summary` tasks at priority 9
- "Which repos haven't had their created_at backfilled?" → Create `backfill_created_at` tasks at priority 2
- "Which domain briefs are older than 7 days?" → Create `enrich_domain_brief` tasks at priority 3
- "Have materialized views been refreshed in the last 6 hours?" → Create `refresh_mv` tasks at priority 5

The scheduler is the only place that knows about cadence and staleness. Workers know nothing about scheduling. The scheduler knows nothing about execution.

## Data Model

### tasks

```sql
CREATE TABLE tasks (
    id              bigserial PRIMARY KEY,
    task_type       text NOT NULL,          -- e.g. 'fetch_github', 'enrich_summary'
    subject_id      text,                   -- e.g. repo slug, project id, domain name
    priority        smallint NOT NULL,       -- 1 (lowest) to 10 (highest)
    state           text NOT NULL DEFAULT 'pending',  -- pending, claimed, done, failed
    resource_type   text,                   -- github_api, gemini, pypi, npm, none
    estimated_cost_usd numeric(10,6),
    claimed_by      text,                   -- worker identifier
    claimed_at      timestamptz,
    heartbeat_at    timestamptz,
    completed_at    timestamptz,
    result          jsonb,                  -- output payload if needed
    error_message   text,
    retry_count     smallint DEFAULT 0,
    max_retries     smallint DEFAULT 3,
    created_at      timestamptz DEFAULT now()
);

CREATE INDEX idx_tasks_claimable ON tasks (priority DESC, created_at ASC)
    WHERE state = 'pending';
```

### resource_budgets

```sql
CREATE TABLE resource_budgets (
    resource_type   text PRIMARY KEY,       -- github_api, gemini, dollars
    period_start    timestamptz NOT NULL,
    period_hours    int NOT NULL,           -- e.g. 1 for GitHub (hourly), 24 for dollars (daily)
    budget          int NOT NULL,           -- total allowed in period
    consumed        int NOT NULL DEFAULT 0,
    remaining       int GENERATED ALWAYS AS (budget - consumed) STORED
);
```

The budget resets when `now() > period_start + period_hours * interval '1 hour'`. A periodic job (or the scheduler itself) resets `consumed` to 0 and advances `period_start`.

Resource types and their budgets:
- `github_api`: 5,000/hour
- `gemini`: 800/minute (or whatever the current RPM limit is)
- `dollars`: configurable daily spend cap

### raw_cache

```sql
CREATE TABLE raw_cache (
    source          text NOT NULL,          -- github_readme, github_repo, pypi_meta, etc.
    subject_id      text NOT NULL,          -- repo slug, package name
    fetched_at      timestamptz NOT NULL,
    payload         text,                   -- raw content (README markdown, JSON response)
    PRIMARY KEY (source, subject_id)
);
```

Every expensive fetch gets stored here. When a worker needs a README to send to Gemini, it checks `raw_cache` first. If the README was fetched in the last N days, use the cache. If not, fetch it, store it, then proceed.

This means:
- Prompt iteration is free (replay cached READMEs against new prompts)
- Rate limit pressure drops dramatically after the first pass
- You can inspect exactly what input produced what output

### llm_cache

```sql
CREATE TABLE llm_cache (
    id              bigserial PRIMARY KEY,
    task_type       text NOT NULL,          -- which enrichment pipeline
    subject_id      text NOT NULL,
    model           text NOT NULL,          -- gemini-2.0-flash, etc.
    prompt_hash     text NOT NULL,          -- hash of the full prompt
    input_text      text,                   -- the README or source material
    prompt_template text,                   -- the system/user prompt used
    response        text,                   -- raw LLM output
    cost_usd        numeric(10,6),
    created_at      timestamptz DEFAULT now()
);
```

Every LLM call gets logged with its input and output. If the prompt hasn't changed and the input hasn't changed, skip the call entirely. If the prompt changes, you can rerun against cached inputs without refetching.

## Task Types

### High priority (8-10): Revenue-critical enrichment

| Task Type | Subject | Resource | Notes |
|-----------|---------|----------|-------|
| `enrich_summary` | repo slug | gemini | Problem brief via Gemini Flash |
| `enrich_repo_brief` | repo slug | gemini | Full repo brief |
| `enrich_project_brief` | project id | gemini | Project-level brief |
| `enrich_comparison` | repo pair | gemini | Comparison sentence |

### Medium priority (5-7): Core data freshness

| Task Type | Subject | Resource | Notes |
|-----------|---------|----------|-------|
| `fetch_github` | repo slug | github_api | Metadata refresh (stars, forks, etc.) |
| `fetch_readme` | repo slug | github_api | Cache README for enrichment |
| `fetch_downloads` | repo slug | none* | PyPI/npm/Docker — different rate limits |
| `fetch_hf` | repo slug | none* | HuggingFace metadata |
| `import_gsc` | date | none | Google Search Console import |
| `import_umami` | date | none | Analytics ETL |
| `refresh_mv` | view name | none | Materialized view refresh |
| `deploy_site` | — | none | Trigger Render static site webhook |

### Low priority (1-4): Backfills and periodic enrichment

| Task Type | Subject | Resource | Notes |
|-----------|---------|----------|-------|
| `enrich_domain_brief` | domain | gemini | Domain-level brief |
| `enrich_landscape_brief` | landscape | gemini | Landscape-level brief |
| `backfill_created_at` | repo slug | github_api | Historical creation dates |
| `fetch_candidates` | — | github_api | Discover new repos |
| `classify_subcategory` | repo slug | none | Subcategory assignment |
| `compute_embeddings` | repo slug | none* | Vector embeddings |

## Priority Scheme

```
10  — (reserved for manual urgent tasks)
 9  — Content enrichment: summaries, repo briefs, project briefs
 8  — README caching (prerequisite for enrichment)
 7  — Core data: GitHub metadata, downloads, trending
 6  — Analytics: GSC, Umami, HN backlinking
 5  — Infrastructure: MV refresh, site deploy, stack layers
 4  — Discovery: candidates, candidate velocity
 3  — Periodic enrichment: domain briefs, landscape briefs, comparison sentences
 2  — Backfills: created_at, package deps, builder tools
 1  — Opportunistic: anything that can wait indefinitely
```

This means enrichment always runs before backfills. If GitHub budget is tight, the backfill starves — not the enrichment pipeline. Domain briefs run when the queue is quiet, not "on Sundays."

## Dependencies

Some tasks have genuine prerequisites:

- `enrich_summary` requires a cached README → depends on `fetch_readme`
- `enrich_repo_brief` requires a summary → depends on `enrich_summary`
- `enrich_project_brief` requires repo briefs → depends on `enrich_repo_brief`
- `enrich_domain_brief` requires project briefs → depends on `enrich_project_brief`
- `refresh_mv` should run after a batch of data ingestion, not after every single fetch
- `deploy_site` should run after MV refresh and content enrichment

The simplest way to handle this: the scheduler only creates a task when its prerequisites are met. It doesn't create `enrich_summary` for repo X until repo X has a cached README newer than its last summary. It doesn't create `refresh_mv` until N data tasks have completed since the last refresh.

No in-process dependency tracking. The scheduler queries the database to see what's ready.

## Budget Mechanics

### GitHub API (5,000/hour)

The worker checks `resource_budgets` before claiming any `github_api` task. After completing the task, it decrements the budget. If the budget is zero, it skips `github_api` tasks and claims something else (Gemini enrichment, MV refresh, analytics import — anything that doesn't need GitHub).

This naturally partitions the budget by priority. If there are 5,000 calls available this hour and 2,000 priority-9 README fetches pending, those get claimed first. The priority-2 backfill only gets GitHub calls when nothing more important needs them.

### Gemini (RPM limit)

Same mechanics. The worker checks the Gemini budget, claims enrichment tasks only when budget allows, decrements after each call.

### Dollar spend

A daily (or rolling) dollar cap. Each task has an `estimated_cost_usd`. The worker checks remaining dollar budget before claiming expensive tasks. This prevents runaway spend if something goes wrong.

## Observability

Because every task is a database row, observability is just SQL:

```sql
-- What's happening right now?
SELECT task_type, state, count(*) FROM tasks
WHERE created_at > now() - interval '24 hours'
GROUP BY task_type, state;

-- How fast is enrichment progressing?
SELECT date_trunc('hour', completed_at) AS hour, count(*)
FROM tasks WHERE task_type = 'enrich_summary' AND state = 'done'
GROUP BY 1 ORDER BY 1;

-- What's the GitHub budget situation?
SELECT * FROM resource_budgets WHERE resource_type = 'github_api';

-- What's stuck?
SELECT * FROM tasks
WHERE state = 'claimed'
AND heartbeat_at < now() - interval '10 minutes';

-- What failed and why?
SELECT task_type, subject_id, error_message, retry_count
FROM tasks WHERE state = 'failed'
ORDER BY created_at DESC LIMIT 20;
```

No special dashboards needed. No log parsing. The database is the dashboard.

## Migration Path

This is a big architectural change but it doesn't have to be a big bang. A plausible sequence:

1. **Create the tables** (`tasks`, `resource_budgets`, `raw_cache`, `llm_cache`)
2. **Build the worker loop** (claim/execute/complete cycle with heartbeating)
3. **Port one task type** — start with `enrich_summary` since it's the most valuable and most independent
4. **Build the scheduler** for that one task type
5. **Run the old pipeline and the new worker side by side** — the old pipeline does everything except summaries, the new worker handles summaries
6. **Port task types one at a time**, removing them from `runner.py` as each one moves to the queue
7. **Kill the cron jobs** when `runner.py` is empty

At no point does the system break. The old pipeline shrinks as the new worker grows.

## What the Render deployment looks like

Currently: three cron jobs (daily, Saturday, Sunday) that invoke `runner.py` with different flags.

Target: one persistent worker process (a Render background worker or web service that just loops). The scheduler could be a lightweight cron job that runs every 15 minutes, or it could be a thread inside the worker.

The worker process is a single Python script:

```
while True:
    task = claim_next_task()
    if task is None:
        sleep(30)
        continue
    try:
        execute(task)
        mark_done(task)
    except Exception as e:
        mark_failed(task, error=str(e))
    heartbeat()
```

Each `task_type` maps to a function. The functions are the existing ingest/enrichment code, extracted from `runner.py` and made to operate on a single subject (one repo, one view, one domain) rather than in bulk.

---

## Research Findings (Audit of 5 April 2026)

Full research notes in `scratch/research-*.md`. Below is the consolidated picture.

### The Current Pipeline: 49 Sequential Jobs

`runner.py:run_all()` executes 49 jobs in strict sequence with zero parallelism. Three separate entry points exist:

| Entry Point | Schedule | Script | What It Does |
|-------------|----------|--------|--------------|
| Daily worker | 06:00 UTC daily | `scripts/ingest_worker.py` → `ingest_all.py` → `runner.run_all()` | All 49 jobs |
| Saturday cron | 12:00 UTC Saturdays | `scripts/ingest_ai_repos.py` | GitHub Search API discovery (~220K repos) |
| Sunday cron | 03:00 UTC Sundays | `scripts/weekly_structural.py` | Comparison pairs, centroids, labels, coverage audit |

Additionally, `run_all()` has a hardcoded `weekday() == 6` check that runs domain_briefs and landscape_briefs only on Sundays.

The worker is already a persistent Render background worker (not a cron), specifically to avoid Render's 12-hour cron timeout. It sleeps until 06:00 UTC, spawns `ingest_all.py` as a subprocess with `timeout=None`, and self-deploys via the Render API after success.

#### Execution Order

**Phase 1 — Fast data ingestion (no LLM, <5 min each):**
1. `github` — 800 projects × 3-4 API calls each (~2,400-3,200 GitHub calls)
2. `downloads` — PyPI/npm/Docker download counts
3. `dockerhub` — Docker Hub metadata
4. `vscode` — VS Code Marketplace stats
5. `huggingface` — HuggingFace model download stats
6. `hn` — Hacker News Algolia search (22 terms)
7. `v2ex` — V2EX forum posts
8. `trending` — GitHub Search trending repos
9. `candidate_velocity` — Re-score all pending candidates

**Phase 2 — Slow discovery (minutes to hours):**
10-20. `hf_datasets`, `hf_models`, `public_apis`, `api_specs`, `package_deps`, `dep_velocity`, `builder_tools`, `npm_mcp`, `ai_repo_downloads` (1.5h), `ai_repo_commits`, `candidate_watchlist`

**Phase 3 — LLM-dependent:**
21-23. `ai_repo_package_detect`, `releases` (~800 GitHub calls), `newsletters`

**Post-loop (24-49):** GSC, Umami, coview, HN backfill, HN LLM match, V2EX backfill, subcategory, subcategory_llm, stack_layer, domain_reassign, project_linking, models, embeddings, **MV refresh**, content_budget, **ai_summaries** (up to 25K Gemini calls), comparison_sentences, repo_briefs, dataset_export, project_briefs, domain_briefs (Sunday), landscape_briefs (Sunday), briefing_refresh, **static site deploy**, **ai_repo_created_at** (10h backfill, up to 45K GitHub calls)

#### Failure Handling

Robust at the job level: every job is individually `try/except`'d, failures don't cascade. DB connection errors get 3 retries with exponential backoff (10s, 30s, 60s). The worker allows one retry per day and self-heals on restart. An advisory lock (`pg_try_advisory_lock(8675309)`) prevents concurrent runs.

**Critical gap:** No item-level tracking. When `ai_summaries` processes 50 repos and 3 fail, there's no record of which 3 or why. Only the job-level sync_log entry exists.

#### Idempotency

Most jobs are idempotent via `ON CONFLICT` upserts and `WHERE column IS NULL` guards. LLM-dependent jobs are idempotent in data terms but burn budget on re-run. The project_briefs/landscape_briefs use `generation_hash` (SHA-256 of key metrics) for smart staleness detection.

#### Real Dependencies vs. Accidental Sequencing

**Genuinely sequential:**
- `content_budget` depends on MV refresh (reads `mv_allocation_scores`)
- `ai_summaries`, `comparison_sentences`, `repo_briefs` depend on `content_budget`
- `project_briefs` and `domain_briefs` depend on MV refresh
- `embeddings` should run before MV refresh (some MVs use embedding data)
- `static_site` deploy should run after MV refresh + content enrichment
- `subcategory_llm` depends on `subcategory` (LLM fallback after regex)
- `hn_llm_match` depends on `hn_backfill` + `hn_lab_backfill`

**Completely independent (could run in parallel):**
- All Phase 1 jobs are independent of each other
- Most Phase 2 jobs are independent (except dep_velocity → package_deps)
- GSC, Umami, coview are independent of everything
- models (OpenRouter) is independent

**Known ordering bug:** `package_deps` (#14) runs before `ai_repo_package_detect` (#21), so LLM-detected packages don't get dependency data until the next day.

### GitHub Rate Limits

**One token shared across everything.** A single `GITHUB_TOKEN` PAT is used by all four Render services (web, worker, two crons). 5,000 requests/hour REST, 5,000 points/hour GraphQL, 30 requests/minute Search API.

**No centralised tracking.** Each of ~10 modules implements its own ad-hoc approach:

| Module | Approach |
|--------|----------|
| `github.py` | Pre-flight `/rate_limit` check; aborts all on first 403 |
| `ai_repo_summaries.py` | Best-in-class: pre-flight + periodic check every 200 fetches + 403 abort + README cache. Safety floor: 1,000 remaining |
| `ai_repo_commits.py` | Pre-flight `/rate_limit` check on GraphQL bucket; skips if <50 |
| `ai_repo_created_at.py` | Fixed 0.8s delay (~4,500/hr); stops on 403. No pre-flight check |
| `github_search.py` | `Retry-After` header + 2 retries; `CallCounter(budget=3000)` |
| `audit_coverage.py` | `X-RateLimit-Reset` header + 3 retries |
| Everything else | No rate limit handling at all |

**Dead setting:** `GITHUB_RATE_LIMIT = 10.0` in `app/settings.py` is defined but never referenced anywhere.

**No module reads `X-RateLimit-Remaining` from response headers.** Budget awareness comes only from explicit `/rate_limit` endpoint calls.

**Daily GitHub call budget:**

| Consumer | Calls/day | Priority in new system |
|----------|-----------|----------------------|
| `github` (projects) | ~2,400-3,200 | 7 |
| `releases` | ~800 | 6 |
| `ai_repo_summaries` (README fetch) | up to 25,000 | 9 |
| `ai_repo_created_at` (backfill) | up to 45,000 | 2 |
| `candidate_velocity` | variable | 4 |
| `ai_repos` (Saturday weekly) | up to 3,000 | 4 |
| Others (trending, npm_mcp, hn, v2ex) | small | various |
| **Total demand** | **~76,000-79,000+** | |
| **Available** | **120,000** (5K/hr × 24h) | |

### Gemini / LLM

**Model:** `gemini-2.5-flash` with thinking disabled (`thinkingBudget: 0`).

**Rate limit:** 800 RPM (safety margin on 1,000 RPM paid tier). Token-bucket rate limiter in `app/ingest/rate_limit.py`. No daily cap — volume controlled by pipeline limits and `LLM_BUDGET_MULTIPLIER` (5.0).

**Retry:** 3 retries with exponential backoff. HTTP errors: 5s, 10s, 20s. 429s: 15s, 30s, 60s (max 120s). `ai_repo_summaries` also has a `MAX_LLM_FAILURES = 10` circuit breaker.

**Cost:** No tracking in codebase. Migration plan estimates ~$3-6/day for ~31K calls. No token counting, no spend logging.

**16 distinct LLM tasks** across 14 files, all routing through `app/ingest/llm.py`:

| Task | Volume/day | max_tokens | Batching |
|------|-----------|------------|----------|
| Problem briefs (ai_summaries) | up to 25,000 | 400 | 1 per call |
| Subcategory classification | up to 7,500 | 2048 | 30 per batch |
| HN post matching | up to 5,000 | 2048 | 20 per batch |
| Comparison sentences | up to 2,000 | 150 | 1 per call |
| Repo briefs | budget-driven (~2,000) | 4096 | 10 per batch |
| Package detection | up to 500 | 2048 | 20 per batch |
| Project briefs | max 100 | 4096 | 10 per batch |
| Release summaries | per new release | 512 | 1 per call |
| Newsletter extraction | ~50-100 | 8192 | 1 per call |
| Domain briefs | ~17 domains | 2048 | 1 per call |
| Landscape briefs | ~10 layers | 2048 | 1 per call |
| Stack layer classification | varies | 2048 | 30 per batch |
| Builder tool matching | ~120 tools | 2048 | batch |
| Candidate domain check | per candidate | 20 | 1 per call |
| V2EX relevance | per post | 10 | 1 per call |

### Caching: What Exists Today

**READMEs:** Partially cached in `ai_repos.readme_cache` (text column) + `readme_cached_at` timestamp. Truncated to 8,000 chars. 90-day freshness window. **But only 141 repos have cached READMEs** (0.06% of 247K). Critical bug: the README is only saved when the LLM call also succeeds. If the LLM fails, the freshly-fetched README is discarded and must be re-fetched.

**LLM responses:** Never stored raw. Only parsed output fields are saved (e.g., `ai_summary`, `use_this_if`, `sentence`). No prompt-response cache exists. Prompt iteration requires re-fetching inputs and re-calling the LLM.

**Other API responses:** Not cached. GitHub repo metadata, PyPI/npm/crates.io package metadata, HuggingFace data — all processed inline, only extracted fields stored.

**Storage implications:** Full README cache at 248K repos × ~4KB average ≈ 1 GB. Database is currently 4.24 GB with ~5.8 GB headroom on the Render Standard plan (estimated 10 GB limit).

### Database Schema

**Current size:** 4.24 GB. `ai_repos` alone is 2.65 GB (63%) due to inline embeddings (vector 256 + vector 1536), readme_cache, and ai_summary columns.

**sync_log** (865 rows): 7 columns — `id`, `sync_type` (varchar 50), `status` (varchar 20), `records_written` (int), `error_message` (text), `started_at`, `finished_at`. Tracks 59 distinct sync types at run level only. No item-level tracking.

**Enrichment outputs:**
- `ai_repos` inline: `ai_summary` (5.6% coverage), `use_this_if` (0.06%), `problem_domains` (0.06%), `readme_cache` (0.06%)
- `comparison_sentences`: 11,842 rows (5,830 with sentences)
- `repo_briefs`: 0 rows (empty, never populated)
- `project_briefs`: 96 rows
- `domain_briefs`: 0 rows (empty)
- `landscape_briefs`: 0 rows (empty)
- `content_budget`: 10,071 rows (allocation-driven, truncated and rewritten each run)

**No task/job tracking table exists.** Implicit state via `*_at` timestamp columns on `ai_repos` (`ai_summary_at`, `readme_cached_at`, `downloads_checked_at`, `deps_fetched_at`, `commits_checked_at`). No retry counting, no error recording at item level.

**Top tables by size:** ai_repos (2,653 MB), quality_snapshots (349 MB), hf_datasets (276 MB), ai_repo_snapshots (234 MB), releases (147 MB), public_apis (125 MB), hf_models (104 MB).

### Render Deployment

**5 services + 2 databases:**

| Service | Type | Plan | Cost |
|---------|------|------|------|
| pt-edge | web | standard ($25) | Main API + static site generation at startup |
| pt-edge-umami | web | starter ($7) | Analytics dashboard |
| pt-edge-daily-ingest-worker | worker | standard ($25) | Persistent worker, self-redeploying |
| pt-edge-ai-repos-weekly | cron | free | Saturday 12:00 UTC |
| pt-edge-weekly | cron | free | Sunday 03:00 UTC |
| pt-edge-db | postgres | basic-1gb ($20) | Main database |
| umami-db | postgres | basic-256mb ($7) | Umami analytics |
| **Total** | | | **~$84/mo fixed** |

**Standard plan:** 2 GB RAM, 1 CPU. No process timeout on workers (the whole point). Cron jobs have a hard 12-hour timeout.

**Variable costs:** Gemini (~$5-20/mo), OpenAI embeddings (~$5-15/mo). Total estimated: ~$94-119/mo.

**Key constraint:** The worker already exists as a persistent process. The new architecture doesn't need a new service type — it replaces the worker's internal logic while keeping the same Render service.

### External APIs: Complete Inventory

**22 integrations** (20 active, 1 removed, 1 stub):

| API | Auth | Rate Limit | Cost | Handling |
|-----|------|-----------|------|----------|
| GitHub REST | `GITHUB_TOKEN` | 5,000/hr | Free | Varies by module (see above) |
| GitHub GraphQL | `GITHUB_TOKEN` | 5,000 pts/hr | Free | Pre-flight check |
| GitHub Search | `GITHUB_TOKEN` | 30/min | Free | CallCounter + Retry-After |
| Gemini | `GEMINI_API_KEY` | 800 RPM (configured) | **Paid** | Token bucket + 429 backoff |
| OpenAI Embeddings | `OPENAI_API_KEY` | 400 RPM (configured) | **Paid** | Token bucket |
| PyPI/PyPIStats | None | Undocumented | Free | 1.0s sleep, Semaphore(2-3) |
| npm Registry | None | Undocumented | Free | 0.3-0.5s sleep, Semaphore(3) |
| Docker Hub | None | 100-200 pulls/6hr | Free | 0.5s sleep, Semaphore(3) |
| HuggingFace Hub | None | 500 req/300s | Free | 0.5-0.6s sleep, Semaphore(3) |
| HN Algolia | None | 10,000/hr | Free | 1.0s sleep, Semaphore(2) |
| V2EX | `V2EX_TOKEN` (optional) | 120/hr | Free | 6.0s between requests |
| VS Code Marketplace | None | Undocumented | Free | 0.5s sleep, Semaphore(3) |
| Google Search Console | OAuth2 (3 env vars) | 1,200/min | Free | Sequential, 3 calls/run |
| Umami | Direct DB (`UMAMI_DATABASE_URL`) | N/A | Included | SQL query |
| OpenRouter | None | Undocumented | Free | Single GET/run |
| APIs.guru | None | N/A | Free | Single GET/run |
| crates.io | None (User-Agent) | 1 req/s | Free | 1.0s sleep, Semaphore(1) |
| Render API | `RENDER_API_KEY` | N/A | Free | Single POST for deploy |
| RSS feeds (8 sources) | None | N/A | Free | Sequential via feedparser |
| HuggingFace Hub (push) | `HF_TOKEN` (optional) | N/A | Free | Single push/run |
| ~~Semantic Scholar~~ | ~~Optional key~~ | ~~Shared 1K/s pool~~ | Free | **Removed 2026-04-04** |
| Reddit | Would need OAuth | N/A | Free | **Stub only, not implemented** |

### Materialized Views

**35 MVs** (not 47 as previously estimated), all defined in `VIEWS_IN_ORDER` in `app/views/refresh.py`.

**Refresh time:** 1-3 minutes for all 35. Not a bottleneck.

**Dependency graph:**
```
Base (7):     mv_dep_resolution, mv_momentum, mv_hype_ratio, mv_lab_velocity,
              mv_project_tier, mv_velocity, mv_download_trends

Derived (3):  mv_lifecycle (← mv_momentum)
              mv_traction_score (← mv_velocity, mv_download_trends)
              mv_project_summary (← 7 base MVs)

Usage (2):    mv_usage_sessions → mv_usage_daily_summary

Standalone:   mv_ai_repo_ecosystem, mv_nucleation_project, mv_nucleation_category,
              mv_access_bot_demand

Quality (18): One per domain (mv_mcp_quality, mv_agents_quality, ... mv_perception_quality)
              All standalone — query ai_repos + dep tables directly

Aggregation:  mv_allocation_scores (← all quality MVs + snapshots + gsc + umami)
```

**For the static site:** Only the 18 quality MVs are needed. The other 17 serve the API/MCP tools.

**For the scheduler:** `mv_allocation_scores` feeds `content_budget`, which drives task generation for enrichment pipelines. This is a real dependency: data ingestion → MV refresh → content_budget → enrichment tasks.

### Static Site Deploy

**Chain:** ingest worker → run_all() → MV refresh → POST to `RENDER_DEPLOY_HOOK_URL` → web service redeploy → `start.sh` → `generate_site.py` (all 18 domains + portal + deep dives) → uvicorn starts.

**Duration:** ~5 minutes for site generation, plus Docker build + health check.

**Cannot be incremental.** Render's ephemeral filesystem means the entire site regenerates from scratch on every deploy. No CDN or persistent storage layer.

**Fragile under load:** Site generation queries the DB heavily. If other DB-heavy operations run concurrently, queries can time out and Render cancels the deploy ("No open ports detected" within 5-minute timeout).

---

## Design Decisions (Resolved)

### Task granularity

Bulk ingestion jobs (Phase 1-2) stay as coarse-grained tasks — one task per source ("refresh all GitHub metadata"). Enrichment jobs are fine-grained — one task per repo. MV refresh is one task for all 35 views (1-3 minutes, not worth splitting). Batch LLM tasks (subcategory 30/batch, HN match 20/batch) are modelled as individual tasks in the queue; the worker claims N at once, executes as a batch, marks all N individually.

### Budget mechanics

GitHub: hourly budget in `resource_budgets` table (4,500/hr, 90% safety margin). Gemini: the existing token-bucket rate limiter in `rate_limit.py` handles per-minute pacing; the `resource_budgets` row (48,000/hr) is a coarse gate. Dollar spend: tracked via `estimated_cost_usd` on tasks for visibility, but not enforced as a gate (current spend ~$3-6/day is low risk).

### content_budget dependency

The scheduler reads the existing `content_budget` table (computed by runner.py's MV refresh → `compute_and_write_budget()` flow). The scheduler checks `content_budget.computed_at` freshness and only creates enrichment tasks when the budget is current. In Wave 5, MV refresh and content_budget become task-driven.

### Coexistence during migration

Safe: most jobs use `ON CONFLICT` upserts and `WHERE column IS NULL` guards. The advisory lock prevents concurrent `run_all()` but doesn't block individual task claims. Jobs are removed from `runner.py` as each task type is validated.

### Table bloat

Retention policy: completed tasks deleted after 7 days, failed after 30 days. At 25K tasks/day, peak table size is ~175K rows — trivially small for Postgres.

### Single worker vs. multiple

Architecture supports multiple workers from day one via `FOR UPDATE SKIP LOCKED`. Currently running one worker on the Render standard plan.

---

## Migration Roadmap

Each wave ports task types from `runner.py` to the task queue. The old pipeline shrinks as the new worker grows. At no point does the system break.

### Wave 1: Foundation + `fetch_readme` + `enrich_summary`

**Status: implemented** (migration 079, `app/queue/`)

| Task Type | Kind | Priority | Resource | Replaces |
|-----------|------|----------|----------|----------|
| `fetch_readme` | Fetch | 8 | `github_api` | README fetching inside `ai_repo_summaries.py` |
| `enrich_summary` | Enrich | 9 | `gemini` | `generate_ai_summaries()` (runner.py:358-364) |

**New tables:** `tasks`, `resource_budgets`, `raw_cache`
**Scheduler rules:** create `fetch_readme` for repos in `content_budget` with no fresh `raw_cache(github_readme)` entry; create `enrich_summary` for repos with cached README but no summary
**Removes from runner.py:** `ai_summaries` job

### Wave 2: Remaining high-value enrichment

| Task Type | Kind | Priority | Resource | Replaces | Details |
|-----------|------|----------|----------|----------|---------|
| `enrich_comparison` | Enrich | 9 | `gemini` | `generate_comparison_sentences()` (runner.py:366-371) | Reads two repo summaries, writes `comparison_sentences.sentence`. Up to 2,000/day, 150 max_tokens |
| `enrich_repo_brief` | Enrich | 9 | `gemini` | `generate_repo_briefs()` (runner.py:373-379) | Reads repo summary + metrics, writes `repo_briefs`. Budget-driven, 4096 max_tokens, batch of 10 |

**Scheduler rules:** create tasks for pairs with `sentence IS NULL` / repos with no `repo_briefs` row, gated by `content_budget`

### Wave 3: Project/domain/landscape briefs

| Task Type | Kind | Priority | Resource | Replaces | Details |
|-----------|------|----------|----------|----------|---------|
| `enrich_project_brief` | Enrich | 7 | `gemini` | `generate_project_briefs()` (runner.py:381-386) | Max 100/run, 4096 max_tokens, batch of 10. Depends on repo_briefs existing |
| `enrich_domain_brief` | Enrich | 3 | `gemini` | `generate_domain_briefs()` (runner.py:405-411) | ~17 domains, 2048 max_tokens. Scheduler creates when brief >7 days old |
| `enrich_landscape_brief` | Enrich | 3 | `gemini` | `generate_landscape_briefs()` (runner.py:413-419) | ~10 layers, 2048 max_tokens. Scheduler creates when brief >7 days old |

**Kills the "Sunday" concept.** These become staleness-driven, not day-of-week-driven.

### Wave 4: GitHub-heavy tasks

| Task Type | Kind | Priority | Resource | Replaces | Details |
|-----------|------|----------|----------|----------|---------|
| `backfill_created_at` | Fetch | 2 | `github_api` | `ingest_ai_repo_created_at()` (runner.py:449-458) | One task per repo where `created_at IS NULL`. At priority 2, naturally yields to higher-priority GitHub work |
| `fetch_github` | Fetch | 7 | `github_api` | `ingest_github()` (runner.py:157-158) | Coarse-grained: refreshes all 800 projects. Scheduler creates when last `sync_log(github)` >24h old |
| `fetch_releases` | Fetch | 6 | `github_api` | `ingest_releases()` (runner.py:183) | ~800 GitHub calls. Coarse-grained |
| `enrich_release_summary` | Enrich | 6 | `gemini` | Release summarisation inside `releases.py` | Reads `releases.body`, writes `releases.summary` |

### Wave 5: Infrastructure tasks

| Task Type | Kind | Priority | Resource | Replaces | Details |
|-----------|------|----------|----------|----------|---------|
| `compute_mv_refresh` | Compute | 5 | none | `refresh_all_views()` (runner.py:342) | Single task, all 35 MVs (1-3 min). Scheduler creates when last refresh >6h old |
| `compute_content_budget` | Compute | 5 | none | `compute_and_write_budget()` (runner.py:350-356) | Depends on MV refresh. Scheduler creates when `computed_at` is stale |
| `export_static_site` | Export | 4 | none | Deploy hook POST (runner.py:436-447) | Scheduler creates after MV refresh + enrichment batch |
| `compute_embeddings` | Enrich | 5 | `openai` | `backfill_embeddings` (runner.py:338) | Processes rows where `embedding IS NULL` |

### Wave 6: Batch LLM classification tasks

| Task Type | Kind | Priority | Resource | Replaces | Details |
|-----------|------|----------|----------|----------|---------|
| `enrich_subcategory` | Enrich | 4 | `gemini` | `classify_subcategory_llm()` (runner.py:267) | Batch of 30 per LLM call. Worker claims 30 tasks, executes as batch |
| `enrich_stack_layer` | Enrich | 4 | `gemini` | `classify_stack_layers()` (runner.py:271) | Batch of 30 |
| `enrich_hn_match` | Enrich | 4 | `gemini` | `match_hn_posts_llm()` (runner.py:260) | Batch of 20 |
| `enrich_package_detect` | Enrich | 4 | `gemini` | `detect_packages_llm()` (runner.py:182) | Batch of 20. Followed by `fetch_package_verify` to verify predictions |

### Wave 7: Data ingestion

| Task Type | Kind | Priority | Resource | Replaces |
|-----------|------|----------|----------|----------|
| `fetch_downloads` | Fetch | 7 | none | `ingest_downloads()` (runner.py:158). Coarse-grained |
| `fetch_dockerhub` | Fetch | 7 | none | `ingest_dockerhub()` (runner.py:159). Coarse-grained |
| `fetch_vscode` | Fetch | 7 | none | `ingest_vscode()` (runner.py:160). Coarse-grained |
| `fetch_huggingface` | Fetch | 7 | none | `ingest_huggingface()` (runner.py:161). Coarse-grained |
| `fetch_hn` | Fetch | 6 | none | `ingest_hn()` (runner.py:162). Forum scraping |
| `fetch_v2ex` | Fetch | 6 | none | `ingest_v2ex()` (runner.py:163). Forum scraping |
| `import_gsc` | Fetch | 6 | none | `ingest_gsc()` (runner.py:192). Analytics ETL |
| `import_umami` | Fetch | 6 | none | `ingest_umami()` (runner.py:195). Analytics ETL |
| `fetch_hf_datasets` | Fetch | 5 | none | `ingest_hf_datasets()` (runner.py:167). Large catalog |
| `fetch_hf_models` | Fetch | 5 | none | `ingest_hf_models()` (runner.py:168). Large catalog |
| `discover_ai_repos` | Fetch | 4 | `github_api` | Saturday cron `ingest_ai_repos.py`. Scheduler creates when last run >7 days old |
| `compute_structural` | Compute | 3 | none | Sunday cron `weekly_structural.py`. Scheduler creates when last run >7 days old |

### Wave 8: Kill the old system

When all 49 jobs are ported:

- Delete `app/ingest/runner.py`
- Delete `scripts/ingest_all.py`
- Simplify `scripts/ingest_worker.py` to just the task queue loop (remove legacy subprocess spawning)
- Delete Saturday cron job `pt-edge-ai-repos-weekly` from `render.yaml`
- Delete Sunday cron job `pt-edge-weekly` from `render.yaml`
- Remove advisory lock logic (tasks use `FOR UPDATE SKIP LOCKED` instead)
- Deprecate `sync_log` — the `tasks` table replaces it for operational tracking
