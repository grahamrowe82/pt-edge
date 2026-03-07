# The Edge — MVP Build Plan

## What we're building

An MCP server that makes Claude less wrong about the current state of AI. It pulls primary sources (release notes, GitHub activity, download stats, HN posts), computes metrics nobody publishes (hype-to-adoption ratio, momentum, lab velocity), and lets practitioners submit corrections when Claude gets something wrong. The corrections stick.

Same stack as signal-cascade: Python, FastAPI, fastmcp, PostgreSQL, Alembic, deployed on Render.

## What "done" looks like

- MCP server running on Render
- ~100 key AI projects and ~10 labs seeded and tracked
- Daily ingest: GitHub stats, PyPI downloads, releases, HN posts
- Derived metrics: momentum, hype-to-adoption ratio, lab velocity
- Claude can answer "what actually shipped this week", "is X hype or real adoption", "which lab is shipping fastest"
- Practitioners can submit corrections through Claude, and those corrections persist

---

## Schema

### Core tables

#### `labs`
The organisations doing the work.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| name | text | "Anthropic", "OpenAI", etc. |
| slug | text unique | "anthropic", "openai" |
| url | text | Main website |
| blog_url | text | nullable |
| github_org | text | nullable, e.g. "anthropics" |
| created_at | timestamptz | default now() |

Seed ~10: Anthropic, OpenAI, Google DeepMind, Meta AI, Mistral, Cohere, Stability AI, Hugging Face, Together AI, Groq.

#### `projects`
The repos, tools, frameworks, and models we track.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| name | text | "Claude Code", "vllm", "ollama" |
| slug | text unique | "claude-code", "vllm", "ollama" |
| category | text | model, framework, tool, library, infra, agent |
| lab_id | int FK | nullable — not everything belongs to a lab |
| github_owner | text | nullable |
| github_repo | text | nullable |
| pypi_package | text | nullable |
| npm_package | text | nullable |
| description | text | one-liner |
| url | text | nullable |
| is_active | bool | default true |
| created_at | timestamptz | |
| updated_at | timestamptz | |

Seed ~100 projects across categories: major models (GPT-4, Claude, Gemini, Llama, Mistral), frameworks (LangChain, LlamaIndex, DSPy, CrewAI, Haystack), inference (vLLM, Ollama, llama.cpp, TGI), tools (Cursor, Claude Code, Copilot, Aider), libraries (transformers, openai-python, anthropic-sdk), infra (Modal, Replicate, Together), agents (AutoGPT, OpenDevin, SWE-agent).

#### `github_snapshots`
Point-in-time captures of GitHub repo state. One row per project per day.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| project_id | int FK | |
| captured_at | timestamptz | |
| stars | int | |
| forks | int | |
| open_issues | int | |
| watchers | int | |
| commits_30d | int | commits in last 30 days |
| contributors | int | total contributor count |
| last_commit_at | timestamptz | most recent commit |
| license | text | nullable |

Unique constraint: `(project_id, captured_at::date)` — one snapshot per project per day.

#### `download_snapshots`
Package download stats over time.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| project_id | int FK | |
| captured_at | timestamptz | |
| source | text | "pypi", "npm" |
| downloads_daily | bigint | last day |
| downloads_weekly | bigint | last 7 days |
| downloads_monthly | bigint | last 30 days |

Unique constraint: `(project_id, source, captured_at::date)`.

#### `releases`
Shipped things. From GitHub releases API, lab blogs, changelogs.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| project_id | int FK | nullable |
| lab_id | int FK | nullable |
| version | text | nullable — not everything is versioned |
| title | text | |
| summary | text | Claude-generated summary of release notes |
| body | text | raw release notes / changelog entry |
| url | text | link to release |
| released_at | timestamptz | when it shipped |
| captured_at | timestamptz | when we ingested it |
| source | text | "github", "blog", "changelog" |

Unique constraint: `(url)` — deduplicate by URL.

#### `hn_posts`
Hacker News signal. Filtered to AI-relevant posts.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| hn_id | int unique | HN item ID |
| title | text | |
| url | text | nullable (some are Ask HN) |
| author | text | |
| points | int | |
| num_comments | int | |
| post_type | text | "show", "ask", "link" |
| posted_at | timestamptz | |
| captured_at | timestamptz | |
| project_id | int FK | nullable — linked if we can match |

#### `corrections`
The community layer. What makes this compound.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| topic | text | what this is about — a project, a claim, a trend |
| correction | text | the actual correction |
| context | text | nullable — what Claude said that was wrong |
| submitted_by | text | nullable — contributor identifier |
| submitted_at | timestamptz | default now() |
| status | text | "active", "superseded", "rejected" |
| upvotes | int | default 0 — other users confirming |
| tags | text[] | for categorisation |

Index on `topic`, full-text index on `correction`.

#### `tool_usage`
Same pattern as signal-cascade. Fire-and-forget analytics.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| tool_name | text | |
| params | jsonb | |
| duration_ms | int | |
| success | bool | |
| error_message | text | nullable |
| result_size | int | |
| created_at | timestamptz | |

#### `sync_log`
Ingest audit trail.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| sync_type | text | "github", "downloads", "releases", "hn", "views" |
| status | text | "success", "failed" |
| records_written | int | |
| error_message | text | nullable |
| started_at | timestamptz | |
| finished_at | timestamptz | |

### Materialized views

#### `mv_momentum`
Rate of change in adoption signals. The leading indicator.

```sql
-- Stars velocity: compare latest snapshot to 7 and 30 days ago
-- Download velocity: same
-- Output: project_id, stars_7d_delta, stars_30d_delta,
--         downloads_7d_delta, downloads_30d_delta,
--         stars_velocity (% change), downloads_velocity (% change)
```

#### `mv_hype_ratio`
The metric nobody publishes. Stars / monthly downloads.

```sql
-- High ratio = lots of excitement, not much real use (hype)
-- Low ratio = quiet adoption, nobody's written the explainer yet (signal)
-- Output: project_id, stars, monthly_downloads, hype_ratio,
--         hype_bucket ("hype", "balanced", "quiet_adoption", "no_data")
```

#### `mv_lab_velocity`
How fast are labs actually shipping?

```sql
-- Releases per lab per 30-day window
-- Commit activity across lab's projects
-- Output: lab_id, releases_30d, releases_90d,
--         avg_days_between_releases, is_accelerating (bool)
```

#### `mv_project_summary`
One-stop view for any project. Joins latest snapshot, downloads, momentum, hype ratio.

```sql
-- Output: project_id, name, category, lab_name,
--         stars, forks, monthly_downloads,
--         stars_velocity, downloads_velocity,
--         hype_ratio, hype_bucket,
--         last_release_at, last_release_title,
--         days_since_last_release, last_commit_at,
--         correction_count
```

---

## MCP Tools

### Intelligence tools (the main value)

#### `whats_new(days: int = 7) -> str`
"What actually shipped this week?"

Returns: recent releases across all tracked projects and labs, sorted by date. Grouped by lab. Includes release summaries. Flags anything with unusual momentum.

#### `project_pulse(project: str) -> str`
Deep dive on a specific project.

Returns: latest GitHub stats, download trends, momentum, hype ratio, recent releases, last commit, relevant HN posts, active corrections. Everything Claude needs to give a current, grounded answer about this project.

#### `lab_pulse(lab: str) -> str`
What is this lab actually shipping?

Returns: recent releases across all tracked projects for this lab, release cadence, whether they're accelerating or decelerating, commit activity. Facts, not press releases.

#### `trending(category: str = None, window: str = "7d") -> str`
What's accelerating right now?

Returns: projects ranked by momentum (stars velocity + downloads velocity), optionally filtered by category. The things that are moving, not the things that are big.

#### `hype_check(project: str) -> str`
Is this hype or real adoption?

Returns: the hype-to-adoption ratio (stars / downloads), how it compares to similar projects, trend over time. One number that cuts through the noise.

### Data tools

#### `query(sql: str) -> str`
Read-only SQL. Same pattern as signal-cascade. Max 1000 rows.

#### `describe_schema() -> str`
Table and column listing so Claude can write informed queries.

### Community tools

#### `submit_correction(topic: str, correction: str, context: str = None) -> str`
The correction engine. Claude drafts it, the user confirms.

Topic is free-text but should match a project name, lab name, or concept. Context captures what Claude said that was wrong (so corrections are traceable).

#### `upvote_correction(correction_id: int) -> str`
"Yeah, that's right." Lightweight confirmation from another practitioner.

#### `list_corrections(topic: str = None, status: str = "active") -> str`
View active corrections, optionally filtered by topic.

### Meta tools

#### `about() -> str`
What this server is, what it tracks, how corrections work, when data was last updated. The orientation tool.

---

## Ingest Pipeline

### GitHub ingest (`ingest/github.py`)
- GitHub REST API with token auth
- Rate limit: 5000 req/hr with token
- For each active project with github_owner + github_repo:
  - GET `/repos/{owner}/{repo}` — stars, forks, issues, watchers, license, last push
  - GET `/repos/{owner}/{repo}/stats/commit_activity` — weekly commit counts (last year)
  - GET `/repos/{owner}/{repo}/contributors?per_page=1&anon=true` — total contributors (from Link header)
- Insert into `github_snapshots`
- Schedule: daily

### Downloads ingest (`ingest/downloads.py`)
- PyPI: `https://pypistats.org/api/packages/{package}/recent` — last day/week/month
  - Rate limit: 30 req/min
- npm: `https://api.npmjs.org/downloads/point/{period}/{package}`
  - Periods: last-day, last-week, last-month
- Insert into `download_snapshots`
- Schedule: daily

### Releases ingest (`ingest/releases.py`)
- GitHub Releases API: `GET /repos/{owner}/{repo}/releases?per_page=10`
- For each release:
  - Capture version, title, body (markdown), url, published_at
  - Generate summary from body (Claude or simple truncation for MVP)
- Deduplicate by URL
- Schedule: every 6 hours, or on-demand via `refresh_project` tool

### HN ingest (`ingest/hn.py`)
- Algolia HN API: `https://hn.algolia.com/api/v1/search_by_date`
- Query: AI-related terms (LLM, GPT, Claude, Anthropic, OpenAI, etc.)
- Filter: last 7 days, min 10 points
- Match to projects where possible (fuzzy on title)
- Schedule: every 6 hours

### View refresh (`views/refresh.py`)
- Same tiered refresh pattern as signal-cascade
- Tier 0: mv_momentum, mv_hype_ratio, mv_lab_velocity
- Tier 1: mv_project_summary (depends on all tier 0)
- Schedule: after each ingest cycle

---

## Project Structure

```
pt-edge/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI + MCP mount
│   ├── db.py                    # SQLAlchemy engine/session
│   ├── settings.py              # Pydantic BaseSettings
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py              # DeclarativeBase
│   │   ├── core.py              # Lab, Project
│   │   ├── snapshots.py         # GitHubSnapshot, DownloadSnapshot
│   │   ├── content.py           # Release, HNPost
│   │   ├── community.py         # Correction
│   │   └── meta.py              # ToolUsage, SyncLog
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── github.py            # GitHub API client
│   │   ├── downloads.py         # PyPI + npm stats
│   │   ├── releases.py          # GitHub releases
│   │   ├── hn.py                # Hacker News via Algolia
│   │   └── runner.py            # Orchestrator
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── server.py            # MCP tool definitions
│   │   └── tracking.py          # Usage tracking decorator
│   ├── views/
│   │   ├── __init__.py
│   │   └── refresh.py           # Materialized view refresh
│   └── migrations/
│       ├── env.py
│       └── versions/
├── scripts/
│   ├── seed.py                  # Seed labs + projects
│   ├── ingest_all.py            # Run full ingest cycle
│   ├── ingest_github.py         # GitHub stats only
│   ├── ingest_downloads.py      # Download stats only
│   ├── ingest_releases.py       # Releases only
│   ├── ingest_hn.py             # HN posts only
│   └── refresh_views.py         # Refresh materialized views
├── seeds/
│   ├── labs.json                # Lab definitions
│   └── projects.json            # Project definitions (~100)
├── pyproject.toml
├── requirements.txt
├── alembic.ini
├── Dockerfile
├── docker-compose.yml           # Local Postgres
├── render.yaml
├── .env.example
├── .gitignore
└── PLAN.md
```

---

## Build Sequence

### Day 1 — Foundation + GitHub pipeline

**Morning: Scaffold**
1. Init git repo, pyproject.toml, requirements.txt
2. Copy and adapt from signal-cascade: db.py, settings.py, main.py, base model, Dockerfile, docker-compose.yml, .env.example, .gitignore
3. Settings: DATABASE_URL, API_TOKEN, GITHUB_TOKEN
4. FastAPI app with healthz endpoint
5. Alembic init

**Afternoon: Core schema + GitHub ingest**
1. Models: Lab, Project, GitHubSnapshot, SyncLog
2. First migration: create tables
3. Seed data: labs.json (~10 labs), projects.json (~100 projects with GitHub coords)
4. `scripts/seed.py` — load from JSON
5. GitHub ingest client:
   - Async httpx with token auth
   - Rate-limit aware (check X-RateLimit-Remaining header)
   - Fetch repo stats + commit activity + contributor count
6. `scripts/ingest_github.py` — run for all projects
7. Test: seed + ingest + verify data in Postgres

### Day 2 — Downloads, releases, HN, views

**Morning: More ingest**
1. Models: DownloadSnapshot, Release, HNPost
2. Migration: add tables
3. Downloads ingest: PyPI stats API (and npm for JS projects)
4. Releases ingest: GitHub Releases API, store raw + summary
5. HN ingest: Algolia search API, AI keyword filter
6. `scripts/ingest_all.py` — orchestrate full cycle

**Afternoon: Materialized views + derived metrics**
1. mv_momentum — stars/downloads velocity (7d and 30d deltas)
2. mv_hype_ratio — stars / monthly downloads
3. mv_lab_velocity — release frequency per lab
4. mv_project_summary — unified view
5. Migration: create all views
6. `scripts/refresh_views.py`
7. Test: verify derived metrics make sense

### Day 3 — MCP tools + corrections + deploy

**Morning: MCP server**
1. Copy tracking.py from signal-cascade (fire-and-forget usage logging)
2. Model: ToolUsage, Correction
3. Migration: add tables
4. Implement tools:
   - `about()` — orientation
   - `describe_schema()` — table listing
   - `query(sql)` — read-only SQL
   - `whats_new(days)` — recent releases + trending
   - `project_pulse(project)` — deep dive
   - `lab_pulse(lab)` — lab shipping cadence
   - `trending(category)` — momentum ranking
   - `hype_check(project)` — the ratio
   - `submit_correction(topic, correction, context)` — the engine
   - `upvote_correction(correction_id)` — confirmation
   - `list_corrections(topic)` — browse corrections
5. Bearer token auth middleware (same as signal-cascade)

**Afternoon: Deploy + polish**
1. render.yaml — web service + managed Postgres
2. Push to GitHub, connect Render
3. Run seed + full ingest on production
4. Refresh views
5. Connect Claude Desktop to production MCP endpoint
6. Smoke test: ask Claude real questions, verify answers are grounded

---

## Seed Data

### Labs (~10)

```json
[
  {"name": "Anthropic", "slug": "anthropic", "github_org": "anthropics"},
  {"name": "OpenAI", "slug": "openai", "github_org": "openai"},
  {"name": "Google DeepMind", "slug": "google-deepmind", "github_org": "google-deepmind"},
  {"name": "Meta AI", "slug": "meta-ai", "github_org": "facebookresearch"},
  {"name": "Mistral AI", "slug": "mistral", "github_org": "mistralai"},
  {"name": "Cohere", "slug": "cohere", "github_org": "cohere-ai"},
  {"name": "Hugging Face", "slug": "hugging-face", "github_org": "huggingface"},
  {"name": "Stability AI", "slug": "stability-ai", "github_org": "Stability-AI"},
  {"name": "Together AI", "slug": "together-ai", "github_org": "togethercomputer"},
  {"name": "Groq", "slug": "groq", "github_org": "groq"}
]
```

### Projects (~100, representative sample)

**Models & APIs:**
claude, gpt-4, gemini, llama, mistral-models, command-r, stable-diffusion, flux, phi, qwen, deepseek, gemma

**Frameworks:**
langchain, llamaindex, dspy, crewai, haystack, semantic-kernel, autogen, pydantic-ai, smolagents, mastra

**Inference:**
vllm, ollama, llama-cpp, tgi, sglang, mlx, exllamav2, tensorrt-llm

**Tools:**
cursor, claude-code, aider, continue-dev, cody, open-interpreter, fabric

**Libraries:**
transformers, openai-python, anthropic-sdk, litellm, instructor, outlines, guidance, lmstudio

**Infra:**
modal, replicate, together-platform, anyscale, fireworks-ai, chromadb, qdrant, weaviate, pgvector, lancedb

**Agents:**
opendevin, swe-agent, devika, gpt-engineer, sweep, cognition-devin

**Evaluation:**
lm-eval-harness, ragas, promptfoo, giskard

---

## Future (post-MVP, not now)

- **arXiv papers** — daily new AI papers, linked to labs/projects
- **Lab blog monitoring** — RSS/scrape for announcements not on GitHub
- **Multi-user corrections** — API keys per user, attribution
- **Correction confidence** — weighted by contributor track record
- **Weekly digest tool** — `weekly_briefing()` summarising the week
- **Benchmark tracking** — MMLU, HumanEval, etc. scores over time
- **Model pricing tracker** — $/token across providers over time
- **Comparison tools** — `compare(project_a, project_b)` head-to-head
- **Scheduled ingest** — cron job or Render cron, not manual scripts
- **Embeddings on corrections** — semantic search over community knowledge

---

## Key Decisions

1. **Same stack as signal-cascade** — no reason to change what works. Python, FastAPI, fastmcp, PostgreSQL, Alembic, Render.

2. **Snapshots over diffs** — store full point-in-time snapshots rather than deltas. More storage, much simpler queries. Diffs are computed in views.

3. **Free-text topics on corrections** — not forcing corrections to link to a specific project_id. People will correct claims about concepts, trends, comparisons — not just project facts. Full-text search handles retrieval.

4. **Claude generates release summaries** — the raw body of a GitHub release can be thousands of lines of changelog. Store both raw and summary. For MVP, summary can be simple truncation; Claude can summarise on read.

5. **No embeddings for MVP** — pure SQL, same as signal-cascade. Keyword matching and full-text search are enough for a corpus of this size. Add pgvector later if needed.

6. **Daily ingest is fine** — we're not building a real-time feed. Daily GitHub + downloads, 6-hourly releases + HN. The value is in the derived metrics and corrections, not millisecond freshness.

7. **~100 projects is enough** — better to have good coverage of 100 important projects than noisy coverage of 1000. The seed list is an editorial choice and it matters. Easy to add more later.
