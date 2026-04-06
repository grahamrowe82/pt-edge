# http_access_log Table Growth Analysis

**Date:** 2026-04-05
**Data span:** 22 hours (2026-04-04 14:12 to 2026-04-05 11:54 UTC)

---

## 1. Current Table Size

| Metric | Value |
|--------|-------|
| Total size (table + indexes) | **54 MB** |
| Table data only | 35 MB |
| Indexes + TOAST | 19 MB |
| Row count | 163,990 |
| Average row size (incl. indexes) | 344 bytes |
| Average row size (table only) | ~213 bytes |

The table was created on 2026-04-04 (migration 074). IDs start at 1 — no rows have ever been purged. There is **no retention policy or cleanup job** in the codebase.

## 2. Insertion Rate

Over the 22 observed hours:

| Metric | Value |
|--------|-------|
| Rows/hour (mean) | ~7,450 |
| Rows/day (projected) | **~179,000** |
| MB/day (total incl. indexes) | **~58 MB** |
| MB/day (table data only) | ~36 MB |

Hourly rates vary from ~1,600 to ~13,200, likely driven by bot crawl schedules. The mean is the reliable planning number.

## 3. Forward Projection (No Purge)

| Milestone | Days from table creation | Estimated date |
|-----------|--------------------------|----------------|
| 100 MB | **~1.7 days** | 2026-04-06 |
| 500 MB | **~8.5 days** | 2026-04-13 |
| 1 GB | **~17 days** | 2026-04-21 |

**This table will consume the entire 1 GB Render Standard DB budget in under 3 weeks** — and the DB is already at 4,240 MB total (see below), meaning it is already well over the standard plan limit.

## 4. Database Context

| Item | Size |
|------|------|
| **Total database** | **4,240 MB** |
| ai_repos | 2,653 MB |
| quality_snapshots | 349 MB |
| hf_datasets | 276 MB |
| ai_repo_snapshots | 234 MB |
| releases | 147 MB |
| public_apis | 125 MB |
| hf_models | 104 MB |
| **http_access_log** | **54 MB** (8th largest, after 22 hours) |
| mv_access_bot_demand | 15 MB (62,623 rows, 1 day) |

http_access_log is already the 8th largest table after less than a day. At current rate, it will overtake hf_models in 1 day and public_apis in 2 days.

## 5. Retention Scenarios: 7 Days vs 30 Days

Since all data is < 1 day old, we can only project:

| Retention | Estimated steady-state size | % of 1 GB budget |
|-----------|----------------------------|-------------------|
| 7 days | **~410 MB** | 41% |
| 30 days | **~1,760 MB** | 176% (exceeds budget) |
| 3 days | **~175 MB** | 17.5% |
| 1 day | **~58 MB** | 5.8% |

**30-day raw retention is not viable.** Even 7 days is expensive at 410 MB.

## 6. Aggregation Strategy: Daily Summaries

### What mv_access_bot_demand already does

The materialized view `mv_access_bot_demand` aggregates raw logs into `(access_date, bot_family, path)` tuples with hit counts, unique IPs, and avg duration. After 1 day:

| Table | Rows | Size | Ratio |
|-------|------|------|-------|
| http_access_log (1 day) | ~164K | 54 MB | 1x |
| mv_access_bot_demand (1 day) | 62,623 | 15 MB | 0.28x |

The materialized view is **3.6x smaller** than raw — decent but not dramatic, because path cardinality is very high (127,225 distinct paths in 164K rows, avg 1.3 hits/path).

### What granularity would be lost

Dropping raw rows after aggregation into daily `(date, path, bot_family)` summaries would lose:

1. **Per-request timing** — individual `duration_ms` values (only avg survives)
2. **IP addresses** — only unique count survives, not which IPs
3. **User-agent strings** — collapsed into `bot_family` categories
4. **Sub-day timing** — cannot tell if hits came at 3am or 3pm
5. **Method/status_code detail** — not carried into the MV
6. **Sequence of events** — cannot reconstruct crawl patterns within a day

### Recommended approach

**Keep raw logs for 1-3 days max, then rely on the materialized view.**

| Component | Retention | Steady-state size |
|-----------|-----------|-------------------|
| http_access_log (raw) | 1 day | ~58 MB |
| mv_access_bot_demand (aggregated) | indefinite | ~15 MB/day, ~450 MB/month |

Even the aggregated view at 15 MB/day grows fast. Consider:
- Dropping low-value paths (404s, single-hit paths) from the MV
- Monthly rollup: collapse daily into monthly `(month, path, bot_family)` after 30 days
- The MV itself needs a retention policy for anything beyond a few months

## 7. Immediate Action Required

**This is urgent.** Without intervention:
- The table hits 500 MB in ~8 days
- Combined with the existing 4.2 GB database, disk pressure will increase

Minimum viable fix:
1. Add a daily cron job: `DELETE FROM http_access_log WHERE created_at < now() - interval '1 day'` (run after MV refresh)
2. Follow with `VACUUM http_access_log` to reclaim space
3. Consider whether mv_access_bot_demand also needs a retention cap (e.g., 90 days)

Without step 2 (VACUUM), deleted rows still consume disk — Postgres does not auto-reclaim space from large deletes.
