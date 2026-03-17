# PT-Edge Product Improvement Roadmap

Surfaced during prospect research sessions on 2026-03-17. Each item includes the problem, evidence, proposed solution, and implementation notes.

---

## Phase 1: Data Integrity Fixes

These undermine credibility of existing data. Fix first.

### 1.1 `commits_30d` snapshot bug

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

### 1.2 Contributor count accuracy

**Problem:** Contributor counts appear truncated for some projects. DeepEval (14K stars, active development) shows 1 contributor in our snapshot.

**Evidence:** GitHub's REST API for contributors is paginated and returns max 500 per page. If we're only reading the first page (or just the response header), we'll get wrong counts for projects with many contributors.

**Fix:**
- Audit the GitHub API call that populates `github_snapshots.contributors`
- If using the Contributors API, paginate fully or use the `anon` parameter to get accurate counts
- Alternative: use the repo stats API (`GET /repos/{owner}/{repo}/stats/contributors`) which returns all contributors in one call
- Add a sanity check: if `contributors = 1` and `stars > 1000`, flag for manual review

**Effort:** Low (API call fix + backfill)

---

### 1.3 Snapshot history retention

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

### 2.1 VS Code Marketplace extension tracking

**Problem:** Major agent projects (Cline, Goose, Cursor, Continue) are distributed as VS Code extensions, not PyPI/npm packages. We can't measure their download-based adoption, which undermines hype-ratio analysis — our strongest differentiator.

**Proposed solution:**
- Integrate the [VS Code Marketplace API](https://marketplace.visualstudio.com/_apis/public/gallery) to pull install counts, ratings, and version history
- Add a `vscode_extension` column to `projects` (extension ID)
- Create a `vscode_snapshots` table: `project_id, snapshot_date, installs, rating, rating_count`
- Include VS Code installs in the hype-ratio calculation alongside PyPI/npm/Docker

**Implementation notes:**
- The Marketplace API is unauthenticated and rate-limited but workable for ~50 extensions
- JetBrains Marketplace is a secondary target (same pattern, different API)
- Map extensions to existing projects where possible (Cline → cline project)

**Effort:** Medium (new data source, new table, ingestion job)

---

### 2.2 Python `package_deps` ingestion

**Problem:** The `package_deps` table only has data for npm packages. Python dependency graphs are missing for all projects, which blocks dependency analysis — a high-value signal for tool selection recommendations.

**Evidence:** The Promptfoo dependency analysis was compelling (85 production deps, revealing architectural decisions), but we could only do it for one tool because it's the only npm-based eval framework.

**Proposed solution:**
- Parse `pyproject.toml`, `setup.py`, `setup.cfg`, and `requirements.txt` from GitHub for all curated projects with a `pypi_package`
- Populate `package_deps` with `source = 'pypi'`
- Prioritize: eval, agent, and framework categories first (highest value for research)
- Run as a batch job after GitHub snapshot ingestion

**Implementation notes:**
- `pyproject.toml` (PEP 621) is the modern standard — parse `[project.dependencies]`
- Fall back to `setup.cfg` `[options] install_requires` or `requirements.txt`
- Skip version specifiers for now, just capture dependency names
- Consider using the PyPI JSON API (`/pypi/{package}/json`) for the `requires_dist` field as an alternative to parsing repo files

**Effort:** Medium (file parsing + batch job)

---

### 2.3 Dependency reverse-lookup

**Problem:** We track what projects depend on (forward graph), but can't answer "which projects depend on X?" (reverse graph). This is valuable for understanding a library's downstream impact.

**Proposed solution:**
- This is a query pattern, not a data gap — the data exists in `package_deps`
- Create a helper view or API endpoint:
  ```sql
  SELECT pd.dep_name, COUNT(DISTINCT pd.repo_id) as dependent_repos,
    STRING_AGG(ar.full_name, ', ' ORDER BY ar.stars DESC) as top_dependents
  FROM package_deps pd
  JOIN ai_repos ar ON pd.repo_id = ar.id
  GROUP BY pd.dep_name
  ORDER BY dependent_repos DESC;
  ```
- Expose via REST API as `/v1/dependencies/{package_name}/dependents`

**Effort:** Low (view + API endpoint, data already exists once 2.2 is done)

---

### 2.4 Tutorial/demo repo classification

**Problem:** PT-Edge metrics (downloads, lifecycle stage) don't apply well to tutorial/demo repos. Awesome-lists and example collections get flagged as "no downloads" when that's expected behavior, not a negative signal.

**Proposed solution:**
- Add a `repo_type` enum to `ai_repos`: `library`, `tool`, `tutorial`, `awesome-list`, `model`, `dataset`
- Classify based on heuristics: repo name contains "awesome-", README structure (list of links), absence of `setup.py`/`package.json`, topics array contains "tutorial" or "examples"
- Exclude tutorial/awesome-list repos from hype-ratio calculations
- Display repo_type in API responses so consumers can filter

**Effort:** Low (new column + classification heuristics)

---

### 2.5 Closed-source project tracking

**Problem:** Major commercial AI tools (Devin, Windsurf, Cursor) have no public repos. They're invisible in our data but relevant to landscape analysis.

**Proposed solution:**
- Create a `commercial_projects` table: `name, url, category, description, pricing_model, last_verified_at`
- Manually curate ~20-30 significant closed-source projects
- Don't attempt to track metrics — just maintain a reference list with known features
- Surface in API responses with a `source: 'curated'` flag and no metrics

**Effort:** Low (manual table, no automation needed)

---

## Phase 3: New Data Sources

Each adds a new platform or signal type to the tracking index.

### 3.1 Academic paper tracking

**Problem:** No arXiv, Semantic Scholar, or citation data. AI research papers are a core content type for newsletters and analysts, and many open-source projects originate from papers.

**Proposed solution:**
- Integrate Semantic Scholar API (free, 100 req/sec) to track AI papers
- Create `papers` table: `semantic_scholar_id, arxiv_id, title, authors, abstract, venue, citation_count, publication_date, discovered_at`
- Link papers to projects where possible (many READMEs cite their paper)
- Create `paper_snapshots` for citation count time series
- Scope: start with papers linked to tracked projects, expand to top-cited AI papers

**Implementation notes:**
- Semantic Scholar's API is well-documented and generous with rate limits
- The paper→project link can be bootstrapped by searching for repo URLs in paper abstracts/code links
- ArXiv RSS feeds can supplement for discovery of new papers

**Effort:** High (new data source, new tables, linking logic)

---

### 3.2 Social signal aggregation

**Problem:** Twitter/X and Reddit are major discovery channels for AI tools. We only track Hacker News. Projects can go viral on social media before showing up in our star deltas.

**Proposed solution:**
- **Phase A (Reddit):** Reddit's API is accessible and well-structured. Track mentions of tracked projects in r/MachineLearning, r/LocalLLaMA, r/artificial, r/ChatGPT. Create `reddit_posts` table mirroring `hn_posts` structure.
- **Phase B (Twitter/X):** More complex due to API costs and access restrictions. Consider tracking via Nitter mirrors or the Academic Research API if available. Lower priority than Reddit.

**Implementation notes:**
- Reddit API requires OAuth but is free for moderate usage
- Start with keyword matching against project names in post titles
- De-duplicate carefully (project names like "agent" or "claude" have high false-positive rates)

**Effort:** Medium-High (Reddit is medium, Twitter/X is high)

---

### 3.3 Download count methodology documentation

**Problem:** PyPI and Docker Hub download counts include CI/CD automation, bots, and transitive dependency pulls. Raw numbers overstate human-initiated adoption. Without methodology notes, data consumers may draw incorrect conclusions.

**Proposed solution:**
- Add a `/v1/methodology` endpoint documenting what each metric includes and excludes
- For download counts specifically:
  - Note that PyPI counts include CI/CD pipelines and mirror pulls
  - Note that Docker Hub counts include automated pulls from orchestrators
  - Consider developing an "adjusted downloads" estimate: `raw_downloads / known_ci_multiplier` based on package type
- Add a `methodology` field to API responses for download metrics
- Document the lifecycle stage algorithm (inputs, thresholds, update frequency)

**Effort:** Low (documentation + optional API field)

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

| Phase | Items | Total effort | Unlocks |
|-------|------:|:-------------|:--------|
| 1. Data Integrity | 3 | Low-Medium | Trustworthy existing data |
| 2. Coverage Gaps | 5 | Low-Medium | Agent ecosystem, Python deps, repo classification |
| 3. New Data Sources | 3 | Medium-High | Papers, social signals, methodology transparency |
| 4. Enhanced Signals | 6 | Medium-High | Velocity detection, contributor health, China, MCP taxonomy, qualitative layer |

**Recommended execution order within each phase:**
- Phase 1: 1.1 (commits bug) → 1.2 (contributors) → 1.3 (retention)
- Phase 2: 2.2 (Python deps) → 2.1 (VS Code) → 2.3 (reverse lookup) → 2.4 (repo types) → 2.5 (commercial)
- Phase 3: 3.3 (methodology docs) → 3.2 (Reddit) → 3.1 (papers)
- Phase 4: 4.5 (MCP taxonomy) → 4.2 (contributor quality) → 4.1 (breakout detection) → 4.3 (maintainer health) → 4.4 (China) → 4.6 (qualitative)
