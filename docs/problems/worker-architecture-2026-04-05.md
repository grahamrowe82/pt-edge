# Worker Architecture Problems

*Documented 5 April 2026, after observing the first post-Gemini-migration daily run.*

## The situation

The daily ingest pipeline (`runner.py`) runs everything in a single sequential process. It started at 06:00 UTC on 5 April 2026. By 09:37 UTC — three and a half hours in — the Gemini enrichment pipeline (the entire point of the Easter weekend migration) had not started. The worker was still grinding through a `created_at` backfill, fetching individual repos from the GitHub API one per second.

The new problem brief pipeline, which is designed to generate 40,000 practitioner-focused assessments per day via Gemini Flash, cannot run until every prior phase completes. On the current architecture, it may never run at all within a 24-hour cycle.

## Problem 1: Everything is sequential

`runner.py` executes ~20 phases in strict sequence:

```
Phase 1 (fast):     github, downloads, dockerhub, vscode, huggingface, hn, v2ex, trending, candidates
Phase 2 (slow):     hf_datasets, hf_models, public_apis, api_specs, package_deps, builder_tools, npm_mcp,
                    ai_repo_downloads (1.5h), ai_repo_commits, candidate_watchlist
Phase 3 (LLM):     ai_repo_package_detect, releases, newsletters
Post-phases:        GSC, Umami ETL, HN backlinking, subcategory classification, stack layers,
                    domain reassignment, project linking, embeddings
MV refresh:         47 materialized views
Content pipelines:  budget computation, ai_repo_summaries (40K Gemini calls), comparison_sentences,
                    repo_briefs, project_briefs, domain_briefs (Sunday), landscape_briefs (Sunday)
Static site deploy: Render webhook
Backfill:           ai_repo_created_at (10 hours, 45K GitHub API calls)
```

If `ai_repo_downloads` takes 1.5 hours and `ai_repo_created_at` takes 10 hours, the content enrichment pipeline (the thing that makes the site valuable to AI agents) is squeezed into whatever time is left. Yesterday's run took 17+ hours. The enrichment pipeline may have started around midnight and had very little time before the next run at 06:00.

## Problem 2: Shared GitHub rate limit with no budget partitioning

Every phase that touches the GitHub API draws from the same 5,000 requests/hour pool:

- `ingest_github`: ~3,000 calls (788 projects × 3-4 calls each)
- `ai_repo_commits`: ~100 calls (GraphQL batches of 50, only repos with ≥500 stars)
- `candidate_velocity`: ~5,000 calls (1,609 candidates × 3 calls each)
- `releases`: ~800 calls
- `ai_repo_created_at`: **45,000 calls over 10 hours** (the backfill)
- `ai_repo_summaries`: **up to 40,000 README fetches** (the new enrichment pipeline)

Total demand: ~94,000 calls/day. Available budget: 120,000 calls/day (5,000/hour × 24 hours). Tight but feasible — IF they don't overlap.

But they do overlap. The `ai_repo_created_at` backfill runs for 10 hours consuming 4,500 calls/hour. During those 10 hours, if any other phase needs GitHub calls, there are only 500 calls/hour left. The `ai_repo_summaries` pipeline has GitHub budget awareness (stops when remaining < 1,000), but by the time it runs, the created_at backfill has already consumed most of the day's budget.

## Problem 3: No visibility

The only observability is the `sync_log` table, which gets one row per phase when that phase finishes. While a phase is running, there's no way to see:

- What phase is currently executing
- How far through it is
- How much GitHub budget has been consumed
- Whether the enrichment pipeline will get to run today
- What the rate of progress is

The Render dashboard shows log lines (`HTTP Request: GET https://api.github.com/repos/...`) but there's no structured progress reporting. You can't tell from the logs whether you're watching Phase 1 or the created_at backfill — they look identical.

## Problem 4: Backfills block the critical path

The `ai_repo_created_at` backfill is designed to run "last, uses remaining time in the day." But "remaining time" after a 17-hour pipeline is 7 hours, and the backfill has a 10-hour time budget. It runs until it either finishes, hits the rate limit, or exhausts its time budget.

The backfill is important but not urgent — it's filling in historical creation dates for repos, which affects the maturity score slightly. The enrichment pipeline is both important and urgent — it's generating the content that AI agents serve to practitioners right now.

The backfill should never consume resources that the enrichment pipeline needs. Currently, there's no priority system — it's first-come-first-served on the GitHub rate limit.

## Problem 5: No separation of concerns

A single worker process handles:
- **Data ingestion** (GitHub, PyPI, npm, HuggingFace, HN) — fetches external data
- **Content enrichment** (Gemini problem briefs, comparison sentences, repo briefs) — generates content via LLM
- **Infrastructure maintenance** (MV refresh, backfills, static site deploy) — housekeeping
- **Analytics** (GSC, Umami ETL) — imports demand signals

These have completely different resource profiles:
- Data ingestion is GitHub-rate-limited and I/O-bound
- Content enrichment is Gemini-rate-limited and compute-light
- MV refresh is CPU-bound on the database
- Backfills are GitHub-rate-limited and can run at any pace

Putting them all in one sequential pipeline means each waits for the previous, even when they have no dependency and don't compete for the same resources.

## Problem 6: The enrichment pipeline can't reach its throughput target

The plan was 40,000 problem briefs per day via Gemini Flash. At 800 RPM (our rate limit setting) with ~2-3 seconds per call (README fetch + Gemini call), 40,000 briefs would take roughly 5-6 hours.

But the enrichment pipeline can't start until all prior phases complete (~17 hours), and when it does start, the GitHub rate limit may already be exhausted by the created_at backfill. Even with README caching (which eliminates GitHub calls on subsequent passes), the first pass needs to fetch 248K READMEs — which requires the GitHub budget that the backfill is consuming.

The system as designed cannot achieve its throughput target. The enrichment pipeline needs to run independently of the data ingestion pipeline, with its own guaranteed share of the GitHub rate limit.

## What needs to change

This document describes the problems, not the solutions. The key insight is that the current single-sequential-process architecture was adequate when the pipeline had ~800 projects and no LLM enrichment. It is not adequate for 248K projects with 40K daily Gemini enrichments, 70K total LLM calls, and a GitHub rate limit shared across 6 competing consumers.

The architecture needs to separate concerns so that:
1. Content enrichment (the revenue-generating work) is never blocked by data ingestion or backfills
2. GitHub rate limit is partitioned, not shared
3. Progress is visible while phases are running, not just after they finish
4. Backfills can run opportunistically without starving the critical path
