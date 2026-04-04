# Plan: Migrate LLM Pipeline from Haiku to Gemini + Practitioner Problem Briefs

## Context

PT-Edge's server access logs reveal that ChatGPT is fetching ~40+ project pages per hour to answer questions from non-developer practitioners (scientists, marketers, traders, HR managers). The current AI-generated summaries are developer-focused ("uses stdio transport with automatic reconnection") and don't help ChatGPT give good practitioner-oriented answers ("identify unknown mineral samples from their Raman spectra").

We validated a new "problem brief" prompt that produces practitioner-focused content with domain tags, and confirmed that Gemini Flash produces ~80% of Haiku's quality at ~10% of the cost. The user wants to switch the entire LLM pipeline from Haiku to Gemini and scale volume from ~4K to 10-20K enrichments/day.

### Key numbers
- 247,800 repos in `ai_repos`, 13,636 currently have `ai_summary`
- `ai_repos` table: 2.6GB, total DB: 4GB (Render managed Postgres)
- Current LLM spend: ~8,200 Haiku calls/day at multiplier 2.0
- Target: 10,000-20,000 Gemini calls/day at similar or lower cost
- GitHub API: 5,000/hr = 120K/day available for README fetches

## Implementation Plan

### PR 1: Add Gemini LLM backend to `llm.py`

**Goal:** Drop-in replacement — all existing call sites work identically, no prompt changes, no schema changes. The pipeline outputs the same content from a different model.

**Files:**

`app/settings.py` — Add 3 settings:
```python
GEMINI_API_KEY: str = ""
GEMINI_RPM: int = 1000       # Gemini paid tier supports 2000+, start conservative
GEMINI_MODEL: str = "gemini-2.5-flash"
```

`app/ingest/rate_limit.py` — Add `GEMINI_LIMITER = RateLimiter(rpm=settings.GEMINI_RPM)` alongside existing `ANTHROPIC_LIMITER`.

`app/ingest/llm.py` — Rewrite both functions to call Gemini REST API via httpx (no SDK dependency):
- Endpoint: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}`
- `call_haiku()` (JSON): use Gemini's `responseMimeType: "application/json"` for native JSON mode — eliminates markdown fence stripping
- `call_haiku_text()` (text): omit responseMimeType
- Response parsing: `response["candidates"][0]["content"]["parts"][0]["text"]`
- Swap `ANTHROPIC_LIMITER` → `GEMINI_LIMITER`
- **Keep function names as `call_haiku` / `call_haiku_text`** — rename in cleanup PR to avoid touching 18 files now
- Guard: `if not settings.GEMINI_API_KEY: return None`

`app/ingest/newsletters.py` (lines 210-231) — Replace the direct Anthropic HTTP calls in `_extract_topics()` with `await call_haiku(prompt, max_tokens=8192)`. This eliminates 20 lines of duplicated HTTP/retry code. Update the API key guard on line 196 from `ANTHROPIC_API_KEY` to `GEMINI_API_KEY`. Same for the guard at line 409.

Update API key guards in: `project_briefs.py`, `landscape_briefs.py`, `builder_tools.py` — change `settings.ANTHROPIC_API_KEY` → `settings.GEMINI_API_KEY`.

`.env` — `GEMINI_API_KEY=...` (already added)

**Validation:** Run with `LLM_BUDGET_MULTIPLIER=0.1` (~200 summaries) to verify all 13 call sites produce valid output.

---

### PR 2: Schema migration — new columns + README cache

**Goal:** Additive schema change. No data populated yet.

New migration `077_problem_brief_columns.py`:
- `ALTER TABLE ai_repos ADD COLUMN problem_domains TEXT[]`
- `ALTER TABLE ai_repos ADD COLUMN use_this_if TEXT`
- `ALTER TABLE ai_repos ADD COLUMN not_ideal_if TEXT`
- `ALTER TABLE ai_repos ADD COLUMN readme_cache TEXT`
- `ALTER TABLE ai_repos ADD COLUMN readme_cached_at TIMESTAMPTZ`
- Drop and recreate all 18 domain quality materialized views adding `problem_domains`, `use_this_if`, `not_ideal_if` to the SELECT list (follow pattern from migration 054/071). `readme_cache` stays off the views — it's only used by the enrichment pipeline, not rendered.

The README cache adds ~2GB at full coverage (248K * 8KB). This is acceptable — storage is cheap and having READMEs locally decouples all future LLM enrichment from the GitHub API entirely. Enables prompt iteration, model comparison, and backfill without re-fetching. Can upsize the DB plan if needed.

**Risk:** Zero. Additive columns, views recreated with superset of existing columns.

---

### PR 3: README caching + new problem brief prompt + lower threshold

**Goal:** Cache READMEs on fetch, switch to practitioner-focused problem briefs, populate new columns.

`app/ingest/ai_repo_summaries.py`:

1. **README caching:** After `fetch_readme()` succeeds, store the text in `ai_repos.readme_cache` and `readme_cached_at`. Before fetching from GitHub, check if `readme_cache IS NOT NULL` — if so, use the cached version and skip the GitHub API call. This means the first pass through 248K repos hits GitHub, but all subsequent enrichment passes (prompt changes, model swaps, backfills) are free.

2. **README refresh policy:** Re-fetch from GitHub if `readme_cached_at` is older than 90 days, to keep content reasonably current. This runs naturally during the daily pipeline — a small fraction of repos get refreshed each day.

3. **Replace `SUMMARY_PROMPT`** with the validated `PROBLEM_BRIEF_PROMPT` from `docs/scratch/generate_problem_briefs.py`. Returns JSON: `{summary, use_this_if, not_ideal_if, domain_tags}`.

4. **Switch from `call_haiku_text` to `call_haiku`** — new prompt returns structured JSON.

5. **Replace `_save_summary()`** with `_save_problem_brief()` that writes all fields:
   ```python
   UPDATE ai_repos SET
     ai_summary = :summary,
     use_this_if = :use_this_if,
     not_ideal_if = :not_ideal_if,
     problem_domains = :domain_tags,
     ai_summary_at = NOW()
   WHERE id = :id
   ```

6. **Lower `MIN_QUALITY_SCORE`** from 30 to 0. Niche projects (19-star Raman spectra lib) are exactly where practitioners look. The allocation engine already prioritises by demand — the threshold was just excluding the long tail.

**Existing `ai_summary` values are preserved** until overwritten by a new pass. The template already renders `ai_summary` — content is immediately visible.

---

### PR 4: Increase volume to 10-20K/day

**Goal:** Scale up, leveraging Gemini's lower cost.

`app/allocation/budget.py` — Update base rows:
```python
BASE_CONTENT_ROWS = {
    "ai_repo_summaries": 4000,   # was 2000
    "comparison_sentences": 2000, # unchanged
    "repo_briefs": 200,           # was 100
}
```

`app/settings.py` — Change `LLM_BUDGET_MULTIPLIER` default from `2.0` to `5.0`.

At multiplier 5.0: **20,000 summaries** + 10,000 comparison sentences + 1,000 repo briefs = 31,000 calls/day. At Gemini pricing this is ~$3-6/day.

`app/ingest/ai_repo_summaries.py` — Update `MAX_PER_RUN` from 2000 to 25000.

**Ramp plan:** Start at multiplier 3.0, validate costs for one daily run, then move to 5.0. At 20K/day, full coverage of 248K repos in ~12 days.

---

### PR 5: Template updates — render new fields

**Goal:** Display problem_domains, use_this_if, not_ideal_if on project pages and in structured data.

`templates/server_detail.html`:
- After the `ai_summary` paragraph (line 82), add `problem_domains` as pill badges (reuse the `risk_flags` rendering pattern from lines 90-96)
- Add a compact callout for `use_this_if` / `not_ideal_if` below the summary (only rendered when populated)
- Update JSON-LD `SoftwareApplication` schema: add `"keywords": [{{ server.problem_domains | tojson }}]`

`templates/comparison.html`:
- Show domain tags for each compared repo in the About section

`scripts/generate_site.py`:
- Update the SQL query (~line 401) to SELECT the 3 new columns from quality views
- Pass them to templates via the server dict

---

### PR 6: ChatGPT demand signal in allocation engine

**Goal:** Categories that ChatGPT users are asking about get more content budget.

New migration `078_allocation_chatgpt_demand.py`:
- Drop and recreate `mv_allocation_scores` adding a CTE that aggregates `ChatGPT-User` hits from `http_access_log` by domain/subcategory (extracting domain from URL path)
- Add `chatgpt_hits_7d` to the view output
- Fold into the opportunity score: `GREATEST(ehs, es, chatgpt_demand_score)` — so a category with high ChatGPT demand but low GSC/velocity still gets budget

`app/allocation/budget.py` — No code changes needed. The budget engine reads `opportunity_score` from the view — the new signal flows through automatically.

---

### PR 7: Cleanup — rename functions, remove Anthropic vestiges

`app/ingest/llm.py` — Rename `call_haiku` → `call_llm`, `call_haiku_text` → `call_llm_text`.

All 18 call site files — mechanical find-and-replace of imports and calls.

`app/settings.py` — Remove `ANTHROPIC_API_KEY`, `ANTHROPIC_RPM` (after confirming nothing references them).

`app/ingest/rate_limit.py` — Remove `ANTHROPIC_LIMITER`.

---

## Category names: out of scope for this migration

The existing subcategory system uses developer-focused slugs ("self-supervised-learning", "causal-inference-ml") derived from UMAP+HDBSCAN embedding clustering. These serve as the site's structural taxonomy and are embedded in URLs, regex patterns, and database indexes.

The new `problem_domains` tags on each project page are a separate, complementary taxonomy — generated per-project from the README, in practitioner vocabulary ("spectroscopy", "mineral identification", "resume screening"). These serve a different purpose: helping AI assistants match user queries to projects.

Both taxonomies can coexist. The structural categories organise the site; the problem domains help AI tools find the right project for a practitioner's question. If practitioner-friendly category display labels are wanted later, the cleanest approach is to add a `practitioner_label` column to `category_centroids` (alongside the existing `display_label`) and regenerate via LLM — a lightweight pass that doesn't require re-clustering. This is a separate, future piece of work.

---

## Dependency graph

```
PR 1 (Gemini backend)
  ├── PR 2 (schema) ─── PR 3 (prompt + caching + threshold) ─── PR 4 (volume)
  │                                                            └── PR 5 (templates)
  │                 └── PR 6 (ChatGPT demand signal)
  └── PR 7 (cleanup) — after all PRs merged
```

PRs 4, 5, 6 can be worked in parallel after PR 3.

## Critical files

| File | Change | PR |
|------|--------|-----|
| `app/ingest/llm.py` | Rewrite for Gemini REST API | 1 |
| `app/settings.py` | Add Gemini settings, adjust multiplier | 1, 4 |
| `app/ingest/rate_limit.py` | Add GEMINI_LIMITER | 1 |
| `app/ingest/newsletters.py` | Replace direct Anthropic HTTP calls | 1 |
| `app/ingest/ai_repo_summaries.py` | README cache, new prompt, lower threshold, JSON mode | 3 |
| `app/allocation/budget.py` | Increase BASE_CONTENT_ROWS | 4 |
| `templates/server_detail.html` | Render domain tags, use_this_if | 5 |
| `scripts/generate_site.py` | SELECT new columns from MVs | 5 |
| Migration 077 | Add columns (incl readme_cache) + recreate 18 MVs | 2 |
| Migration 078 | ChatGPT demand in mv_allocation_scores | 6 |

## Verification

After each PR:
1. **PR 1:** Run `python -m app.ingest.ai_repo_summaries --limit 10` — verify Gemini generates valid summaries
2. **PR 2:** Run migration, verify `\d ai_repos` shows new columns (including readme_cache), verify MV refresh succeeds
3. **PR 3:** Run `--limit 50`, verify `ai_summary`, `problem_domains`, `use_this_if`, `not_ideal_if` all populated. Verify `readme_cache` populated for fetched repos. Spot-check 5 projects across different domains (at least one niche/low-score project).
4. **PR 4:** Run full pipeline with multiplier 3.0, check cost/timing, then ramp to 5.0
5. **PR 5:** Generate static site locally, visually check 3-4 project pages for correct tag and callout rendering
6. **PR 6:** Verify `mv_allocation_scores` includes `chatgpt_hits_7d`, check budget output favours categories with ChatGPT traffic
7. **PR 7:** Grep for any remaining `haiku` / `ANTHROPIC` references
