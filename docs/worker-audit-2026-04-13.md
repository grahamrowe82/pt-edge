# Worker Engineering Audit — 13 April 2026

Assessment of both workers against engineering best practice for long-running Python processes ingesting external data at 200K+ entity scale. For each discipline: what good looks like, what we do, where the gap is, and what breaks as we scale or add domains.

---

## Handler Inventory (verified)

### CyberEdge (11 handlers)

| Handler | Source | Pattern | Frequency |
|---------|--------|---------|-----------|
| `ingest_nvd` | REST API, paginated 2K/page | Stream per page, batch upsert | Daily |
| `ingest_kev` | HTTP JSON, single fetch | Batch, full catalog replace | Daily |
| `ingest_epss` | HTTP gzip CSV, 270K rows | Batch, temp table + UPDATE JOIN | Daily |
| `ingest_mitre` | 3 HTTP fetches (XML+JSON) | Batch per source, sequential | Weekly |
| `ingest_osv` | REST API, per-CVE queries | Loop (5K max), batch update | Daily |
| `ingest_ghsa` | GraphQL, paginated 500 pages | Stream pages, batch update | Daily |
| `ingest_exploit_db` | HTTP CSV, 50K rows | Batch, JOIN against cves | Daily |
| `compute_pairs` | DB-only | Query + cache as JSON | Weekly |
| `compute_hypotheses` | DB-only | Query + cache as JSON | Weekly |
| `compute_embeddings` | DB + OpenAI API | Batch 2K, then UMAP+HDBSCAN clustering | Daily |
| `refresh_views` | DB MV refresh | Sequential REFRESH + snapshots | After ingest |

### OS AI (shared core loop, ~30+ handler types)

Uses the same `app/core/queue/worker.py` loop. Handler types include `fetch_readme`, `fetch_releases`, `enrich_summary`, `compute_structural`, `compute_domain_reassign`, `backfill_created_at`, and many more. Individually smaller tasks than CyberEdge but higher volume.

---

## 1. Data Validation at Ingestion Boundaries

### Best practice

Every piece of external data passes through validation before touching the database:
- **Deduplicate within a batch** before `execute_values` — not just `ON CONFLICT`
- **Truncate strings** to column max length in application code
- **Strip invalid characters** (NUL bytes, invalid UTF-8)
- **Validate schema** — required fields present, types correct
- **Fail the row, not the batch** — skip bad records, count and log skips

This matters because external data is dirty. APIs change schemas without notice. CSVs contain duplicates. Fields exceed expected lengths. If the first line of defence is the database constraint, a single bad record kills an entire batch of thousands.

### What we do

Validation is ad-hoc and handler-specific:
- **NVD** is the most thorough: validates CPE format, filters wildcard vendors/products, regex-validates CWE IDs, deduplicates in Python dicts before INSERT. This is the gold standard in the codebase.
- **EPSS** catches CSV parse errors per-row (IndexError, ValueError) and skips. Good.
- **KEV** skips entries missing CVE ID or date. Good.
- **Exploit-DB** extracts CVE IDs via regex but does not deduplicate the extraction results. The same CVE can appear twice in one exploit's `codes` field, producing duplicate `(exploit_db_id, cve_id)` pairs that crash the batch.
- **MITRE** parses XML/JSON with no per-field validation beyond what the parser provides.
- **OSV/GHSA** trust API response structure, access nested fields with `.get()` fallbacks.

No handler truncates fields to column width. Only one field in the entire codebase is truncated in application code: CWE source to 30 chars (`nvd.py`).

### The gap

There is no shared validation pattern. Each handler invents its own approach. The NVD pattern (deduplicate in Python, validate before INSERT) works but isn't extracted into reusable infrastructure. When building bio/patents domains, each new handler will make its own decisions about validation — and some will get it wrong, the way exploit-db did.

### What breaks at scale

At 1M+ entities, a single bad record in a 5,000-row `execute_values` batch causes a rollback of all 5,000 rows. With more data comes more edge cases in upstream sources. Without systematic validation, failure rate increases with scale.

---

## 2. Idempotency

### Best practice

Every handler produces the same result whether it runs once or twice:
- **Upserts** with `ON CONFLICT` for all writes
- **No side effects on retry** (don't double-count, don't re-send)
- **Full-replace patterns** where appropriate (fetch full catalog, replace all)
- **Batch-level deduplication** so the same batch can be replayed

### What we do

Most handlers are idempotent:
- **NVD**: `ON CONFLICT (cve_id) DO UPDATE` — fully idempotent
- **EPSS**: temp table + UPDATE JOIN — idempotent (full replace daily)
- **KEV**: full catalog fetch + stale flag reset — idempotent
- **compute_pairs**: overwrites cache keys — idempotent
- **refresh_views**: MV refresh is inherently idempotent

The exception is **exploit-db**: duplicate rows within a single `execute_values` call crash the entire batch. The handler is idempotent in theory (ON CONFLICT DO UPDATE) but not in practice because the input isn't deduplicated.

### The gap

Small. Most handlers are naturally idempotent via upsert patterns. The gap is that we haven't explicitly tested or documented idempotency as a requirement. A new handler author wouldn't know it's expected.

---

## 3. Graceful Degradation

### Best practice

When an upstream source is unavailable, returns unexpected data, or changes schema:
- **Distinguish "no new data" from "source broken"** — a legitimate empty result is different from a failed parse returning zero rows
- **Anomaly detection** — if a source normally returns 270K rows and today returns 50, something is wrong
- **Partial success over total failure** — process what you can, report what you couldn't
- **Don't cache empty results** — an empty cache from a failed run poisons downstream consumers until the cache expires

### What we do

We log `success` with `records_written=0` when a handler completes without error, regardless of whether zero records is expected or a sign of failure. There is no concept of "expected record count" or anomaly detection.

The structural_cache problem on April 12 is the canonical example: `compute_pairs` ran against an empty database, cached `[]` for every key, logged `success`, and the scheduler won't re-run it for 7 days. Every downstream consumer (site generator, relationship pages) gets empty data and there is no signal that anything is wrong.

### The gap

This is the widest gap. We have no mechanism to distinguish legitimate empty results from broken ones. No expected-count thresholds. No staleness detection on cached data. No re-trigger when prerequisites are later satisfied.

The pattern we need: if a handler produces results that are significantly below expectations (or empty when they shouldn't be), flag it distinctly — not as `success` and not as `failed`, but as something that needs investigation. And cached data should have a validity check: "does this cache contain meaningful data, or is it stale/empty?"

### What breaks at scale

With 6 domains, each with 5-10 external sources, the chance of at least one source being degraded on any given day is high. Without anomaly detection, degraded data flows silently through the pipeline and appears on the site as missing content. At scale, you can't manually verify every data source every day.

---

## 4. Observability

### Best practice

Without reading logs, you can answer:
- Which tasks ran today, how long did they take, how many records did they process?
- What's the error rate by task type over the last week?
- What's the memory profile of each task type?
- Is any task degrading over time (getting slower, using more memory, processing fewer records)?
- Is there an alert when something goes wrong?

Tools: structured metrics per task execution (duration, memory before/after, record count, error type), queryable via SQL, with threshold-based alerting.

### What we do

Two data sources:
- **sync_log**: `sync_type`, `status`, `records_written`, `started_at`, `finished_at`. Coarse but useful. Covers duration (started_at to finished_at) and record count. No memory data.
- **Task queue** (`tasks` table): `state`, `error_message`, `created_at`, `claimed_at`, `completed_at`. Has timing data but no record counts or memory.

PR #264 added RSS logging to stdout (`Post-task RSS: NNNmb`). This goes to Render logs but not to a queryable table.

No alerting. No dashboards. Problems are discovered by reading Render logs or noticing symptoms (OOM kills, site deploy failures).

### The gap

The data exists in sync_log and the task queue but it's not unified or queryable in a useful way. There's no "task execution metrics" view that joins the two. RSS data goes to logs, not to a table. No alerting.

The gap is more about using what we have than building something new. sync_log already captures most of what we need for basic monitoring. What's missing is: (a) memory metrics in sync_log, (b) a dashboard or query that surfaces anomalies, (c) any form of alerting.

### What breaks at scale

With more handlers, more frequent runs, and more data sources, the probability of a silent failure on any given day increases. Without alerting, the time between "something broke" and "someone noticed" grows. With 6 domains × 10 sources × daily runs, you can't manually check every sync_log entry.

---

## 5. Memory Lifecycle

### Best practice

For a long-running process handling variable-size work:
- **Know the memory profile** of every operation it performs
- **Categorize**: stream (constant memory), batch-and-release (spike then drop), accumulate (grows — bad)
- **Stream where possible** — process data incrementally, don't load it all into memory
- **Batch-and-release where streaming isn't possible** — load, process, explicitly `del`, `gc.collect()`
- **Never accumulate** — no growing module-level dicts, no unbounded result lists
- **Safety net**: RSS monitoring with restart threshold

### What we do

PR #264 added GC + RSS monitoring with configurable restart threshold. This is the safety net. Specific handlers:

| Handler | Pattern | Memory discipline |
|---------|---------|------------------|
| `ingest_nvd` | Stream (per-page) | Good — `del data` after each page |
| `ingest_epss` | Batch-and-release | OK — CSV is ~13MB decompressed, manageable |
| `ingest_kev` | Batch-and-release | OK — ~10MB, trivial |
| `ingest_mitre` | Batch (3 sequential) | No explicit cleanup between modules |
| `ingest_osv` | Batch (per-CVE loop) | OK — accumulates dict but capped at 5K entries |
| `ingest_ghsa` | Stream (paginated) | OK — accumulates dict but capped at 500 pages |
| `ingest_exploit_db` | Batch | OK — ~50MB CSV |
| `compute_pairs` | Batch-and-release | Good — explicit `del` + `gc.collect()` after each cache write |
| `compute_hypotheses` | Batch | No cleanup — results persist until function returns |
| `compute_embeddings` (backfill) | Stream (2K/batch) | OK — bounded batch size |
| `compute_embeddings` (clustering) | **Accumulate** | Loads ALL embeddings into numpy. ~1.2GB for 200K CVEs. |

### The gap

The safety net is in place (RSS restart). Most handlers are acceptable. Two structural concerns:

1. **Clustering** loads the entire embedding matrix into memory. This is an architectural choice (UMAP/HDBSCAN need the full matrix), not a bug. But it means clustering cannot run in the main worker process for large entity types without exceeding the memory limit. This needs a different approach (subprocess isolation, or chunked/approximate clustering).

2. **No handler declares its memory category.** The table above is documentation we just created; it doesn't exist in the code or playbook. A new handler author has no guidance on which pattern to use.

### What breaks at scale

Clustering is the immediate concern — currently blocked by zero embeddings, but will fail when backfill completes. At 2x-10x entity counts, any handler that loads full result sets (compute_pairs enrichment, compute_hypotheses) will need the same batch-and-release discipline that NVD and compute_pairs already have.

---

## 6. Orchestration

### Best practice

- **Prerequisites**: don't run enrichment before core data exists. Don't refresh views before all daily ingests complete.
- **Staleness detection**: if cached data is empty or outdated, detect and re-trigger the computation
- **Ordering**: express dependencies between tasks, not just priorities
- **Bootstrap vs steady-state**: the first run of a system has different needs than daily incremental runs. Handle both explicitly.

### What we do

The scheduler runs every 15 minutes and creates tasks independently. Each task type has a "should I run?" check based on sync_log (did this run today / this week?). There are no inter-task dependencies. Priority numbers provide soft ordering (NVD=9, KEV/EPSS=8, MITRE/OSV/GHSA=7, compute=5-6) but this doesn't enforce prerequisite completion.

Refresh_views has a smarter trigger (checks if any ingest completed since last refresh) but it fires after ANY ingest, not after ALL daily ingests.

There is no staleness detection on cached data. Empty cache from a failed/premature run persists until the next scheduled run.

### The gap

This is the second-widest gap after graceful degradation. The April 12 bootstrap showed the full failure mode:
1. All sources scheduled simultaneously
2. Supplementary sources (EPSS, KEV, etc.) ran before NVD populated the cves table
3. They succeeded with 0 records and cached empty results
4. Weekly tasks (compute_pairs, compute_hypotheses) cached empty data that persists for 7 days
5. No mechanism to detect or recover from this without manual intervention

The scheduler has no concept of "the data needs to be in a certain state before this task makes sense." It only knows "did this task run recently?"

### What breaks at scale

With 6 domains, each with its own bootstrap sequence, the likelihood of orchestration failures increases. Each domain will have its own version of the "supplementary sources ran before core data" problem. Bio will have gene data → protein enrichment → pathway linking. Patents will have patent data → citation graph → assignee resolution. Each needs ordered bootstrapping.

---

## 7. Connection Discipline

### Best practice

- Explicit pool sizing tuned to actual concurrency needs
- Connection recycling to prevent long-lived connection state accumulation
- Proper cleanup in all code paths (including error paths)
- Don't hold connections during long-running non-DB work (API calls, file parsing)

### What we do

PR #264 added `pool_size=3, max_overflow=5, pool_recycle=1800` to both engines. Raw connections are properly closed in finally blocks across all handlers (verified by code review). Sessions for sync_log writes are properly closed.

Handlers that do long API pagination (NVD, GHSA) don't hold DB connections during API calls — they open a connection only for the batch upsert, then close it. This is correct.

### The gap

Small. The basics are in place. The one concern is pool monitoring — we can't see connection pool health without querying `pg_stat_activity` manually. But this is a monitoring gap (covered in observability), not a connection discipline gap.

---

## Summary: Where We Stand

| Discipline | Maturity | Key gap |
|-----------|----------|---------|
| Data validation | Ad-hoc | No shared pattern; each handler invents its own |
| Idempotency | Good | Mostly correct via upsert patterns; not documented as requirement |
| Graceful degradation | **Weak** | No anomaly detection; empty results cached as success |
| Observability | Basic | sync_log exists but no alerting, no memory metrics, no dashboards |
| Memory lifecycle | Good (recently) | Safety net in place; clustering is a known future risk |
| Orchestration | **Weak** | No prerequisites; empty cache persists; bootstrap not handled |
| Connection discipline | Good | Pool tuning + proper cleanup in place |

The two structural weaknesses — **graceful degradation** and **orchestration** — are related. Both stem from the same root cause: the system has no concept of data state. It knows "did this task run?" but not "is the data in a state where downstream tasks will produce meaningful results?"

---

## Domain Engineering Checklist

Every handler in every domain — current and future — must pass these checks. Use this as a review checklist when building new handlers or auditing existing ones.

### Data Validation

- [ ] **Batch deduplication**: before calling `execute_values`, deduplicate by the conflict key in Python. Don't rely solely on `ON CONFLICT` — duplicate rows within a single batch cause `CardinalityViolation`.
- [ ] **Field truncation**: every string field truncated to its column max width before INSERT. Use a helper: `val[:max_len] if val else None`.
- [ ] **Character sanitisation**: strip NUL bytes (`\x00`) from any text field sourced from external APIs or file downloads.
- [ ] **Required field check**: skip the row (don't crash the batch) when a required field is missing or the wrong type. Log the skip count.
- [ ] **Skip count logged**: after processing, log how many rows were skipped and why (`logger.info(f"Skipped {n} rows: {reasons}")`).

### Idempotency

- [ ] **All writes use ON CONFLICT**: INSERT ... ON CONFLICT DO UPDATE or DO NOTHING. No bare INSERTs for data that may be re-ingested.
- [ ] **Cache writes are full-replace**: `_cache_json(key, data)` overwrites the previous value. No append-only patterns on cache keys.
- [ ] **Retry-safe**: running the handler twice against the same data produces the same database state.

### Graceful Degradation

- [ ] **Expected record count**: the handler knows roughly how many records to expect. If the result is <10% of expectation, log a warning and set sync_log status to `degraded` (not `success`).
- [ ] **Empty result guard**: if the handler produces zero records when it shouldn't (e.g. core table has data), don't cache the empty result. Log a warning and exit without writing to `structural_cache`.
- [ ] **Upstream health check**: before processing, verify the HTTP response looks sane (status 200, content-type matches, body is non-empty). Don't parse a 404 error page as CSV.

### Observability

- [ ] **sync_log entry**: every handler writes a sync_log entry with `records_written`, `started_at`, `finished_at`, and `error_message` (truncated to 2000 chars).
- [ ] **Duration derivable**: `finished_at - started_at` gives wall-clock duration. Both fields must be populated.
- [ ] **Memory logged**: the core worker loop logs RSS before and after each task. No handler-level action needed, but heavy handlers should log intermediate RSS if they have multi-phase processing.

### Memory Lifecycle

- [ ] **Memory category declared**: handler comments or docstring states one of: `stream` (constant memory), `batch-and-release` (spike then drop), or `subprocess` (isolated process).
- [ ] **Batch-and-release handlers**: explicitly `del` large objects after committing/caching results, followed by `gc.collect()`.
- [ ] **No accumulation**: no growing module-level dicts, lists, or caches. All state is function-local or explicitly bounded.
- [ ] **Peak estimate documented**: handler docstring includes estimated peak memory (e.g. "~150MB per page" or "~50MB for full CSV").

### Orchestration

- [ ] **Prerequisites declared**: handler docstring states what data must exist before this handler produces meaningful results (e.g. "requires cves table populated by ingest_nvd").
- [ ] **Bootstrap awareness**: if this is the first run and prerequisite data doesn't exist, exit cleanly with a clear log message — don't cache empty results.
- [ ] **Cache validity**: before writing to `structural_cache`, verify the result is non-trivial. An empty list or dict should not overwrite a previous meaningful cache entry.

### Connection Discipline

- [ ] **Raw connections in try/finally**: every `engine.raw_connection()` has a matching `raw.close()` in a finally block.
- [ ] **Sessions closed**: every `SessionLocal()` has a matching `session.close()` in a finally block.
- [ ] **No DB during API calls**: don't hold a database connection open while waiting for an external HTTP response.

---

## Implementation Plan

Two PRs. The first makes everything work. The second makes sure it keeps working.

### PR 1: Fix data flow

Everything that's currently broken or blocking, in one PR.

**Orchestration — scheduler prerequisites:**
- Add `data_readiness` helper: checks core entity tables have meaningful data (e.g. `cves > 1000`)
- Supplementary source schedulers (EPSS, KEV, OSV, GHSA, exploit_db) check readiness before scheduling
- `compute_pairs` and `compute_hypotheses` schedulers check that their inputs are populated
- Empty-result guard on `_cache_json`: don't overwrite meaningful cache with empty data

**Exploit-DB dedup:**
- Deduplicate `(exploit_db_id, cve_id)` pairs in `_parse_csv()` before returning

**Missing MVs:**
- Remove `mv_cve_weakness_landscape`, `mv_software_risk_landscape`, `mv_attack_chain_coverage` from refresh list — they were never created, error every 15 min, mask real failures

**Reset stale cache:**
- Delete the stale `compute_pairs` sync_log entry so the scheduler re-triggers with real data
- Verify structural_cache is populated after it runs

**Files:**
- `domains/cyber/app/queue/scheduler.py`
- `domains/cyber/app/ingest/compute_pairs.py`
- `domains/cyber/app/ingest/exploit_db.py`
- `domains/cyber/app/views/refresh.py`

### PR 2: Engineering standards

Establish patterns so new domains don't rediscover the same failure modes.

**Shared validation helpers:**
- `app/core/ingest/validation.py`: `deduplicate_by()`, `truncate_fields()`, `sanitise_text()`
- Wire into exploit_db and one other handler as proof of pattern

**Observability improvements:**
- `peak_rss_mb` column on sync_log (migration)
- `expected_min_records` per scheduler function — flag `degraded` status when result is suspiciously low
- Documented anomaly-detection query in `docs/development.md`

**Memory documentation:**
- Memory category + peak estimate in every handler docstring
- `del` + `gc.collect()` in `compute_hypotheses.py`
- Memory category table in edge-playbook.md Chapter 4

**Cross-linking:**
- Link checklist from edge-playbook.md Chapters 2, 4, and 9
- Reference in CLAUDE.md: review new handlers against the checklist
- Reference in vision.md: engineering standards documented in playbook + audit
