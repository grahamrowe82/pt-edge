# Worker → DB → Site: End-to-End Audit

*6 April 2026*

**Implementation plan:** [audit-implementation-plan.md](audit-implementation-plan.md) — 12 PRs across 4 phases to close every gap.

The worker runs 36 task types. Each writes data to the database. This audit traces every task through to the live site at mcp.phasetransitions.ai to identify what data is being generated but never displayed, what tasks are failing, and where the pipeline is broken.

---

## Method

- Task types enumerated from the `tasks` table (last 7 days)
- DB tables counted directly via psql
- Live site checked via HTTP requests to mcp.phasetransitions.ai
- Each task classified as: reaches site, doesn't reach site, or indirect

---

## Discovery & Ingestion Tasks

| Task | Writes to | On site? | DB count | Notes |
|------|-----------|----------|----------|-------|
| `discover_ai_repos` | `ai_repos` (new rows) | **YES** | 245,616 active | Core discovery — repos appear in domain listings |
| `fetch_github` | `projects`, `github_snapshots` | **NO** | ~160 projects | Legacy pipeline for tracked projects, not used by ai_repos site |
| `fetch_readme` | `raw_cache` (github_readme) | Indirect | 17,516 | Feeds `enrich_summary` which writes to `ai_repos` |
| `backfill_created_at` | `ai_repos.created_at` | **YES** | 84,626 populated | Used in maturity score calculation |
| `fetch_ai_repo_commits` | `ai_repos.commits_30d` | **YES** | 3,329 populated | Shown as "30-day commits" on project pages |
| `fetch_ai_repo_downloads` | `ai_repos.pypi_package`, `npm_package`, `downloads_monthly` | **YES** | 7,378 with downloads | Shown as "Monthly downloads" on project pages |
| `fetch_releases` | `releases` | **NO** | 8,414 releases | Data collected but no section on project pages |
| `fetch_models` | `hf_models`, `hf_datasets` | **NO** | 25,656 models + 61,256 datasets | Collected but no pages or project linking on site |
| `fetch_api_specs` | `public_apis` | **NO** (site) | 2,529 APIs | Served via MCP `find_public_api` tool only |
| `fetch_candidate_watchlist` | `project_candidates` | **NO** | — | Internal pipeline |
| `fetch_newsletters` | `newsletter_mentions` | **NO** | — | Collected but not rendered |

---

## LLM Enrichment Tasks (Gemini)

| Task | Writes to | On site? | DB count | Notes |
|------|-----------|----------|----------|-------|
| `enrich_summary` | `ai_repos.ai_summary`, `use_this_if`, `not_ideal_if`, `problem_domains` | **PARTIAL** | 15,519 summaries; 4,756 with use_this_if | `ai_summary` shown as project description. **`use_this_if` and `not_ideal_if` exist in the MV but the template does not render them.** |
| `enrich_repo_brief` | `repo_briefs.title`, `summary`, `evidence` | **NO** | 5,603 briefs | **Completely disconnected.** MVs don't join to `repo_briefs`. Template has no brief section. Rich quality assessments with structured evidence sitting unused. |
| `enrich_comparison` | `comparison_sentences.sentence` | **YES** | 12,897 sentences | Shown as comparison links on project pages |
| `enrich_project_brief` | `project_briefs.title`, `summary`, `evidence` | **NO** | 99 briefs | Separate table from `repo_briefs`, also disconnected from site |
| `enrich_domain_brief` | `domain_briefs.title`, `summary`, `evidence` | **NO** | 17 briefs (one per domain) | Domain landing pages have no brief section. Each domain has a generated landscape summary that never appears. |
| `enrich_landscape_brief` | `landscape_briefs` | **NO** | 0 rows | Task keeps failing — empty table |
| `enrich_subcategory` | `ai_repos.subcategory` | **YES** | 235,830 populated | Powers category grouping on domain pages |
| `enrich_stack_layer` | `ai_repos` stack classification | **UNKNOWN** | Task failing | Column may not exist |
| `enrich_hn_match` | `hn_posts` project linking | **NO** | 3,882 HN posts | Posts collected but no "community discussion" section on project pages |
| `enrich_package_detect` | `ai_repos.pypi_package` etc | **YES** (indirect) | Feeds download detection | |

---

## Compute & Infrastructure Tasks

| Task | Writes to | On site? | Notes |
|------|-----------|----------|-------|
| `compute_mv_refresh` | Refreshes 35 materialised views | **YES** — but currently failing | **CRITICAL.** MVs are the data source for the entire site. If this doesn't run, site shows stale data. |
| `compute_embeddings` | `ai_repos.embedding` | **NO** (directly) | Powers MCP `find_ai_tool` semantic search. 238,163 embedded. |
| `compute_content_budget` | `content_budget` | **NO** | Internal allocation — but currently failing, which blocks all budget-gated enrichment |
| `compute_structural` | `structural_cache` | **NO** | 17 rows, internal analysis |
| `compute_coview` | `coview_pairs` | **NO** | 30 pairs, not on site |
| `compute_briefing_refresh` | `briefings` | **NO** (site) | 38 briefings served via MCP `briefing()` tool only |
| `compute_domain_reassign` | `ai_repos.domain` corrections | **YES** (indirect) | Fixes misclassified repos |
| `compute_project_linking` | Cross-table links | Indirect | |
| `compute_hn_backfill` | `hn_posts` | **NO** | |
| `compute_hn_lab_backfill` | `hn_posts` lab linking | **NO** | |
| `compute_v2ex_lab_backfill` | `v2ex_posts` lab linking | **NO** | |
| `export_static_site` | Triggers site rebuild on Render | **YES** — but currently failing | **CRITICAL.** Site doesn't rebuild without this. |
| `export_dataset` | Dataset file export | **NO** | |
| `import_gsc` | `gsc_search_data` | **NO** | 1,342 rows, internal SEO analytics |
| `import_umami` | `umami_page_stats` | **NO** | 72 rows, internal traffic analytics |

---

## Failing Tasks

These tasks have failed recently and are blocking parts of the pipeline:

| Task | Failures | Pending | Impact |
|------|----------|---------|--------|
| `compute_mv_refresh` | 1 | 1 | **CRITICAL** — materialised views not refreshing, site shows stale scores |
| `export_static_site` | 1 | 1 | **CRITICAL** — site not rebuilding with new data |
| `compute_content_budget` | 1 | 0 | Blocks all budget-gated enrichment (summaries, comparisons, repo briefs) |
| `enrich_domain_brief` | 16 | 17 | Domain briefs failing consistently |
| `enrich_stack_layer` | 1 | 0 | Stack layer classification not running |
| `enrich_hn_match` | 1 | 0 | HN post matching not running |
| `enrich_package_detect` | 1 | 0 | Package detection not running |

---

## Data in the Dark

Content the worker generates that never reaches a user (site visitor or AI agent):

| Data | DB rows | What it contains | Why it matters |
|------|---------|-----------------|----------------|
| **repo_briefs** | 5,603 | Quality assessments with title, summary, and structured evidence (scores, metrics, dates) | This is the richest content we generate. An AI agent landing on a project page gets a score and raw metrics but no analytical assessment. |
| **project_briefs** | 99 | Detailed project analyses with peer context | High-effort LLM output, never displayed |
| **domain_briefs** | 17 | One landscape summary per domain ("MCP Landscape: n8n and FastMCP Dominate...") | Every domain landing page could have an authoritative intro. Instead they just list projects. |
| **use_this_if / not_ideal_if** | 4,756 | Decision guidance: "Use this when you need X" / "Not ideal if you need Y" | Fields exist in the MV. Template just doesn't render them. Easiest gap to close. |
| **releases** | 8,414 | Version numbers, dates, changelogs | Project pages show "last pushed" but not release history |
| **hn_posts** | 3,882 | Hacker News discussion links with scores and dates | Community signal — shows real-world interest beyond GitHub stars |
| **v2ex_posts** | 757 | Chinese developer forum discussions | Additional community signal |
| **hf_models** | 25,656 | HuggingFace model cards associated with repos | Could show "Models built with this tool" |
| **hf_datasets** | 61,256 | HuggingFace datasets associated with repos | Could show "Datasets for this tool" |
| **newsletter_mentions** | — | Newsletter coverage of projects | Social proof |
| **public_apis** | 2,529 | API directory with OpenAPI specs | Only served via MCP, no site pages |
| **briefings** | 38 | Domain briefings (weekly summaries) | Only served via MCP tool |
| **landscape_briefs** | 0 | Ecosystem layer analyses | Task failing, never generated |

---

## Enrichment Coverage

How much of the 245,616 active repos have been enriched:

| Field | Populated | Coverage | Notes |
|-------|-----------|----------|-------|
| embedding | 238,163 | 97.0% | Near-complete |
| subcategory | 235,830 | 96.0% | Near-complete |
| description | 238,163 | 97.0% | From GitHub |
| created_at | 84,626 | 34.5% | Backfill in progress |
| cached README | 17,516 | 7.1% | Feeds summary pipeline |
| ai_summary | 15,519 | 6.3% | Gemini-generated |
| downloads_monthly | 7,378 | 3.0% | Package repos only |
| repo_briefs | 5,603 | 2.3% | Gemini-generated |
| use_this_if | 4,756 | 1.9% | Gemini-generated |
| commits_30d | 3,329 | 1.4% | GitHub API |

---

## What the Site Currently Shows

### Project page (e.g. `/llm-tools/servers/BerriAI/litellm/`)

- Project name and description (from `ai_repos.description` or `ai_summary`)
- Quality score and tier (from MV: maintenance/adoption/maturity/community)
- Key metrics: stars, forks, downloads, commits_30d, reverse dependents, dependencies
- Language, license, last pushed date
- Category with tool count
- Related tools (5 similar projects)
- Comparison links (from `comparison_sentences`)
- "Featured in" deep dive links (from `deep_dives`)
- API access link

**Not shown:** repo brief assessment, use_this_if/not_ideal_if guidance, releases, HN discussions, HuggingFace models/datasets

### Domain landing page (e.g. `/llm-tools/`)

- Domain description and total count
- Quality tier breakdown
- Top 20 tools table
- Category grid with counts
- Popular comparisons

**Not shown:** domain brief (landscape analysis), trending/breakout repos

### Deep dive pages (e.g. `/insights/agent-governance-landscape/`)

- Full editorial content with live metrics
- Working end-to-end (17 deep dives live)

---

## Priority Actions

### P0 — Fix broken pipeline

1. Fix `compute_mv_refresh` — site is showing stale data
2. Fix `export_static_site` — site isn't rebuilding
3. Fix `compute_content_budget` — blocks all LLM enrichment

### P1 — Display data we already have

4. Render `use_this_if` / `not_ideal_if` on project pages — template change only, fields already in MV
5. Wire `repo_briefs` to project pages — join in MV or query in site gen, add template section
6. Wire `domain_briefs` to domain landing pages — add landscape summary section

### P2 — Surface community signals

7. Add HN discussion links to project pages
8. Add release history section to project pages

### P3 — Connect HuggingFace ecosystem

9. Link `hf_models` / `hf_datasets` to relevant project pages
10. Create public API directory pages
