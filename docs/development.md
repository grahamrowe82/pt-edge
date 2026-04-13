# Development Guide

## Database safety

PT-Edge runs against a production PostgreSQL instance on Render (1GB RAM, 0.5 CPU). There is no staging database. Every query hits real data. These guidelines exist because we've learned them the hard way.

### Estimate query size before running

Before running any query, estimate the data volume:
- `ai_repos` has 220K+ rows. Each 1536d embedding is ~6KB as text. Fetching all embeddings = **1.3GB** — larger than the DB's entire RAM.
- Materialized view refreshes scan the full `ai_repos` table with joins. Each refresh = **2-5 minutes** of sustained CPU.
- Bulk UPDATEs on 100K+ rows trigger autovacuum, which consumes CPU/memory for **15-30 minutes** after.

**Rules of thumb for a 1GB instance:**
- Query result < 50MB: safe to run anytime
- Query result 50-200MB: run alone, no concurrent operations
- Query result > 200MB: don't do it. Batch by domain, by score range, or by LIMIT/OFFSET instead
- If you need all embeddings, process per-domain (5K-70K per query, not 220K at once)

**Before writing a new script, ask:** "How many rows will this touch, how big is each row, and does that fit in 1GB?" If the answer is "maybe not," batch it.

### Never run queries in the background

Run all database-touching commands in the foreground with explicit timeouts. Background processes that fail leave orphaned server-side queries that continue consuming CPU and memory even after the client process is killed. PostgreSQL does not terminate a query when the client disconnects — it keeps running until it completes or is explicitly killed via `pg_terminate_backend()`.

### Never run concurrent operations against the same views

Materialized view refreshes take exclusive locks. If you refresh a view while another process is querying it, the query blocks until the refresh completes. If you then start another refresh or query, you create a lock queue that can cascade into a multi-hour pile-up. One operation at a time.

### Materialized view refreshes are expensive

The quality views join `ai_repos` (220K+ rows) with `package_deps` and compute scoring CTEs. A single refresh can take 2-5 minutes on the production DB. Running all 17 views sequentially takes 30-60 minutes. Don't refresh views unless the underlying data has actually changed (i.e., after ingest). The daily cron handles this.

### Kill orphaned queries from the server side

Killing a local `psql` or Python process does **not** kill the query on PostgreSQL. The server-side backend continues running. To actually stop a query:

```sql
-- See what's running
SELECT pid, state, LEFT(query, 80) as query, now() - query_start as duration
FROM pg_stat_activity
WHERE state = 'active' AND pid <> pg_backend_pid();

-- Kill specific query
SELECT pg_terminate_backend(<pid>);

-- Kill all active queries (nuclear option)
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'active' AND pid <> pg_backend_pid();
```

### Avoid correlated subqueries on large tables

A query like `JOIN table s ON s.id = (SELECT id FROM big_table WHERE name = m.name LIMIT 1)` runs the subquery once per row. On a 13K-row view joining against 220K rows, that's 13K × 220K comparisons. Use a proper JOIN instead:

```sql
-- Bad: correlated subquery (minutes to hours)
JOIN snapshots s ON s.repo_id = (
    SELECT id FROM ai_repos WHERE full_name = m.full_name LIMIT 1
)

-- Good: proper JOIN (seconds)
JOIN ai_repos ar ON ar.full_name = m.full_name
JOIN snapshots s ON s.repo_id = ar.id
```

### Save expensive computation outputs before applying

Any pipeline that involves LLM calls, embedding generation, or clustering must write its results to a file (JSON, CSV) before writing to the database. Discovery and application must be separate steps. If the apply fails, you can re-run it from the saved file instead of re-running the entire pipeline.

```bash
# Good: save then apply
python scripts/discover_categories.py --all-domains --save
python scripts/discover_categories.py --apply-from data/categories.json

# Bad: compute and apply in one shot with no saved artifact
python scripts/discover_categories.py --all-domains --apply
```

### Render deploy and the database

The web service runs `scripts/start.sh` on deploy, which generates static pages from the database before starting uvicorn. If the database is under load, these queries will hang, uvicorn never starts, and Render cancels the deploy after its port timeout.

If a deploy fails with "No open ports detected":
1. Cancel the deploy on Render
2. Check for orphaned queries: `SELECT * FROM pg_stat_activity WHERE state = 'active'`
3. Kill them: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'active' AND pid <> pg_backend_pid()`
4. Wait for DB CPU/memory to drop below 50%
5. Retry the deploy

### Connection limits

Render's managed PostgreSQL has a connection limit (~97 on the current plan). Each `psql` session, each Python process using SQLAlchemy, and each deploy attempt all consume connections. If you see "too many connections" errors, check for orphaned processes locally (`ps aux | grep psql`) and on the server (`pg_stat_activity`).

## Running scripts locally

Always use the virtual environment and source the `.env` file:

```bash
source .venv/bin/activate
set -a && source .env && set +a
python scripts/your_script.py
```

For scripts that hit the database, set an explicit timeout and run in the foreground. Never use `&` or `run_in_background` for database operations.

## Ingest pipeline

The daily ingest runs at 6am UTC via Render cron (`scripts/ingest_all.py`). It takes 4-6 hours. Don't manually run ingest jobs — let the cron handle it. If you need to test an ingest module, run it against a small subset:

```bash
python scripts/backfill_summaries.py --limit 10 --min-score 70
```

## Static site generation

**Important**: The site generator must never compute data at build time. All entity data comes from materialized views, all relationship data from `structural_cache`. See [edge-playbook.md Chapter 9](edge-playbook.md#the-precomputation-rule) for the full pattern.

The site generator queries materialized views and renders Jinja2 templates. To regenerate locally:

```bash
python scripts/generate_site.py --domain mcp --output-dir site
```

For all 30 domains, the full generation takes ~5 minutes and queries the DB heavily. Don't run it while other DB-heavy operations are in progress.

## Render platform

### API access

The Render API key is in `.env` as `RENDER_API_KEY`. Use it to monitor services, check deploys, and manage infrastructure without the dashboard:

```bash
# List services
curl -s -H "Authorization: Bearer $RENDER_API_KEY" "https://api.render.com/v1/services?limit=10"

# List recent deploys for a service
curl -s -H "Authorization: Bearer $RENDER_API_KEY" "https://api.render.com/v1/services/<service-id>/deploys?limit=5"

# Get service details
curl -s -H "Authorization: Bearer $RENDER_API_KEY" "https://api.render.com/v1/services/<service-id>"
```

Render MCP tools are also available in Claude sessions for querying services, deploys, logs, and metrics.

### Render quirks and gotchas

**Auto-deploy on push to main.** Every push to main triggers a deploy. If the DB is under load, the deploy will hang on site generation queries and eventually time out. Cancel deploys from the dashboard when the DB is unhealthy. Consider disabling auto-deploy during heavy DB operations.

**Port detection timeout.** Render's health check scanner expects a port to be open within ~5 minutes of deploy start. If `start.sh` runs DB queries before starting uvicorn and those queries take too long, the deploy is cancelled with "No open ports detected." The fix is not to make uvicorn start first — it's to ensure queries are fast.

**Cron jobs share the Docker image.** The ingest cron uses the same Docker image as the web service. A deploy that breaks the web service also breaks the cron. Don't push breaking changes to main without testing.

**Ephemeral filesystem.** Render web services have ephemeral disk — files written at runtime (like the generated `site/` directory) are lost on every deploy. The site must be regenerated on every startup via `start.sh`.

**Connection limits.** The managed PostgreSQL has ~97 max connections. The web service (2 uvicorn workers), the cron job, and any local development sessions all share this pool. Orphaned connections from killed processes count against the limit until they time out (which can take minutes).

**DB plan: basic-1gb (1GB RAM, 0.5 CPU, 15GB storage).** Upgraded from basic-256mb on 2026-03-28. The 256mb plan couldn't handle bulk vector writes. Current usage: ~3GB of 15GB storage. Autovacuum runs automatically after bulk writes and can consume significant CPU/memory for 15-30 minutes.

**Memory at ceiling is normal.** PostgreSQL deliberately uses all available memory for shared buffers and page cache. The Render dashboard showing 1,000/1,024 MB does NOT mean the DB is in trouble — it means it's caching data efficiently. Check CPU to determine actual load. CPU < 5% with memory at ceiling = healthy idle. CPU > 50% with memory at ceiling = actually under load.

**Deploy hook.** The ingest cron triggers a web service redeploy after completion via `RENDER_DEPLOY_HOOK_URL` environment variable. This is how the site gets fresh data daily: ingest updates DB → refreshes views → triggers deploy → start.sh regenerates site.

## Content creation

**Deep dives** are editorial analysis pages that create hub-and-spoke link clusters around a topic. They live at `/insights/{slug}/` and are rendered from the `deep_dives` database table with live data at build time. The full process — from data pull to Substack companion to deployment — is documented in [docs/briefs/deep-dive-process.md](briefs/deep-dive-process.md).

**Allocation engine** drives deep dive prioritisation. The `v_deep_dive_queue` view ranks topics by Established Heat Score (GSC/Umami signals) and Emergence Score (GitHub velocity). Design brief at [docs/briefs/allocation-engine.md](briefs/allocation-engine.md).
