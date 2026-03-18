# PT-Edge Product Improvement Roadmap

Surfaced during prospect research sessions on 2026-03-17. Each item includes the problem, evidence, proposed solution, and implementation notes.

---

## Phase 1: Data Integrity Fixes

These undermine credibility of existing data. Fix first.

### 1.1 `commits_30d` snapshot bug ✅ Done (2026-03-18)

**Problem:** Some actively developed projects show 0 commits in 30 days. In at least one case (OpenHands), duplicate snapshot rows exist for the same date — one with correct data (196 commits), one with 0.

**Evidence:**
```sql
SELECT p.name, gs.stars, gs.commits_30d, gs.snapshot_date
FROM projects p
JOIN github_snapshots gs ON p.id = gs.project_id
WHERE gs.snapshot_date = '2026-03-17'
  AND p.name = 'OpenHands';
-- Returns two rows: one with 196 commits, one with 0
```
Inspect AI (18.6M monthly PyPI downloads) and Goose (+386 stars in 7 days) both show 0 commits_30d, which is implausible.

**Fix:**
- Audit the GitHub snapshot ingestion pipeline for race conditions or duplicate inserts
- The `uq_gh_project_day` unique constraint should prevent duplicates — investigate whether the constraint is being bypassed or if the second insert is an upsert overwriting with stale data
- Add a post-ingestion validation check: flag any project where `commits_30d = 0` but `last_commit_at` is within 30 days
- Backfill corrected data for affected projects

**Effort:** Medium (pipeline debugging + validation logic)

---

### 1.2 Contributor count accuracy ✅ Done (2026-03-18)

**Problem:** Contributor counts appear truncated for some projects. DeepEval (14K stars, active development) shows 1 contributor in our snapshot.

**Evidence:** GitHub's REST API for contributors is paginated and returns max 500 per page. If we're only reading the first page (or just the response header), we'll get wrong counts for projects with many contributors.

**Fix:**
- Audit the GitHub API call that populates `github_snapshots.contributors`
- If using the Contributors API, paginate fully or use the `anon` parameter to get accurate counts
- Alternative: use the repo stats API (`GET /repos/{owner}/{repo}/stats/contributors`) which returns all contributors in one call
- Add a sanity check: if `contributors = 1` and `stars > 1000`, flag for manual review

**Effort:** Low (API call fix + backfill)

---

### 1.3 Snapshot history retention ✅ Done (2026-03-18)

**Problem:** Star velocity queries over 30-day windows fail because historical snapshots are pruned too aggressively. The 30-day star delta query returned no results for eval tools.

**Fix:**
- Retain at minimum 90 days of `github_snapshots` and `download_snapshots` data for all curated projects (the 374 in `projects` table)
- For the broader `ai_repos` table, retain weekly rollups for 90 days (daily snapshots can be pruned after 30 days to manage storage)
- Add a `snapshot_retention_days` config parameter
- Consider a `github_snapshots_weekly` rollup table for long-term trend analysis

**Effort:** Low (retention policy change + optional rollup table)

---

## Phase 2: Coverage Gaps

These limit what PT-Edge can analyze. Each opens a new data dimension.

### 2.1 VS Code Marketplace extension tracking ✅ Done (2026-03-18, PR #73)

**Problem:** Major agent projects (Cline, Goose, Cursor, Continue) are distributed as VS Code extensions, not PyPI/npm packages. We can't measure their download-based adoption, which undermines hype-ratio analysis — our strongest differentiator.

**Implemented:**
- Added `vscode_extension_id` column to `projects` table (migration 035)
- Created `app/ingest/vscode_marketplace.py` — fetches install counts from VS Code Marketplace API
- Stores in `download_snapshots` with `source='vscode'` (reuses existing table, no new table needed)
- Added to Phase 1 of `runner.py` for daily ingestion
- Seeded Cline (`saoudrizwan.claude-dev`) and Continue (`Continue.continue`)
- JetBrains Marketplace remains a future target

---

### 2.2 Python `package_deps` ingestion ✅ Done (infrastructure exists, 2026-03-18 PR #73 confirmed)

**Problem:** The `package_deps` table only has data for npm packages. Python dependency graphs are missing for all projects, which blocks dependency analysis — a high-value signal for tool selection recommendations.

**Status:** The infrastructure already exists in `app/ingest/package_deps.py` — it fetches PyPI `requires_dist` via the PyPI JSON API and stores in `package_deps` with `source='pypi'`. 35K+ PyPI deps are already stored for `ai_repos`. Curated projects access deps via the `projects.ai_repo_id → ai_repos → package_deps` join path. Remaining pending repos are processed by the regular cron cycle.

---

### 2.3 Dependency reverse-lookup ✅ Done (2026-03-18)

**Problem:** We track what projects depend on (forward graph), but can't answer "which projects depend on X?" (reverse graph). This is valuable for understanding a library's downstream impact.

**Implemented:**
- Added `GET /api/v1/dependencies/{package_name}/dependents` endpoint
- Query function `get_dependents()` in `queries.py` — joins `package_deps` → `ai_repos`, returns dependents sorted by stars
- Supports `source` filter (pypi/npm), `include_dev` flag, and `limit` param
- Response includes summary counts (total, by source) plus detailed dependent list
- Uses existing `ix_package_deps_dep_name` index — no migration needed

---

### 2.4 Tutorial/demo repo classification ✅ Done (2026-03-18, PR #72)

**Problem:** PT-Edge metrics (downloads, lifecycle stage) don't apply well to tutorial/demo repos. Awesome-lists and example collections get flagged as "no downloads" when that's expected behavior, not a negative signal.

**Implemented:** Added `content_type` column to `ai_repos` (migration 034) with values: `tool` (default), `awesome-list`, `tutorial`, `course`. Classified via heuristics on repo name and topics array.

---

### 2.5 Closed-source project tracking ✅ Done (2026-03-18)

**Problem:** Major commercial AI tools (Devin, Windsurf, Cursor) have no public repos. They're invisible in our data but relevant to landscape analysis.

**Implemented:**
- Created `commercial_projects` table (migration 037) with name, slug, url, category, description, pricing_model, timestamps
- Seeded 20 significant closed-source projects across ai-coding, llm-consumer, content-generation, ai-infra, and productivity categories
- Added `CommercialProject` model in `app/models/content.py`
- Added `GET /api/v1/commercial-projects` endpoint with optional `category` filter
- All responses include `source: "curated"` flag — no metrics, just reference data

---

## Phase 3: New Data Sources

Each adds a new platform or signal type to the tracking index.

### 3.1 Academic paper tracking ✅ Done (2026-03-18)

**Problem:** No arXiv, Semantic Scholar, or citation data. AI research papers are a core content type for newsletters and analysts, and many open-source projects originate from papers.

**Implemented:**
- Created `papers` and `paper_snapshots` tables (migration 038)
- `Paper` and `PaperSnapshot` models in `app/models/content.py`
- Full Semantic Scholar ingest in `app/ingest/semantic_scholar.py` — searches by project name + GitHub repo URL
- Citation count snapshots recorded each run for time-series tracking
- Registered in Phase 2 of `runner.py`
- `GET /api/v1/papers` endpoint with `q`, `project`, `year`, `limit` filters

---

### 3.2 Social signal aggregation — Reddit stub ✅ Done (2026-03-18)

**Problem:** Twitter/X and Reddit are major discovery channels for AI tools. We only track Hacker News.

**Implemented (stub):**
- Created `reddit_posts` table (migration 038) with full schema
- `RedditPost` model in `app/models/content.py`
- Stub ingest at `app/ingest/reddit.py` — returns early with `{"skipped": True, "reason": "no credentials"}` if `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` not set
- **Not registered in runner.py** — activate when credentials are configured
- No API endpoint yet — add when data exists
- Twitter/X remains future work

---

### 3.3 Download count methodology documentation ✅ Done (2026-03-18)

**Problem:** PyPI and Docker Hub download counts include CI/CD automation, bots, and transitive dependency pulls. Without methodology notes, data consumers may draw incorrect conclusions.

**Implemented:**
- `GET /api/v1/methodology` endpoint — lists all 24 methodology entries with optional `category` filter (metric, tool, algorithm, design)
- `GET /api/v1/methodology/{topic}` endpoint — returns full detail for a topic
- Query functions `get_methodology_list()` and `get_methodology_detail()` in `app/api/queries.py`
- No migration needed — `methodology` table already has 24 entries

---

## Phase 4: Enhanced Signals

These add depth to existing data. Lower urgency but high value for differentiation.

### 4.1 Intra-day velocity and breakout detection

**Problem:** Daily snapshots catch trends after they've already trended. Projects can gain thousands of stars in hours from a viral post, and we don't see it until the next day's snapshot.

**Proposed solution:**
- Add hourly star checks for the top 50 projects by recent velocity
- Implement a breakout detection algorithm: flag any project gaining stars at >5x its 7-day average hourly rate
- Create a `breakout_alerts` table: `project_id, detected_at, star_rate, trigger_source`
- Expose via API as `/v1/breakouts` endpoint

**Implementation notes:**
- GitHub API rate limits (5000/hr authenticated) are sufficient for hourly checks on 50 projects
- Start with curated projects only; expand to `ai_repos` top-1000 based on demand
- Consider webhook integration for real-time alerts (Slack, email)

**Effort:** High (new pipeline cadence, detection algorithm, alerting)

---

### 4.2 Contributor quality metrics

**Problem:** `contributors` count is a single number. It doesn't capture contributor health: bus factor, new contributor onboarding rate, or concentration of commits.

**Proposed solution:**
- Extend `github_snapshots` or create `contributor_metrics` table:
  - `bus_factor`: minimum contributors responsible for 50% of commits
  - `top_contributor_pct`: % of commits from the #1 contributor
  - `new_contributors_30d`: contributors with first commit in last 30 days
  - `contributor_retention_90d`: % of 90-day-ago contributors still active
- Compute from GitHub's stats/contributors API (returns per-contributor weekly commit counts)

**Implementation notes:**
- The stats/contributors API can be slow (GitHub computes on-demand, returns 202 + retry)
- Cache results aggressively — contributor patterns change slowly
- Start with curated projects only

**Effort:** Medium (new metrics, API complexity, caching)

---

### 4.3 Issue response time and maintainer health

**Problem:** For teams evaluating tools, maintainer responsiveness matters as much as feature set. We don't track issue/PR response times.

**Proposed solution:**
- Track for curated projects:
  - `median_issue_response_hours`: time from issue creation to first maintainer comment
  - `median_pr_review_hours`: time from PR creation to first review
  - `open_issues_ratio`: open issues / total issues (staleness indicator)
  - `issues_closed_30d`: volume of resolved issues
- Create `maintainer_health` table with monthly snapshots
- Use GitHub's Issues and Pull Requests APIs with `since` parameter for incremental fetching

**Implementation notes:**
- Distinguish maintainer comments from community comments (check against contributor list)
- Expensive in API calls — batch during off-peak hours
- Consider only tracking issues labeled "bug" to reduce noise

**Effort:** Medium-High (API-intensive, needs careful filtering)

---

### 4.4 China ecosystem coverage

**Problem:** China's AI open-source ecosystem is divergent — different model architectures, platform integrations, institutional structures. We track Chinese repos by stars but lack context on the ecosystem's structure.

**Proposed solution:**
- Add `region` classification to `ai_repos` based on:
  - GitHub owner's location (from profile)
  - README language detection
  - Known Chinese AI labs and companies (Tsinghua, Shanghai AI Lab, Alibaba, Baidu, etc.)
- Track Gitee mirrors where they exist (many Chinese projects mirror to Gitee)
- Add V2EX post tracking (already have `v2ex_posts` table — ensure it's populated)
- Consider ModelScope as a HuggingFace equivalent for Chinese models

**Implementation notes:**
- Language detection on READMEs is a reasonable proxy for origin
- Gitee API is accessible but documentation is in Chinese
- Start with manual curation of top 50 Chinese AI projects, then automate classification

**Effort:** High (new data sources, language detection, manual curation)

---

### 4.5 MCP subcategory taxonomy

**Problem:** MCP (Model Context Protocol) emerged as a 665-repo category in late 2024. The current flat categorization doesn't distinguish between MCP servers, clients, SDKs, and tooling.

**Proposed solution:**
- Add subcategories to the MCP domain in `ai_repos`:
  - `mcp-server`: individual MCP server implementations
  - `mcp-client`: client libraries and host implementations
  - `mcp-sdk`: official and community SDKs
  - `mcp-tooling`: development tools, testing, deployment
  - `mcp-aggregator`: directories and collections (awesome-mcp-servers, etc.)
- Classify based on repo name patterns, README content, and topic tags
- The `subcategory` column already exists on `ai_repos` — populate it

**Implementation notes:**
- Most MCP repos follow naming conventions (`*-mcp-server`, `mcp-*`)
- The official MCP spec repo and SDKs are easy to identify
- Reassess taxonomy quarterly as the ecosystem matures

**Effort:** Low (classification logic on existing column)

---

### 4.6 Qualitative project summaries

**Problem:** Raw metrics tell you *what* is happening but not *why*. An AI-generated summary layer would bridge the gap between data and narrative.

**Proposed solution:**
- Generate short (2-3 sentence) project summaries using an LLM, grounded in:
  - README content
  - Recent release notes
  - Lifecycle stage and trajectory
  - Comparative positioning (e.g., "the most-downloaded eval framework despite low star count")
- Store in a `project_summaries` table: `project_id, summary, generated_at, model_used`
- Regenerate monthly or on significant lifecycle stage changes
- Expose via API as an optional `include=summary` parameter

**Implementation notes:**
- Use structured prompts with data context to minimize hallucination
- Include a `generated_by: 'ai'` flag in API responses for transparency
- Human review for top-50 projects; automated for the long tail

**Effort:** High (LLM pipeline, quality assurance, ongoing cost)

---

## Summary

| Phase | Items | Done | Remaining | Unlocks |
|-------|------:|:-----|:----------|:--------|
| 1. Data Integrity | 3 | 3 (1.1, 1.2, 1.3) | 0 | Trustworthy existing data |
| 2. Coverage Gaps | 5 | 5 (2.1, 2.2, 2.3, 2.4, 2.5) | 0 | Agent ecosystem, Python deps, repo classification, reverse-lookup, commercial tools |
| 3. New Data Sources | 3 | 3 (3.1, 3.2 stub, 3.3) | 0 | Papers, social signals (Reddit needs credentials), methodology transparency |
| 4. Enhanced Signals | 6 | 0 | 6 | Velocity detection, contributor health, China, MCP taxonomy, qualitative layer |

**Additional improvements shipped (not in original roadmap):**
- **Domain taxonomy expansion** (2026-03-18, PR #73): Expanded from 10 → 17 domains. Added `ai-coding`, `diffusion`, `voice-ai`, `nlp`, `computer-vision`, `mlops`, `data-engineering`. Splits the `ml-frameworks` (65K repos) and `llm-tools` (34K) catch-all buckets into actionable categories.
- **Snapshot backfill** (2026-03-18, PR #73): Ran GitHub, PyPI/npm, and Docker Hub ingest for 17 new seed projects that had no snapshots.

**Recommended execution order for remaining items:**
- Phase 1: 1.1 (commits bug) → 1.2 (contributors) → 1.3 (retention)
- Phase 2: 2.3 (reverse lookup) → 2.5 (commercial)
- Phase 3: 3.3 (methodology docs) → 3.2 (Reddit) → 3.1 (papers)
- Phase 4: 4.5 (MCP taxonomy) → 4.2 (contributor quality) → 4.1 (breakout detection) → 4.3 (maintainer health) → 4.4 (China) → 4.6 (qualitative)
