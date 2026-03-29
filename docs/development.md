# Development Guide

## Database safety

PT-Edge runs against a production PostgreSQL instance on Render. There is no staging database. Every query hits real data. These guidelines exist because we've learned them the hard way.

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

The site generator queries materialized views and renders Jinja2 templates. To regenerate locally:

```bash
python scripts/generate_site.py --domain mcp --output-dir site
```

For all 17 domains, the full generation takes ~5 minutes and queries the DB heavily. Don't run it while other DB-heavy operations are in progress.
