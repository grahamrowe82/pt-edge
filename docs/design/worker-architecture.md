# Worker Architecture

*Last updated: 5 April 2026*

## How It Works

Three layers, hard boundaries between them.

### Layer 1: Work Queue (Postgres `tasks` table)

Every unit of work is a row. The scheduler creates rows, the worker claims and executes them. Tasks have a priority (1-10, higher = first), a resource type (github_api, gemini, openai, or none), and a state (pending → claimed → done/failed).

The claim query uses `FOR UPDATE SKIP LOCKED` — safe for multiple workers, no contention.

### Layer 2: Worker Loop (`app/queue/worker.py`)

A stateless async loop: claim the highest-priority task whose resource budget allows it, execute the handler, mark done or requeue on failure. Sleeps 5 seconds when idle. Runs continuously on a Render worker service.

If the worker crashes, claimed tasks' heartbeats go stale and the scheduler's reaper returns them to pending after 10 minutes.

### Layer 3: Scheduler (`app/queue/scheduler.py`)

Runs every 15 minutes as an asyncio coroutine inside the worker process. Creates tasks based on staleness (sync_log entries, content_budget freshness, brief age). Never executes work. Also handles housekeeping: stale task reaping, budget period resets, old task cleanup (done >7 days, failed >30 days).

### Separation of Concerns

Every task is strictly one kind:
- **Fetch** — external API → database (no processing)
- **Enrich** — database → LLM → database (no external API other than LLM)
- **Compute** — database → database (no external APIs)
- **Export** — database → external destination

The `raw_cache` table is the interface between Fetch and Enrich tasks. They communicate through data, not code.

---

## All Task Types

### Priority 9 — Revenue-critical enrichment (budget-gated)

| Task | Kind | Resource | Handler | Granularity |
|------|------|----------|---------|-------------|
| `enrich_summary` | Enrich | gemini | `enrich_summary.py` | Per repo |
| `enrich_comparison` | Enrich | gemini | `enrich_comparison.py` | Per pair |
| `enrich_repo_brief` | Enrich | gemini | `enrich_repo_brief.py` | Per repo |

### Priority 8 — README caching (budget-gated)

| Task | Kind | Resource | Handler | Granularity |
|------|------|----------|---------|-------------|
| `fetch_readme` | Fetch | github_api | `fetch_readme.py` | Per repo |

### Priority 7 — Core data freshness (24h staleness)

| Task | Kind | Resource | Handler | Granularity |
|------|------|----------|---------|-------------|
| `fetch_github` | Fetch | github_api | `fetch_github.py` | Coarse (all projects) |
| `fetch_downloads` | Fetch | none | `fetch_data.py` | Coarse |
| `fetch_dockerhub` | Fetch | none | `fetch_data.py` | Coarse |
| `fetch_vscode` | Fetch | none | `fetch_data.py` | Coarse |
| `fetch_huggingface` | Fetch | none | `fetch_data.py` | Coarse |
| `fetch_trending` | Fetch | none | `fetch_data.py` | Coarse |
| `enrich_project_brief` | Enrich | gemini | `enrich_project_brief.py` | Coarse (up to 100) |

### Priority 6 — Analytics & content sources (24h staleness)

| Task | Kind | Resource | Handler | Granularity |
|------|------|----------|---------|-------------|
| `fetch_releases` | Fetch | github_api | `fetch_releases.py` | Coarse |
| `fetch_hn` | Fetch | none | `fetch_data.py` | Coarse |
| `fetch_v2ex` | Fetch | none | `fetch_data.py` | Coarse |
| `fetch_newsletters` | Fetch | none | `fetch_data.py` | Coarse |
| `import_gsc` | Fetch | none | `compute_post_process.py` | Coarse |
| `import_umami` | Fetch | none | `compute_post_process.py` | Coarse |

### Priority 5 — Infrastructure & secondary data (24h staleness)

| Task | Kind | Resource | Handler | Granularity |
|------|------|----------|---------|-------------|
| `compute_mv_refresh` | Compute | none | `compute_mv_refresh.py` | Coarse (all 35 MVs) |
| `compute_content_budget` | Compute | none | `compute_content_budget.py` | Coarse |
| `compute_embeddings` | Enrich | openai | `compute_embeddings.py` | Coarse (all tables) |
| `fetch_hf_datasets` | Fetch | none | `fetch_data.py` | Coarse |
| `fetch_hf_models` | Fetch | none | `fetch_data.py` | Coarse |
| `fetch_public_apis` | Fetch | none | `fetch_data.py` | Coarse |
| `fetch_api_specs` | Fetch | none | `fetch_data.py` | Coarse |
| `fetch_package_deps` | Fetch | none | `fetch_data.py` | Coarse |
| `compute_dep_velocity` | Compute | none | `fetch_data.py` | Coarse |
| `fetch_builder_tools` | Fetch | none | `fetch_data.py` | Coarse |
| `fetch_npm_mcp` | Fetch | none | `fetch_data.py` | Coarse |
| `fetch_ai_repo_downloads` | Fetch | none | `fetch_data.py` | Coarse |
| `fetch_ai_repo_commits` | Fetch | github_api | `fetch_data.py` | Coarse |
| `fetch_models` | Fetch | none | `fetch_data.py` | Coarse |
| `compute_coview` | Compute | none | `compute_post_process.py` | Coarse |
| `compute_hn_backfill` | Compute | none | `compute_post_process.py` | Coarse |
| `compute_hn_lab_backfill` | Compute | none | `compute_post_process.py` | Coarse |
| `compute_v2ex_lab_backfill` | Compute | none | `compute_post_process.py` | Coarse |
| `compute_domain_reassign` | Compute | none | `compute_post_process.py` | Coarse |
| `compute_project_linking` | Compute | none | `compute_post_process.py` | Coarse |
| `compute_briefing_refresh` | Compute | none | `compute_post_process.py` | Coarse |

### Priority 4 — Classification & discovery

| Task | Kind | Resource | Handler | Granularity | Staleness |
|------|------|----------|---------|-------------|-----------|
| `enrich_subcategory` | Enrich | gemini | `enrich_subcategory.py` | Coarse | 24h |
| `enrich_stack_layer` | Enrich | gemini | `enrich_stack_layer.py` | Coarse | 24h |
| `enrich_hn_match` | Enrich | gemini | `enrich_hn_match.py` | Coarse | 24h |
| `enrich_package_detect` | Enrich | gemini | `enrich_package_detect.py` | Coarse | 24h |
| `export_static_site` | Export | none | `export_static_site.py` | Coarse | After MV refresh |
| `export_dataset` | Export | none | `compute_post_process.py` | Coarse | 24h |
| `fetch_candidates` | Fetch | none | `fetch_data.py` | Coarse | 24h |
| `fetch_candidate_watchlist` | Fetch | none | `fetch_data.py` | Coarse | 24h |
| `discover_ai_repos` | Fetch | github_api | `compute_post_process.py` | Coarse | 7 days |

### Priority 3 — Periodic briefs & structural

| Task | Kind | Resource | Handler | Granularity | Staleness |
|------|------|----------|---------|-------------|-----------|
| `enrich_domain_brief` | Enrich | gemini | `enrich_domain_brief.py` | Per domain | 7 days |
| `enrich_landscape_brief` | Enrich | gemini | `enrich_landscape_brief.py` | Coarse | 7 days |
| `compute_structural` | Compute | none | `compute_post_process.py` | Coarse | 7 days |

### Priority 2 — Backfill

| Task | Kind | Resource | Handler | Granularity |
|------|------|----------|---------|-------------|
| `backfill_created_at` | Fetch | github_api | `backfill_created_at.py` | Per repo |

---

## Resource Budgets

| Resource | Budget | Period | Purpose |
|----------|--------|--------|---------|
| `github_api` | 4,500/hr | 1 hour | 90% of GitHub's 5,000/hr REST limit |
| `gemini` | 48,000/hr | 1 hour | Coarse gate (token bucket handles per-minute pacing) |
| `openai` | 24,000/hr | 1 hour | Embeddings |

The worker checks the budget before claiming a task. If the budget for a resource is exhausted, tasks requiring that resource are skipped and the worker claims something else.

---

## Key Dependencies

```
Data ingestion (fetch_*)
  → compute_embeddings
    → compute_mv_refresh
      → compute_content_budget
        → Budget-gated enrichment (fetch_readme, enrich_summary,
           enrich_comparison, enrich_repo_brief, enrich_project_brief)
          → export_static_site
```

Domain briefs, landscape briefs, and backfills have no dependency chain — they're staleness-driven and run whenever the queue is quiet.

---

## How to Operate

### Check system health

```sql
-- What's running right now?
SELECT task_type, state, count(*) FROM tasks GROUP BY 1, 2 ORDER BY 1, 2;

-- How fast is work progressing?
SELECT task_type, date_trunc('hour', completed_at) AS hour, count(*)
FROM tasks WHERE state = 'done'
GROUP BY 1, 2 ORDER BY 2 DESC, 1 LIMIT 30;

-- What's stuck? (claimed but no heartbeat in 10+ min)
SELECT id, task_type, subject_id, claimed_at, heartbeat_at
FROM tasks WHERE state = 'claimed'
AND heartbeat_at < now() - interval '10 minutes';

-- What failed and why?
SELECT task_type, LEFT(error_message, 150), count(*)
FROM tasks WHERE state = 'failed'
GROUP BY 1, 2 ORDER BY 3 DESC;

-- Resource budget status
SELECT * FROM resource_budgets;

-- Is content_budget fresh? (gates enrichment tasks)
SELECT computed_at FROM content_budget LIMIT 1;
```

### Debug a specific failure

```sql
SELECT id, task_type, subject_id, error_message, retry_count, created_at
FROM tasks WHERE state = 'failed' AND task_type = 'enrich_domain_brief'
ORDER BY created_at DESC;
```

### Add a new task type

1. Create handler in `app/queue/handlers/` — async function taking `task: dict`, returning `dict`
2. Register in `app/queue/handlers/__init__.py`
3. Add scheduling rule in `app/queue/scheduler.py` (use `_schedule_coarse_task()` for sync_log-staleness pattern)
4. Test: manually insert a task and verify the worker processes it

### Trigger a manual redeploy

```bash
curl -s -X POST "https://api.render.com/v1/services/srv-d77c6s14tr6s739h798g/deploys" \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"clearCache":"do_not_clear"}'
```

---

## Deployment

| Service | Type | Plan | What it does |
|---------|------|------|-------------|
| `pt-edge` | web | standard ($25) | API + static site generation at startup |
| `pt-edge-daily-ingest-worker` | worker | standard ($25) | Task queue worker + scheduler |
| `pt-edge-umami` | web | starter ($7) | Analytics dashboard |
| `pt-edge-db` | postgres | basic-1gb ($20) | Main database |
| `umami-db` | postgres | basic-256mb ($7) | Umami analytics |

Auto-deploy is disabled on the worker. It self-deploys once per day via the Render API to pick up code changes.

---

## File Map

```
app/queue/
├── __init__.py
├── worker.py              # Claim/execute/complete loop
├── scheduler.py           # Creates tasks, housekeeping
└── handlers/
    ├── __init__.py         # TASK_HANDLERS registry (51 handlers)
    ├── fetch_readme.py     # Per-repo README fetch → raw_cache
    ├── fetch_github.py     # Coarse: all project metadata
    ├── fetch_releases.py   # Coarse: releases + LLM summaries
    ├── fetch_data.py       # 21 coarse data ingestion handlers
    ├── enrich_summary.py   # Per-repo problem brief via Gemini
    ├── enrich_comparison.py    # Per-pair comparison sentence
    ├── enrich_repo_brief.py    # Per-repo brief via Gemini
    ├── enrich_project_brief.py # Coarse: project briefs (batch 10)
    ├── enrich_domain_brief.py  # Per-domain landscape brief
    ├── enrich_landscape_brief.py # Coarse: all ecosystem layers
    ├── enrich_subcategory.py   # Coarse: regex + LLM classification
    ├── enrich_stack_layer.py   # Coarse: stack layer classification
    ├── enrich_hn_match.py      # Coarse: HN post matching
    ├── enrich_package_detect.py # Coarse: package name detection
    ├── backfill_created_at.py  # Per-repo created_at from GitHub
    ├── compute_mv_refresh.py   # Coarse: refresh all 35 MVs
    ├── compute_content_budget.py # Coarse: recompute allocation
    ├── compute_embeddings.py   # Coarse: backfill embeddings
    ├── compute_post_process.py # 12 analytics/post-processing handlers
    └── export_static_site.py   # Trigger Render deploy webhook
```
