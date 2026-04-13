# The *-Edge Engineering Playbook

A prescriptive guide for engineers building bio-edge, cyber-edge, and future *-edge sites based on the PT-Edge architecture. Every lesson here was learned through production incidents, wasted API budget, silent failures, or multi-hour debugging sessions. This is not theory. This is what actually happened and what you should do instead.

**Audience**: Engineers standing up a new *-edge instance from the PT-Edge codebase.

**How to read this**: Each section follows the same structure: what to do, why, and (where relevant) a code example. Chapters are ordered by build sequence -- you will encounter these problems roughly in this order.

---

## Chapter 1: Foundation

### Use Postgres for Everything

Do not introduce Redis, RabbitMQ, or any external queue/cache service. Postgres handles the task queue (FOR UPDATE SKIP LOCKED), resource budgets (single table with atomic operations), materialized views (precomputed analytics), raw_cache (HTTP response storage), and redirect mappings.

**Why**: Every additional service doubles your ops burden. A single managed Postgres instance on Render gives you transactional guarantees across all these subsystems. When the queue drains and a budget updates and a cache writes all need to be consistent, a single database makes that trivial. Separate systems make it an unsolvable distributed consistency problem.

**The tradeoff is real**: You get simplicity at the cost of capacity. A 1GB Postgres instance is the ceiling for all your workloads simultaneously. This constraint is manageable if you follow the rules in this chapter. It is catastrophic if you don't.

### FastAPI + StaticFiles: Generate at Deploy, Serve Static

The web service generates all HTML at deploy time and serves it as static files. Runtime requests never touch the database for page rendering. Target 10-20ms response times for all directory pages.

**What to do**: Use FastAPI's `StaticFiles` mount. Generate all HTML into a `site/` directory during startup. The only runtime DB queries are access logging (buffered, background) and API/MCP endpoints.

**Why**: A 220K-page directory site cannot afford per-request DB queries. Even 50ms per query times 100 concurrent requests would peg the database CPU. Static files eliminate this entire class of problem.

### Docker: Clean Site Every Deploy

The Dockerfile copies the codebase, and `start.sh` generates the site fresh before starting uvicorn. There is no persistent `site/` directory. Render's filesystem is ephemeral -- everything written at runtime is lost on the next deploy.

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y libpq-dev gcc git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

COPY scripts/start.sh /start.sh
RUN chmod +x /start.sh

CMD ["/start.sh"]
```

**What `start.sh` does**: Generates every domain site sequentially (30 calls to `generate_site.py`), then the portal homepage, then deep dive pages, then redirect pages, then `exec uvicorn`. The redirect generation must run last because it checks whether a real page already exists at each path.

```sh
#!/bin/sh
set -e

echo "Generating static directory sites..."
python scripts/generate_site.py --domain mcp --output-dir site
python scripts/generate_site.py --domain agents --output-dir site/agents
# ... 28 more domains ...

echo "Generating portal homepage..."
python scripts/generate_site.py --portal --output-dir site

echo "Generating deep dive pages..."
python scripts/generate_deep_dives.py --output-dir site

echo "Generating redirect pages..."
python scripts/generate_redirects.py --output-dir site

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

**Why redirect generation runs last**: If you generate redirects before real pages, you might write a redirect file at a path where a real page should exist. When the real page generator runs, it overwrites the redirect. If you reverse the order, the redirect generator can check `os.path.exists(old_path)` and skip paths where real content lives.

### 1GB Render Postgres: Know Your Limits

The database has 1GB RAM, 0.5 CPU, and ~97 max connections. Memory at ceiling is normal -- Postgres uses all available RAM for shared buffers and page cache. Monitor CPU, not memory.

**Query sizing rules**:
- Result < 50MB: safe to run anytime
- Result 50-200MB: run alone, no concurrent operations
- Result > 200MB: do not do it. Batch by domain, by score range, or by LIMIT/OFFSET

**The math**: `ai_repos` has 220K+ rows. Each 1536-dimension embedding is ~6KB as text. Fetching all embeddings = 1.3GB -- larger than the database's entire RAM. If you need all embeddings, process per-domain (5K-70K per query, not 220K at once).

**CPU is the constraint, not memory**: Materialized view refreshes join `ai_repos` (220K rows) with `package_deps` and compute scoring CTEs. A single refresh takes 2-5 minutes. Running all 30 views sequentially takes 30-60 minutes. Refresh views serially, never concurrently -- exclusive locks cascade into multi-hour pile-ups. Don't refresh views unless the underlying data has actually changed -- the worker should check whether ingest has run since the last refresh before triggering a new one.

### Database Safety: The Non-Obvious Rules

**Never run queries in the background**. PostgreSQL does not terminate a query when the client disconnects -- it keeps running until it completes or is explicitly killed via `pg_terminate_backend()`. A background process that fails leaves an orphaned server-side query consuming CPU and memory indefinitely. Always run database-touching commands in the foreground with explicit timeouts.

**Killing local psql does not kill the server-side query**:

```sql
-- See what's running
SELECT pid, state, LEFT(query, 80) as query, now() - query_start as duration
FROM pg_stat_activity
WHERE state = 'active' AND pid <> pg_backend_pid();

-- Kill specific query
SELECT pg_terminate_backend(<pid>);
```

**Bulk UPDATEs on 100K+ rows trigger autovacuum** that consumes CPU/memory for 15-30 minutes afterward. Plan for this. Don't deploy while autovacuum is running -- `start.sh` queries will hang, uvicorn never starts, and Render cancels the deploy with "No open ports detected."

**JSONB casting with SQLAlchemy**: Never use `:param::jsonb`. SQLAlchemy's `text()` interprets `:` as a bind parameter marker. Use `CAST(:param AS jsonb)` with `json.dumps()` on the Python side. This one caused an entire pipeline to fail silently for days -- tasks completed their work but failed on `mark_done` because the final state update used `::jsonb` casting.

```python
# BAD: SQLAlchemy interprets ::jsonb as bind params
conn.execute(text("UPDATE t SET data = :val::jsonb"), {"val": data})

# GOOD: explicit CAST
conn.execute(
    text("UPDATE t SET data = CAST(:val AS jsonb)"),
    {"val": json.dumps(data)}
)
```

---

## Chapter 2: Data Ingestion

### GitHub API: Three Independent Rate Limits

GitHub has three separate APIs with independent rate limits:
- **REST API** (5,000/hr with PAT, 7,400/hr with GitHub App)
- **Search API** (30 requests/minute, separate from REST)
- **GraphQL API** (5,000 points/hr, separate from REST)

**What to do**: Model these as separate resource types in your budget system. Use GitHub App authentication to get an isolated 7,400/hr REST limit that doesn't compete with your PAT's 5,000/hr.

**Why**: A single "github" resource slot with 4,500 pending `fetch_readme` tasks starved discovery and commits for 3+ days. The README backfill consumed every REST API call, and no other GitHub-dependent work could run. Splitting into `github_api`, `github_search`, and `github_graphql` with separate budgets fixed this immediately.

### Package Registry Name Normalization

Normalize package names to lowercase-with-hyphens before any JOIN operation. PyPI treats `My_Package`, `my-package`, and `my.package` as the same thing. npm does not.

**What to do**: Normalize on ingest, store the normalized form, and join on normalized names. Never LIKE-join against raw package names.

**Why**: LIKE pattern joins against large tables are O(n*m). A query like `path LIKE '%/servers/' || full_name || '/%'` on 475K x 220K rows pegged the CPU for 40 minutes. Parse once, store, join with equality.

### raw_cache as a Hard Interface

Fetching and enrichment are separate operations connected by `raw_cache`. A fetch task writes raw data (README text, API response) to `raw_cache`. An enrich task reads from `raw_cache` and calls the LLM.

```
fetch_readme → raw_cache (source='github_readme', subject_id=full_name)
                    ↓
enrich_summary → reads raw_cache → calls Gemini → writes ai_repos
```

**What to do**: Never let an enrichment task call an external API. Never let a fetch task call an LLM. The cache is the interface between them.

**Why**: If the LLM fails, the README is still cached for retry. If you combine fetch and enrich in one task, an LLM failure means re-fetching the README (another API call, another rate-limit hit). The hard interface guarantees that fetched data survives LLM failures.

### Follow Redirects and Detect Renames

GitHub repositories can be renamed. The old URL redirects to the new one. But your database stores the old name, and every task that references that name either fails or operates on stale data.

**What to do**: Use `follow_redirects=True` on all GitHub HTTP calls. After following a redirect, compare the final URL's repo name to your stored name. If they differ, update `ai_repos.full_name` and record the old name in your redirects table.

**Why**: 298 repos had been renamed, generating 7,524 failed tasks. Each renamed repo queued tasks against a name that would 404, fail, retry, and fail again -- burning retries and API calls on something that could never succeed.

### Save Expensive Outputs Before Applying

Any pipeline involving LLM calls, embedding generation, or clustering must write results to a file before writing to the database. Discovery and application must be separate steps.

```bash
# GOOD: save then apply
python scripts/discover_categories.py --all-domains --save
python scripts/discover_categories.py --apply-from data/categories.json

# BAD: compute and apply in one shot
python scripts/discover_categories.py --all-domains --apply
```

**Why**: If the apply step fails (bad data, schema mismatch, connection timeout), you can re-run it from the saved file instead of re-running the entire LLM pipeline. An embedding batch that costs $15 and takes 2 hours should never need to run twice because of a database error.

---

## Chapter 3: Domain Architecture

### Choose Domains by Tool-Selection Intent

Choose your domain taxonomy by asking "where do practitioners ask 'which tool should I use?'" -- not "which fields have the most repos."

**What we did wrong first**: Included 8 academic domains (reinforcement learning, robotics, graph neural networks) because they had high repo counts. Nobody searches "which RL library should I use?" the way they search "which MCP server handles Postgres?" Those academic domains generated pages that got zero impressions.

**What we did instead**: Dropped academic domains. Kept commercially relevant tool-selection domains: MCP, agents, RAG, AI coding, voice AI, diffusion, vector databases, embeddings, prompt engineering. Each domain must pass the test: "Would a practitioner compare tools in this category before adopting one?"

### Embedding-Based Domain Reassignment

Repos get misclassified on initial ingest. Run daily reassignment using cosine similarity to domain centroids.

```python
BATCH_SIZE = 2000
BATCHES_PER_RUN = 25
MIN_IMPROVEMENT = 0.05

# For each repo: compute similarity to all domain centroids
sims = centroid_matrix @ vec  # (n_domains,) vector of similarities
current_sim = sims[current_idx]
best_sim = sims[best_idx]

# Only reassign if the improvement is meaningful
if best_idx != current_idx and (best_sim - current_sim) >= MIN_IMPROVEMENT:
    reassign(repo_id, new_domain)
```

**The MIN_IMPROVEMENT threshold prevents flip-flopping**. Without it, a repo sitting equidistant between two domains bounces back and forth on every run, generating a new redirect each time. 0.05 was chosen empirically -- it means the repo must be meaningfully closer to the new domain, not just slightly closer due to centroid drift.

**Process by stars descending with a rolling offset**: High-star repos are more visible and more important to classify correctly. The offset advances daily via `sync_log`, so over multiple days you sweep the entire table.

### Catch-All Domains Accumulate Debt

If you have a domain like `ml-frameworks` that absorbs everything that doesn't fit elsewhere, it will grow uncontrollably. When you later expand your taxonomy (adding 20 new specific domains), reclassifying repos out of the catch-all breaks their URLs.

**What happened**: `ml-frameworks` was the catch-all. Expanding from 10 to 30 domains reclassified 10,000 repos. Every reclassified repo had a URL under its old domain that was now a 404. This triggered the need for the entire redirect system.

**What to do**: Plan your redirect system before your first domain expansion. Use an append-only `domain_redirects` table that records every (full_name, old_domain) pair. At build time, resolve each to the current domain and write a static HTML redirect file.

### Plan Redirects from Day One

Every domain reclassification creates a stale URL. Plan for this before it happens.

```python
# During reassignment: record old domain before updating
conn.execute(text("""
    INSERT INTO domain_redirects (full_name, old_domain)
    SELECT full_name, domain FROM ai_repos WHERE id = ANY(:ids)
    ON CONFLICT DO NOTHING
"""), {"ids": ids})

# Then update to new domain
conn.execute(text(
    "UPDATE ai_repos SET domain = :domain WHERE id = ANY(:ids)"
), {"domain": new_domain, "ids": ids})
```

The redirect generator runs after all real pages are built and writes a tiny HTML file at each old path:

```html
<!DOCTYPE html><html><head>
<meta charset="utf-8">
<link rel="canonical" href="https://mcp.phasetransitions.ai/agents/servers/owner/repo/">
<meta http-equiv="refresh" content="0;url=/agents/servers/owner/repo/">
<title>Moved</title>
</head><body>
<p>Moved to <a href="/agents/servers/owner/repo/">/agents/servers/owner/repo/</a></p>
</body></html>
```

`meta http-equiv="refresh"` + `link rel="canonical"` is the static-file equivalent of a 301 redirect for Google. No server-side redirect rules needed.

### Subcategory Taxonomy: Regex First, LLM Second

For each domain, define subcategories as ordered regex patterns. First match wins. Domains without explicit subcategories get auto-generated ones.

```python
MCP_SUBCATEGORIES: list[tuple[str, re.Pattern]] = [
    ("testing", re.compile(r"\btest|mock|fixture|bench", re.IGNORECASE)),
    ("security", re.compile(r"\bauth\b|\boauth\b|security|\brbac\b|permission", re.IGNORECASE)),
    ("observability", re.compile(r"monitor|inspector|debug|observ|trace|telemetry", re.IGNORECASE)),
    # ... ordered specific → general
]
```

**Phase 1 (regex)**: Fast, deterministic, auditable. Processes 50K repos in seconds. First-match-wins means ordering matters -- put specific patterns before general ones.

**Phase 2 (LLM fallback)**: For repos regex missed, batch to Gemini for classification. Batches of 30 repos per prompt, domain-specific valid subcategory lists, returns JSON array.

**Why two phases**: Regex catches 60-70% of repos at zero cost. LLM handles the ambiguous remainder. Running LLM on all 220K repos would cost ~$50 and take hours. Running it on the 30% regex misses costs ~$15.

---

## Chapter 4: Task Queue and Worker

### Postgres Queue with FOR UPDATE SKIP LOCKED

The task queue is a `tasks` table with a `state` column (pending/claimed/done/failed). Workers claim tasks with `FOR UPDATE SKIP LOCKED`, which atomically locks a row and skips already-locked rows.

```sql
WITH next_task AS (
    SELECT t.id
    FROM tasks t
    LEFT JOIN budget_check bc ON bc.resource_type = t.resource_type
    WHERE t.state = 'pending'
      AND t.resource_type = :target_resource
      AND bc.remaining > 0
    ORDER BY t.priority DESC, t.created_at ASC
    LIMIT 1
    FOR UPDATE OF t SKIP LOCKED
)
UPDATE tasks
SET state = 'claimed',
    claimed_by = :worker_id,
    claimed_at = now(),
    heartbeat_at = now()
WHERE id = (SELECT id FROM next_task)
RETURNING id, task_type, subject_id, priority, resource_type,
          retry_count, max_retries
```

**Priority field**: 1-10, lower number = higher priority. Infrastructure tasks (MV refresh, site export) get 3-5. Enrichment tasks get 7-9. Backfills get 1-2.

**Resource type field**: Each task declares what external resource it needs (github_api, github_search, github_graphql, gemini, pypi, npm, huggingface, etc.). The worker runs one task per resource type concurrently. A GitHub task and a Gemini task run in parallel. Two GitHub tasks are serialized.

### Error Classification: Three Kinds of Failure

Not all errors are the same. Classify them and handle each differently.

**ResourceThrottledError** (HTTP 403/429): The provider rate-limited you. Record the throttle in the budget system, activate backoff, and requeue the task. Do not burn a retry.

**PermanentTaskError** (HTTP 451 DMCA, deleted repo): This will never succeed. Fail immediately with 0 retries. Do not requeue.

**Normal exceptions** (timeout, parse error, transient 500): Increment retry count and requeue. Fail after `max_retries`.

```python
class PermanentTaskError(Exception):
    """Error that will never resolve on retry. Fails immediately, no retries."""
    pass
```

**Why this matters**: Without error classification, a DMCA'd repo retries forever (burning API calls), and a rate-limit burns retries (eventually failing a task that would succeed if you waited). PT-Edge had 13,000 wasted API calls over 3 days because `ResourceThrottledError` was caught but `record_throttle()` was never called -- the backoff system never activated.

### The 19K Re-Enqueue Spiral

**The bug**: The dedup index on the tasks table only covered `pending` and `claimed` states. Failed tasks were invisible to dedup. The scheduler re-created tasks for failed repos every 15 minutes, resulting in 19,000 task rows -- 298 repos queued 66 times each.

**The fix**: Extend dedup to include failed state with a 7-day cooldown:

```sql
AND NOT EXISTS (
    SELECT 1 FROM tasks t
    WHERE t.task_type = 'fetch_readme'
      AND t.subject_id = ar.full_name
      AND t.state = 'failed'
      AND t.completed_at > now() - interval '7 days'
)
```

**Why 7 days**: Long enough that transient issues (API outage, rate limits) have resolved. Short enough that a repo fixed by its maintainer (README added, DMCA lifted) gets retried in reasonable time.

### Scheduler Bloat: Cap Everything

**The incident**: The first scheduler run generated 461,000 pending task rows. The query that generates prerequisite tasks (fetch_readme for repos needing enrichment) had no LIMIT clause and no cap on how many pending tasks could exist.

**The fix**: Two caps.

```python
PENDING_CAP = 5000   # max pending tasks before scheduler stops adding
BATCH_LIMIT = 5000   # max tasks to create per scheduler pass
```

The scheduler checks `_pending_count()` before creating tasks. If there are already 5,000 pending fetch_readme tasks, it creates zero. This keeps the task table manageable and prevents the scheduler from overwhelming the worker.

### Non-Blocking Handlers: No subprocess.run()

**The incident**: A handler used `subprocess.run()` inside an async function. This blocked the entire event loop for 20+ minutes. No heartbeats were sent, no other tasks could be claimed, and the reaper eventually reclaimed the task (which was still running in the blocked subprocess).

**The fix**: Use `asyncio.create_subprocess_exec()` for all subprocess calls in handlers:

```python
# BAD: blocks the event loop
result = subprocess.run(["python", "scripts/heavy_job.py"], capture_output=True)

# GOOD: non-blocking
proc = await asyncio.create_subprocess_exec(
    "python", "scripts/heavy_job.py",
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
stdout, stderr = await proc.communicate()
```

### Heartbeating for Long-Running Tasks

Coarse-grained tasks (MV refresh, site export, embedding computation) can run for 30-60 minutes. Without heartbeats, the stale-task reaper (10-minute threshold) reclaims them as "crashed."

**What to do**: Send periodic heartbeat updates during long-running tasks. The worker's heartbeat interval is 60 seconds. The reaper's threshold is 10 minutes. Any task running longer than 10 minutes without a heartbeat gets requeued.

### NULL Resource Type Needs a Claim Path

Tasks without a `resource_type` (MV refresh, site export, content budget computation) need their own claiming code path. The resource-based claim query (`WHERE t.resource_type = :target_resource`) won't match `NULL`.

```sql
-- Separate claim query for NULL resource type tasks
WITH next_task AS (
    SELECT t.id FROM tasks t
    WHERE t.state = 'pending' AND t.resource_type IS NULL
    ORDER BY t.priority DESC, t.created_at ASC
    LIMIT 1
    FOR UPDATE OF t SKIP LOCKED
)
UPDATE tasks SET state = 'claimed' ...
```

**Why this is easy to miss**: You add a new task type, set `resource_type=NULL` because it's compute-only, schedule it, and it sits in pending forever because no claim query matches it. The scheduler keeps logging "Scheduled compute_mv_refresh task" but nothing ever picks it up.

---

## Chapter 5: Resource Budget System

### The Problem: Scattered Rate Limiting

Before the unified budget system, rate limiting was scattered across the codebase:
- In-memory `LIMITER` dict for OpenAI
- Hardcoded `time.sleep(0.5)` for PyPI and npm
- Blind retries for HuggingFace
- No tracking at all for Gemini

Each approach had different failure modes. The in-memory limiter reset on every deploy. The hardcoded sleeps didn't adapt to actual rate limits. Blind retries burned API budget on responses that would never succeed.

### The Fix: Unified resource_budgets Table

One table tracks all 8+ providers. Each row has: resource_type, budget (calls per period), consumed (calls used), period_hours, reset_mode (rolling or calendar), backoff_count, backoff_until.

```
resource_type | budget | consumed | period_hours | reset_mode
--------------+--------+----------+--------------+-----------
gemini        | 10000  | 3421     | 24           | calendar
github_api    | 7400   | 2100     | 1            | rolling
github_search | 30     | 12       | 1            | rolling
pypi          | 5000   | 890      | 24           | calendar
```

### Two-Phase Budget: Check Then Record

**acquire_budget()** checks availability and enforces RPM spacing. It does NOT decrement the budget.

**record_call()** decrements the budget. Called AFTER the HTTP request fires.

```python
# The correct flow:
allowed = await acquire_budget("gemini")
if not allowed:
    raise ResourceExhaustedError("gemini")

response = await http_client.post(gemini_url, json=payload)  # actual API call

await record_call("gemini")  # only NOW do we decrement

if response.status_code == 429:
    await record_throttle("gemini")
    raise ResourceThrottledError("gemini")

await record_success("gemini")  # clears backoff if active
```

**Why two phases**: The previous design decremented the budget in `acquire_budget()` before the request. A `Decimal`/`float` TypeError in the request construction burned 9,300 of 10,000 Gemini daily budget with zero actual API calls. The crash happened after acquire (budget decremented) but before the HTTP request (no API call made). Two-phase ensures you only pay for calls that actually fire.

### Backoff Ceiling: Cap at the Provider's Reset Window

Exponential backoff escalates: 1 minute, 5 minutes, 30 minutes, 2 hours, 8 hours. But GitHub's rate limit resets every hour. An 8-hour backoff for a provider that resets hourly means 7 hours of unnecessary outage.

**The fix**: Cap backoff at the provider's `period_hours`:

```sql
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
      (period_hours || ' hours')::interval  -- never exceed the reset window
    )
WHERE resource_type = :rt
```

### Batch Instrumentation

A coarse-grained task that calls APIs thousands of times per invocation (fetching download counts for 10,000 packages) can burn an entire daily budget in one task. Track sub-calls within the task.

**What to do**: Every HTTP call inside a handler should go through `acquire_budget()` / `record_call()`. Don't just check the budget at the start of the task and assume it's fine for 10,000 subsequent calls.

### Provider Isolation

**The incident**: A single `github` resource slot with 4,500 pending `fetch_readme` tasks starved discovery and commit fetching for 3+ days. The worker serialized all GitHub work through one slot.

**The fix**: Split into three slots with separate budgets:
- `github_api` (REST, 7400/hr) -- metadata, READMEs
- `github_search` (Search API, 30/min) -- discovery, trending
- `github_graphql` (GraphQL, 5000 points/hr) -- commits, detailed queries

Now discovery runs even while README backfill is consuming REST budget.

---

## Chapter 6: Quality Scoring

### Four Components, 0-100 Composite

Quality score has four equally-weighted components (0-25 each):
- **Maintenance**: commit activity, issue response time
- **Adoption**: downloads (PyPI + npm + HuggingFace), dependents
- **Maturity**: age, stability, documentation presence
- **Community**: stars, forks, contributors

Composite score maps to tiers: verified (80+), established (60-79), emerging (40-59), experimental (0-39).

### Per-Domain Materialized Views

Each domain gets its own `mv_{domain}_quality` view. All views must use the same canonical template.

**The bug we hit**: Copy-pasting SQL for new domain views caused schema drift. 3 domains were missing columns that the page template expected. The site generated with errors, or worse, generated with missing data that looked intentional.

**The fix**: A canonical template in `quality_template.py` that generates the SQL for any domain. Plus a schema test that runs in CI:

```python
def test_all_quality_mvs_have_same_columns():
    """Ensure all domain MVs have identical column sets."""
    views = get_all_quality_mv_names()
    reference_columns = get_columns(views[0])
    for view in views[1:]:
        assert get_columns(view) == reference_columns, (
            f"{view} has different columns than {views[0]}"
        )
```

Migration 088 fixed drift across 12 views. Don't let this happen again -- use the canonical template.

### Unique Indexes for CONCURRENT REFRESH

Materialized views need unique indexes to support `REFRESH MATERIALIZED VIEW CONCURRENTLY`. Without concurrency, a refresh takes an exclusive lock for the entire duration (2-5 minutes per view), blocking all queries against that view.

**What to do**: Test uniqueness before building the index. `dep_name + source` wasn't unique (same package on both PyPI and npm). Had to add `repo_id` to the unique constraint.

### DISTINCT ON Is a Smell

If you're using `DISTINCT ON (project_id)` to pick "one download count per project," you're probably picking an arbitrary source. The initial download MVs picked whichever row Postgres returned first for each project -- sometimes PyPI, sometimes npm, sometimes HuggingFace, nondeterministically.

**The fix**: SUM aggregation across all sources. A project's download count is the sum of its PyPI + npm + HuggingFace downloads, not a random pick from one source.

### Snapshot Daily

Store `(repo_id, score, tier, date)` in `mv_{domain}_quality_snapshots` every day. This decouples expensive computation from query latency and gives you historical data for trend analysis.

**Why**: Without snapshots, answering "how has this project's quality changed over the last 30 days?" requires re-computing the score 30 times with historical data. With snapshots, it's a simple SELECT.

---

## Chapter 7: Allocation Engine

### Dual-Score Model

Two independent scores capture different signals:

**Established Heat Score (EHS)**: Demand signals from Google Search Console impressions, Umami pageviews, click-through rate vs benchmark. Measures "people are already looking for this."

**Emergence Score (ES)**: Leading velocity from GitHub star acceleration, Hacker News points, newsletter mentions, new releases. Measures "this is about to matter."

**opportunity_score = MAX(ehs, es)**. Using MAX (not SUM or AVG) ensures a project that's hot on HN but has no search traffic still gets prioritized -- you're betting on the future, not waiting for the present.

### Content Budget Formula

```python
need = opportunity_score * (1 - summary_ratio) * log2(repo_count + 1)
```

- `opportunity_score`: How much demand or emergence this category has
- `(1 - summary_ratio)`: How much of the category is still un-enriched (coverage gap)
- `log2(repo_count)`: Larger categories get more budget, but with diminishing returns

The budget table stores per-pipeline, per-(domain, subcategory) row limits:

```python
# Normalise need scores to sum to 1.0, then allocate rows proportionally
for c in sorted(categories, key=lambda x: x["share"], reverse=True):
    row_limit = max(1, round(c["share"] * total_rows))
```

### Separate Signals from Decisions from Execution

Three layers, strictly separated:

1. **Signals** (`mv_allocation_scores`): Raw opportunity scores, coverage ratios, repo counts. Pure data.
2. **Decisions** (`content_budget`): How many repos to enrich per category per pipeline. Computed daily from signals.
3. **Execution** (scheduler): Reads `content_budget`, creates tasks for the top N repos in each category by stars.

**Why**: When allocation is wrong, you fix the signal weights or the budget formula -- not the scheduler SQL. When the scheduler has bugs, allocation is unaffected. Clean separation means each layer can be tested and debugged independently.

### Add Signals Iteratively

Start with one signal source and add more as you discover gaps.

PT-Edge started with GSC impressions only. This missed emerging projects with no search traffic. Added Umami pageviews, which caught projects people found via direct links. Added GitHub star velocity, which caught new projects. Added HN points, which caught trending discussions. Added AI browsing signals, which caught what agents were asking about.

Each addition caught categories the previous signals missed. Don't try to design the perfect allocation formula upfront -- ship something, observe what it misses, add a signal that catches those cases.

### The Impression/CTR Gap

A page with 1,300 impressions and 0% CTR is an opportunity, not just a negative. Google is showing the page but nobody clicks. This means the content is indexed and relevant, but the snippet isn't compelling enough.

**What to do**: Treat high-impression, low-CTR pages as top enrichment priorities. An AI summary can transform the snippet and unlock clicks. PT-Edge proved this: the `homemade-machine-learning` page went from 1,300 impressions/day at 0% CTR to 38 clicks/day after adding a problem brief on April 6. Position stayed at ~8 the entire time -- only the content changed.

---

## Chapter 8: Enrichment Pipeline

### Fetch and Enrich Are Separate Task Types

`fetch_readme` writes to `raw_cache`. `enrich_summary` reads from `raw_cache` and calls Gemini. If the LLM fails, the README is still cached for retry without another GitHub API call.

### Problem Brief Prompt: Write for the Person With the Problem

The enrichment prompt is not "summarize this README for developers." It is "write for the person who has the problem this project solves."

```
Your audience is NOT a developer -- it's the person who has the problem this
project solves. That might be a scientist, a marketer, a trader, an HR
manager, a teacher, an operations engineer -- whoever benefits from this
existing.
```

Output structure:
- **summary**: 2-3 sentences, what task/workflow, what goes in and out, who uses it (max 80 words)
- **use_this_if**: One sentence, ideal use case
- **not_ideal_if**: One sentence, when to look elsewhere
- **domain_tags**: 3-5 tags in user vocabulary ("spectroscopy", "portfolio-backtesting"), not developer vocabulary ("transformer", "multi-agent")

**Why this prompt design matters**: These summaries become the Google snippet. If the summary says "A Python library implementing transformer-based architectures for NLP tasks," nobody clicks. If it says "Classify customer support tickets by intent and urgency, routing them to the right team automatically," people with that problem click.

### Gemini Flash Economics

Gemini Flash is approximately 10x cheaper than Claude Haiku at comparable quality for structured extraction tasks. Disable thinking tokens (`thinkingBudget: 0`) -- reasoning tokens ate the output budget with zero quality improvement for this use case.

### The Proven Flywheel

This is not theoretical. This is measured:

1. GSC shows 1,300 impressions/day at position 8 with 0 clicks (April 3)
2. Allocation engine prioritizes this page (high impressions, zero CTR = high opportunity)
3. LLM writes problem brief (April 6)
4. Google re-crawls the page
5. Clicks go from 0 to 38/day by April 9

The flywheel is: search data drives allocation, allocation drives enrichment, enrichment drives clicks, clicks drive more search data. It runs autonomously once all the pieces are connected.

---

## Chapter 9: Static Site Generation

### Build Sequence Matters

`start.sh` runs in a strict order:

1. Generate each domain site (30 calls to `generate_site.py`)
2. Generate portal homepage
3. Generate deep dive pages
4. Generate redirect pages (LAST -- must check if real pages exist)
5. `exec uvicorn`

**Why redirect generation runs last**: The redirect generator checks `os.path.exists(old_path)` before writing. If a real page exists at that path (because the repo moved back, or another repo now occupies that domain), it skips the redirect. This check only works if all real pages have already been generated.

### Output Structure

```
site/
  index.html                              # portal homepage
  servers/{owner}/{repo}/index.html       # MCP domain (root)
  agents/servers/{owner}/{repo}/index.html  # agents domain
  rag/servers/{owner}/{repo}/index.html     # RAG domain
  insights/{slug}/index.html                # deep dive pages
  sitemap.xml
  robots.txt
```

### Page Content

Every project page includes:
- Quality score with component breakdown (not just a tier label)
- AI summary (problem brief) with use_this_if / not_ideal_if
- Related projects (internal links)
- Comparison links to similar projects
- JSON-LD SoftwareApplication structured data

**Two audiences drive page design**: AI agents need front-loaded answers, specific numbers, and freshness signals in prose. Humans need original analysis, dense internal linking (10-15 links per page), and structured data for rich snippets.

### The Precomputation Rule

**Never compute data at site generation time.** The site generator runs inside Render's deploy window (~5 minutes before port detection timeout). Every query it runs delays uvicorn startup. With 200K+ entities, even modest per-entity work is fatal.

Two data sources at build time, both pre-computed:

1. **Entity data** (scores + display fields): Materialized views joined to source tables. Configure `display_fields` in ENTITY_CONFIG so `fetch_entities()` adds them via a single JOIN. One query per entity type.

2. **Relationship/enrichment data** (which entities link to which): The `structural_cache` table, populated by the `compute_pairs` worker task. The site generator reads via `load_cached(key)`. One read per cache key.

**The test**: If `generate_site.py` contains a loop that runs a query per entity, or batch queries that scale with entity count, it's wrong. Move that computation to a worker task that writes to `structural_cache`.

**What went wrong on CyberEdge**: `fetch_cve_enrichment()` ran 196 batch queries for 242K CVEs at deploy time to fetch software/vendor/weakness links. Render killed the process before uvicorn started. The fix: precompute the same data in the `compute_pairs` worker task and read from `structural_cache` at build time.

**The OS AI site never hit this** because its MVs are rich — they include all fields the templates need (description, ai_summary, stars, downloads, quality scores). No enrichment queries at build time.

### Structured Data: JSON-LD SoftwareApplication

```json
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "project-name",
  "applicationCategory": "DeveloperApplication",
  "keywords": ["mcp", "postgres", "database"],
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "82",
    "bestRating": "100"
  }
}
```

This is what improved Google's snippets. The structured data gives Google explicit signals about what the page contains, leading to richer search results.

---

## Chapter 10: Bot Tracking and Demand Radar

### Three-Tier Classification

Classify bots in a materialized view, once. Never re-classify in downstream queries.

```sql
CASE
  WHEN user_agent ILIKE '%ChatGPT-User%'     THEN 'tier1_user_action'
  WHEN user_agent ILIKE '%Claude-User%'       THEN 'tier1_user_action'
  WHEN user_agent ILIKE '%Perplexity-User%'   THEN 'tier1_user_action'
  -- Tier 1: a real human asked an AI a question

  WHEN user_agent ILIKE '%GPTBot%'            THEN 'tier2_training'
  WHEN user_agent ILIKE '%ClaudeBot%'         THEN 'tier2_training'
  -- Tier 2: training/indexing crawlers

  WHEN user_agent ILIKE '%Googlebot%'         THEN 'tier3_search'
  WHEN user_agent ILIKE '%Bingbot%'           THEN 'tier3_search'
  -- Tier 3: search engine crawlers
END
```

**Tier 1 (user-action)** is the highest-value signal. Each ChatGPT-User hit means a real human asked an AI a question and the AI cited your page. This is demand data.

**Tier 2 (training)** means AI companies are indexing your content. Useful for understanding coverage but not direct demand.

**Tier 3 (search/SEO)** is traditional search engine traffic.

### Snapshot Tables from Day One

Create `bot_activity_daily` immediately: (date, domain, subcategory, bot_family, hits, unique_pages, unique_ips, revisit_ratio). One row per combination per day.

**Every day without the snapshot table is a day of lost ML training data.** You can't retroactively compute session patterns or revisit ratios from raw access logs that have been rotated. Aggregate daily and store permanently.

### Session Detection

Multi-page session detection uses a 5-minute gap threshold for session boundaries. For OAI-SearchBot, use a 30-second window with fan-out merging across multiple IPs (OpenAI's search bot uses different IPs for different sub-requests within a single user query).

### Audit Quarterly

The initial bot classification was 88% wrong. 6,437 requests/day were misclassified (mostly because new bot user agents appeared that weren't in the CASE statement). Audit the classification against actual user agents quarterly. Version the classifier -- when you update it, re-process the last 30 days with the new rules.

---

## Chapter 11: SEO

### Coverage-Driven Growth

Growth comes from more pages getting 1+ impression, not existing pages getting more traffic. Monitor the impression distribution shape: how many pages have 0 impressions, 1-10, 10-100, 100+. The long tail fattens over time as Google discovers more pages.

PT-Edge indexed 42,000 pages in 2 weeks -- unusual for a new domain. Attributed to: structured data (JSON-LD SoftwareApplication on every page), large interlinked sitemap with `lastmod` dates, and original content (AI summaries, not just restated GitHub data).

### Enrichment Drives CTR

Proven with measurement: position stayed at ~8, but CTR went from 0% to meaningful after adding the AI summary. Google doesn't need to rank you higher for enrichment to have impact -- a better snippet at the same position gets more clicks.

Each position improvement at the bottom of page 1 has outsized CTR impact. Going from position 10 to 9 might double your CTR. Going from 5 to 4 might increase it by 20%. The bottom of page 1 is where enrichment has the highest leverage.

### Dense Internal Linking

Every project page should have 10-15 internal links: related projects, category pages, comparison pages, trending pages. This is not optional for SEO -- it's how Google discovers your pages and understands your site structure.

### Google Crawls API Endpoints

If your API endpoints are linked from the site (e.g., a "View API response" link on project pages), Google will crawl them. This is free SEO -- your API responses become indexed content. Just make sure they return useful structured data, not error pages.

---

## Chapter 12: Observability

### Unified api_usage Table

Log all REST, MCP, and CLI calls to one table with: transport, endpoint, latency, client_ip, user_agent, api_key_id. Index by query pattern: (transport, created_at), (client_ip, created_at), (endpoint, created_at). Don't index everything -- each index slows writes on a table that gets frequent inserts.

### Access Log Middleware: Never Block the Request Path

Buffer access log entries in memory. Flush to database every 5 seconds or 100 rows, whichever comes first. The flush runs as a background asyncio task. A dead database must never block page responses.

```python
_BUFFER_SIZE = 100
_FLUSH_INTERVAL = 5.0  # seconds

class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # ... timing and filtering ...
        _buffer_access(path, method, status_code, user_agent, client_ip, duration_ms)
        return response  # return immediately, never wait for DB write
```

**Skip paths that are logged elsewhere**: `/api/`, `/mcp/`, `/healthz`, and all static assets (`.css`, `.js`, `.png`, etc.). Only log HTML page views. API and MCP calls go to `api_usage`; access logging covers only the static directory site.

### Health Checks Need Alerts, Not Just Logs

PT-Edge has `check_task_health()` (0 successes + >2 failures/hour = ERROR), `check_pipeline_freshness()` (MV refresh or site export not run in 24h = ERROR), and `check_orphaned_tasks()` (tasks pending >1hr, never claimed = ERROR, often due to resource_type mismatch).

**The problem**: These checks only write to the log. Nobody watches the log. It took 2+ days to notice a stuck pipeline because the health check fired but no alert was sent. For your *-edge instance, connect health checks to actual alerts (email, Slack, PagerDuty) -- don't just log.

### Pipeline Freshness

Monitor three things daily:
1. MV refresh completed in the last 24 hours
2. Site export completed in the last 24 hours
3. Content budget computed today

If any of these is stale, the entire pipeline is stuck. The scheduler checks these and logs errors, but as noted above, logging alone is insufficient.

---

## Chapter 13: Testing

### Integration Tests Against Real DB

Mock tests miss JSONB edge cases, encoding issues, and constraint violations. Test with real PostgreSQL.

The JSONB casting bug (`:param::jsonb` with SQLAlchemy `text()`) was invisible to mock tests. It only manifested with actual PostgreSQL because mocks don't parse SQL bind parameters the same way. Test with data containing colons, nested JSON, `None` values, and Unicode.

```python
# Test that JSONB casting works with real PostgreSQL
def test_jsonb_update():
    conn.execute(
        text("UPDATE t SET data = CAST(:val AS jsonb) WHERE id = :id"),
        {"val": json.dumps({"key": "value:with:colons"}), "id": 1}
    )
```

### Schema Validation Tests

All N domain materialized views must have identical column sets. A test that checks this prevents MV template drift:

```python
def test_all_quality_mvs_have_same_columns():
    views = get_all_quality_mv_names()  # e.g., mv_mcp_quality, mv_agents_quality, ...
    reference = get_columns(views[0])
    for v in views[1:]:
        assert get_columns(v) == reference, f"{v} diverged from {views[0]}"
```

### Smoke Tests

Test every endpoint returns 200, every MCP tool is registered, and JSON-RPC responses parse correctly. These catch deployment regressions that unit tests miss.

---

## Appendix: Failure Taxonomy

Every failure PT-Edge encountered falls into one of three categories. Knowing the category helps you recognize similar patterns in your *-edge instance before they become incidents.

### "We Didn't Know We Were Broken"

These are silent failures. The system appeared healthy. Metrics looked normal. But something fundamental was wrong.

**JSONB casting**: The entire enrichment pipeline was failing silently for days. Tasks completed their work (LLM calls succeeded, data was correct) but failed on the final `mark_done` step because the state update used `::jsonb` casting that SQLAlchemy rejected. Tasks showed as "claimed" forever, then got reaped. From the outside, it looked like tasks were just slow.

**Backoff not activating**: The code caught `ResourceThrottledError` but never called `record_throttle()`. The budget system's backoff mechanism existed and was correct, but the error handler that was supposed to trigger it had a missing line. 13,000 wasted API calls over 3 days, all hitting rate limits and retrying immediately.

**Budget burning on crashes**: `acquire_budget()` decremented the budget before the HTTP request. A `Decimal`/`float` TypeError in request construction burned 9,300 of 10,000 Gemini daily budget with zero actual API calls. The crash happened between "decrement budget" and "make HTTP call."

**Pattern to watch for**: Any system where the "check" step and the "do" step are not atomic. If the check has side effects (like decrementing a counter) and the do step can fail, you'll burn resources on failures.

### "We Built It Wrong"

These are design errors. The system worked as designed, but the design was wrong.

**Dedup only on pending/claimed**: 19,000 re-enqueued tasks. The dedup index existed and worked correctly -- it just didn't cover the `failed` state. The design assumption was "failed tasks are done, they don't need dedup." Wrong. Failed tasks get re-scheduled by the next scheduler pass.

**Backoff exceeding reset window**: Exponential backoff reached 8 hours for GitHub, which resets its rate limit every hour. The backoff formula was mathematically correct but operationally wasteful -- 7 hours of unnecessary downtime per incident.

**LIKE joins on large data**: `path LIKE '%/servers/' || full_name || '/%'` on 475K x 220K rows. Syntactically correct SQL. Functionally correct results. Operationally a 40-minute CPU-pegging disaster. The fix was to parse the path once, extract the owner/repo, store it, and join with equality.

**Blocking subprocess in async handler**: `subprocess.run()` inside an async function. Python doesn't warn you. The function signature says `async def handle()` but the body calls a synchronous blocking function. The event loop freezes. No heartbeats, no other task claiming, no timeout detection.

**Pattern to watch for**: Correct logic at the wrong scope. The dedup was correct for in-progress tasks but wrong for the full lifecycle. The backoff was correct for generic APIs but wrong for specific provider reset windows. The join was correct for small tables but wrong for large ones.

### "We Needed Different Architecture"

These are not bugs. The original design was reasonable but couldn't scale.

**Scattered rate-limiting to unified DB-centric budgets**: In-memory limiters, hardcoded sleeps, and blind retries were fine for a single API. With 8+ providers, each with different rate limits, reset windows, and failure modes, the scattered approach was unmaintainable. The unified `resource_budgets` table was a fundamental re-architecture, not a bug fix.

**Domain selection by repo count to selection by tool-selection intent**: Choosing domains by "which fields have lots of repos" produced 8 domains with thousands of repos and zero search traffic. Switching to "where do practitioners compare tools" dropped those 8 domains and focused on commercially relevant ones.

**MV template copy-paste to canonical template with schema test**: Copy-pasting SQL for each new domain MV was fine for 5 domains. At 30 domains, 3 had drifted. Migration 088 fixed 3 missing columns across 12 views. The canonical template ensures this never happens again.

**Pattern to watch for**: Solutions that work at scale N but fail at scale 10N. If you're about to build something and thinking "I'll just copy this for each new domain," stop. Build the template now.

---

## Quick Reference: The Rules

For when you need the prescription without the reasoning.

1. Postgres for everything. No Redis. No RabbitMQ.
2. Generate static pages at deploy time. Runtime DB queries only for API/MCP/logging.
3. Redirect generation runs last in start.sh.
4. Query sizing: <50MB anytime, 50-200MB alone, >200MB batch it.
5. Never run DB queries in the background. Orphaned queries survive client disconnect.
6. Kill queries server-side with `pg_terminate_backend()`, not by killing psql.
7. CAST(:param AS jsonb), never :param::jsonb.
8. Separate fetch tasks from enrich tasks. raw_cache is the interface.
9. follow_redirects=True on all GitHub API calls. Check for renames.
10. Save expensive outputs to file before applying to DB.
11. Choose domains by tool-selection intent, not repo count.
12. MIN_IMPROVEMENT=0.05 on domain reassignment to prevent flip-flopping.
13. Append-only domain_redirects table from day one.
14. Regex first-match-wins for subcategories, LLM fallback for misses.
15. FOR UPDATE SKIP LOCKED for task claiming. Priority field, resource_type field.
16. Three error classes: ResourceThrottled (backoff), Permanent (fail immediately), Transient (retry).
17. Dedup index must cover failed state with 7-day cooldown.
18. Cap pending tasks (5000) and batch size (5000).
19. asyncio.create_subprocess_exec, never subprocess.run in async handlers.
20. Heartbeat long-running tasks or the reaper will reclaim them.
21. NULL resource_type needs its own claim query.
22. acquire_budget() = check only. record_call() = after HTTP fires.
23. Backoff capped at LEAST(escalation, period_hours).
24. Split high-contention providers into separate resource slots.
25. Canonical MV template with schema test. No copy-paste.
26. Unique indexes for CONCURRENT REFRESH. Test uniqueness first.
27. DISTINCT ON is a smell. SUM aggregation instead.
28. Snapshot daily. Every day without is lost data.
29. opportunity_score = MAX(ehs, es). Content budget = opportunity * (1-coverage) * log2(repos).
30. Classify bots once in MV. Three tiers: user-action, training, search.
31. Session detection: 5-min gap, 30-sec fan-out for OAI-SearchBot.
32. Audit bot classification quarterly.
33. Structured data (JSON-LD) on every page. 10-15 internal links per page.
34. Health checks need alerts, not just logs.
35. Buffer access logs in memory, flush in background. Never block the request path.
36. Integration tests with real PostgreSQL. Test JSONB with colons and Unicode.
37. Schema validation test: all domain MVs must have identical columns.
