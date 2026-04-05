# Expanding the PT-Edge Universe

*5 April 2026*

**Implementation plan:** [discovery-expansion-implementation.md](discovery-expansion-implementation.md) — PR sequence, file-level scope, and dependency graph.

## The Problem

PT-Edge tracks 248,000 AI repos. The addressable universe on GitHub alone is 1.5-2 million. We cover 12-20% of what exists. Every repo we're missing is a page we can't serve to an AI agent, a comparison we can't make, a trend we can't detect.

Meanwhile, our GitHub API budget — 120,000 REST calls/day and 43,200 Search calls/day — is 88% idle. We spend 14,500 calls/day on maintenance, backfills, and a weekly discovery crawl. The remaining 105,000 calls sit unused.

The enrichment pipeline (README caching, problem briefs, comparisons) has a 248K-repo backlog that will take 55 days to clear at current speed. At full budget utilisation it would take 4 days.

This is a resource allocation failure, not a technical limitation.

## The Goal

1. **Clear enrichment backlogs in days, not months** — every repo should have a cached README, a problem brief, and quality scores within a week of discovery
2. **Expand from 248K to 500K+ repos** by adding missing domains and new discovery channels
3. **Sustain 10-20K new discoveries per week** through continuous discovery, not weekly batch crawls
4. **Maintain 30-40% API headroom** — never saturate the budget, always leave room for maintenance and spikes

## Current State

### Budget utilisation

| Resource | Daily budget | Currently used | Utilisation |
|----------|-------------|----------------|-------------|
| GitHub REST API | 120,000 | 14,500 | 12% |
| GitHub Search API | 43,200 | 430 | 1% |
| Gemini | 1,152,000 | ~30,000 | 3% |
| OpenAI (embeddings) | Effectively unlimited | ~5,000 | — |

### Discovery sources

| Source | Repos found | Frequency | Coverage |
|--------|-------------|-----------|----------|
| GitHub topic search (55 topics) | 247,810 | Weekly | 12-20% of universe |
| Trending | ~200/day | Daily | Catches breakouts |
| npm MCP | ~170/month | Daily | MCP-specific |
| Candidate promotion | ~50/month | Daily | High-star repos only |

### Enrichment backlogs

| Backlog | Size | Current rate | Time to clear |
|---------|------|-------------|---------------|
| README cache | 248,000 | 4,500/day | 55 days |
| created_at | 190,000 | 4,500/day | 42 days |
| Problem briefs | 234,000 | ~2,000/day | 117 days |
| Repo briefs | 248,000 | blocked until summaries exist | — |
| Comparison sentences | 7,000 | ~2,000/day | 3.5 days |

### Known blind spots

**Domains we don't search:** reinforcement learning, robotics, recommendation systems, time series/forecasting, graph neural networks, interpretability/XAI, federated learning, edge AI/TinyML, drug discovery/cheminformatics, audio AI/speech, game AI, quantum ML, climate/earth science AI, causal inference, simulation.

**Repos we can't see via topic search:** ~15-20% of GitHub AI repos lack topic tags. These are invisible to our current discovery regardless of how many topics we search. Older repos, academic code, non-English projects, and quick-publish experiments tend not to tag.

**Sources we don't use:** PyPI classifiers, npm tags, Papers with Code, awesome lists, dependency graphs, HuggingFace source repos, GitLab.

---

## Phase 1: Use What We Have

*Config changes only. No new code except tuning constants.*

### 1a. Remove the backlog throttle

The scheduler caps fine-grained tasks at 500 pending with 1,000 per batch, refilled every 15 minutes. At 4,500 claims/hour the worker runs dry between refills.

**Change:** Increase `PENDING_CAP` to 5,000 and `BATCH_LIMIT` to 5,000 for `fetch_readme` and `backfill_created_at`. The worker always has work available for the `github_api` slot.

**Impact:** README and created_at backlogs clear in 4 days instead of 55. The github_api budget goes from 12% to ~80% utilised during the backlog clearing period, then drops back as the backlog drains.

### 1b. Run discovery daily instead of weekly

`discover_ai_repos` currently runs with `staleness_hours=168` (weekly). The Saturday cron job is gone. The task queue can run it every day.

**Change:** Set `staleness_hours=24` for `discover_ai_repos` in the scheduler.

**Impact:** Discovery rate increases 7x for the same 3,000 calls per run. Incremental crawls (searching for repos pushed since the last run) become much more current — catching repos within 24 hours of their first push instead of within 7 days.

### 1c. Add missing domains

Expand the topic list in `ai_repos.py` to cover fields we're currently ignoring entirely.

**New domains and topics:**

| Domain | GitHub topics | Estimated repos |
|--------|-------------|----------------|
| `reinforcement-learning` | `reinforcement-learning`, `rl`, `deep-reinforcement-learning`, `gym`, `multi-agent-reinforcement-learning` | 15,000-30,000 |
| `robotics` | `robotics`, `ros`, `robot-learning`, `autonomous-driving`, `slam` | 10,000-20,000 |
| `recommendation-systems` | `recommender-system`, `collaborative-filtering`, `recommendation-engine`, `content-based-filtering` | 10,000-15,000 |
| `time-series` | `time-series`, `forecasting`, `time-series-analysis`, `anomaly-detection`, `predictive-analytics` | 8,000-12,000 |
| `graph-neural-networks` | `graph-neural-network`, `gnn`, `graph-learning`, `knowledge-graph`, `graph-convolutional-network` | 5,000-10,000 |
| `interpretability` | `explainability`, `interpretable-ml`, `xai`, `model-interpretability`, `feature-importance` | 5,000-8,000 |
| `federated-learning` | `federated-learning`, `privacy-preserving-ml`, `differential-privacy` | 3,000-5,000 |
| `edge-ai` | `tinyml`, `edge-ai`, `model-compression`, `quantization`, `pruning`, `knowledge-distillation` | 3,000-5,000 |
| `drug-discovery` | `drug-discovery`, `molecular-generation`, `cheminformatics`, `protein-folding`, `computational-biology` | 3,000-5,000 |
| `audio-ai` | `speech-synthesis`, `text-to-speech`, `audio-generation`, `music-generation`, `speech-recognition` | 5,000-10,000 |
| `simulation` | `physics-simulation`, `scientific-computing`, `numerical-methods`, `differentiable-programming` | 3,000-5,000 |

**Impact:** 70,000-125,000 new repos discovered over 2-3 weeks of daily crawls. Total repo count reaches 320K-370K.

**Prerequisite:** Each new domain needs a corresponding quality view (`mv_*_quality`) and an entry in `DOMAIN_VIEW_MAP`, `DOMAIN_CONFIG`, and `start.sh` for site generation. This is mechanical but not zero work.

### Phase 1 summary

| Metric | Before | After |
|--------|--------|-------|
| Backlog clear time | 55 days | 4 days |
| Discovery frequency | Weekly | Daily |
| Domains | 18 | 29 |
| Estimated repos | 248K | 320-370K |
| GitHub REST utilisation | 12% | 60-80% during backlog, 30% steady state |
| GitHub Search utilisation | 1% | 7% |

---

## Phase 2: New Discovery Channels

*New task types and handlers. Finds repos that topic search can't reach.*

### 2a. PyPI classifier discovery

PyPI packages are classified using trove classifiers. The classifier `Topic :: Scientific/Engineering :: Artificial Intelligence` contains thousands of packages, many of which have GitHub source URLs we don't track.

**How it works:**
1. Fetch the PyPI classifier page or use the Simple API to list packages under the AI classifier
2. For each package, resolve the source URL (from `project_urls` metadata)
3. Cross-reference against `ai_repos.full_name` — any repo not already tracked becomes a candidate
4. Create `backfill_created_at` + `fetch_readme` tasks for new discoveries

**Resource cost:** ~5,000 PyPI API calls (one per package to get metadata). No GitHub budget consumed for the discovery step itself.

**Expected yield:** 10,000-20,000 repos not already tracked. These are repos that have published packages (strong signal of real usage) but lack GitHub topic tags.

**Frequency:** Weekly. The PyPI ecosystem doesn't change fast enough to justify daily.

### 2b. Description-based GitHub search

Our current discovery searches by topic tag only. The GitHub Search API also supports `in:description` and `in:readme` qualifiers. This catches repos where the author described their project as AI-related but didn't add topic tags.

**How it works:**
1. Search GitHub for repos matching keywords in their description:
   - `"neural network" in:description language:python stars:>=5`
   - `"language model" in:description stars:>=5`
   - `"machine learning" in:description stars:>=10`
   - `"deep learning" in:description stars:>=5`
   - `"transformer model" in:description stars:>=5`
   - ~20 keyword variations
2. Apply the same adaptive sharding as `github_search.py` (star ranges, languages, date brackets)
3. Cross-reference against `ai_repos`, add new discoveries

**Resource cost:** ~5,000-10,000 Search API calls per run (well within the 43,200/day budget). Some REST calls to fetch metadata for new discoveries.

**Expected yield:** 20,000-50,000 repos not already tracked. This is the biggest single opportunity — the 15-20% of AI repos that don't have topic tags but do describe themselves as AI in their README or description.

**Frequency:** Weekly. The search results are fairly stable; new repos appear via the `pushed:>={cutoff}` incremental filter.

### 2c. Awesome list ingestion

GitHub hosts hundreds of curated "awesome" lists for AI/ML topics. These are manually curated by domain experts and contain high-quality repos that may not appear in topic searches.

**How it works:**
1. Maintain a list of ~20 awesome lists:
   - `sindresorhus/awesome` (master list)
   - `josephmisiti/awesome-machine-learning`
   - `keon/awesome-nlp`
   - `jbhuang0604/awesome-computer-vision`
   - `eugeneyan/applied-ml`
   - `dair-ai/ML-Papers-of-the-Week`
   - etc.
2. Fetch each list's README, parse Markdown for GitHub URLs
3. Cross-reference against `ai_repos`, add new discoveries as candidates

**Resource cost:** ~20 README fetches + ~5,000 metadata fetches for new repos. Negligible.

**Expected yield:** 5,000-10,000 repos, heavily biased toward high-quality, well-known projects. Many will already be tracked, but the ones that aren't are likely important.

**Frequency:** Monthly. These lists change slowly.

### 2d. HuggingFace source repo linking

We already track HuggingFace models and datasets. Many have `source` or `github` links in their metadata pointing to GitHub repos we may not track.

**How it works:**
1. Query `hf_models` and `hf_datasets` for entries with GitHub URLs in their metadata
2. Extract the repo slug
3. Cross-reference against `ai_repos`, add new discoveries

**Resource cost:** Database-only for the cross-reference. A few hundred GitHub calls for metadata on new discoveries.

**Expected yield:** 2,000-5,000 repos. These are repos that have associated ML models or datasets — strong signal of real research or production use.

**Frequency:** Weekly, after `fetch_hf_models` and `fetch_hf_datasets` run.

### Phase 2 summary

| Channel | Expected new repos | Resource cost | Frequency |
|---------|-------------------|---------------|-----------|
| PyPI classifiers | 10,000-20,000 | 5K PyPI calls | Weekly |
| Description search | 20,000-50,000 | 10K Search calls | Weekly |
| Awesome lists | 5,000-10,000 | 5K REST calls | Monthly |
| HuggingFace linking | 2,000-5,000 | ~500 REST calls | Weekly |
| **Total** | **37,000-85,000** | | |

Combined with Phase 1: **357K-455K repos.**

---

## Phase 3: Dependency-Based Discovery

*The deepest discovery channel. Finds repos by what they use, not what they say they are.*

### The insight

A repo that imports `torch`, `tensorflow`, `transformers`, `langchain`, or `openai` is almost certainly an AI project — regardless of whether it has topic tags, a meaningful description, or any GitHub stars at all. The dependency graph is the most honest signal of what a repo actually does.

### How it works

1. **Seed list:** Identify the ~50 most common AI framework packages (pytorch, tensorflow, transformers, langchain, openai, scikit-learn, keras, jax, spacy, huggingface-hub, chromadb, pinecone, weaviate, llamaindex, crewai, autogen, etc.)

2. **Reverse dependency lookup:** For each seed package, find all packages that depend on it:
   - PyPI: Use the Google BigQuery `pypi.distribution_metadata` dataset or Libraries.io API
   - npm: Use the npm API's dependents endpoint
   - This gives us package names, not repo URLs

3. **Repo resolution:** For each dependent package, resolve its source URL from the package registry metadata. Cross-reference against `ai_repos`.

4. **Quality filter:** Many dependent packages are trivial (tutorials, forks, one-file scripts). Filter by:
   - Has a GitHub source URL
   - ≥5 stars OR ≥100 monthly downloads
   - Not already in `ai_repos`

### Scale

PyTorch alone has ~50,000 dependent packages on PyPI. TensorFlow has ~30,000. LangChain has ~5,000. After deduplication and quality filtering, the dependency graph likely yields 50,000-100,000 repos that aren't in our current index.

### Resource cost

The expensive part is the reverse dependency lookup, which requires either:
- **Libraries.io API** (free, rate-limited to 60 req/min): ~5,000 calls to get dependents for 50 seed packages
- **BigQuery** (paid, ~$5 per scan): one query against the PyPI dataset
- **npm API**: free, ~2,000 calls for npm-specific seeds

Repo resolution: ~50,000-100,000 GitHub REST calls over several days (well within budget).

### Why Phase 3 is last

This is the highest-yield channel but requires:
- External API integrations we don't have yet (Libraries.io or BigQuery)
- A quality filter to avoid drowning in tutorial repos
- Careful domain classification (a repo that depends on PyTorch could be in any of our 29 domains)

Phases 1 and 2 are higher leverage per unit of effort.

### Phase 3 summary

| Source | Expected new repos | Resource cost | Frequency |
|--------|-------------------|---------------|-----------|
| PyPI reverse deps (50 seeds) | 30,000-60,000 | Libraries.io or BigQuery | Monthly |
| npm reverse deps (20 seeds) | 10,000-20,000 | npm API | Monthly |
| Crates.io reverse deps (10 seeds) | 2,000-5,000 | crates.io API | Monthly |
| **Total** | **42,000-85,000** | | |

Combined with Phases 1 and 2: **400K-540K repos.**

---

## Projected Growth

| | Repos | Domains | GitHub REST utilisation | Timeline |
|---|---|---|---|---|
| **Today** | 248K | 18 | 12% | — |
| **After Phase 1** | 320-370K | 29 | 30% steady state | 2-3 weeks |
| **After Phase 2** | 360-455K | 29 | 35% steady state | 1-2 months |
| **After Phase 3** | 400-540K | 29+ | 40% steady state | 2-3 months |

Steady-state budget after all phases:

| Use | Calls/day |
|-----|-----------|
| Maintenance (metadata, releases, commits) | 8,000-15,000 |
| README freshness (500K repos ÷ 90 days) | 5,500 |
| Enrichment (new discoveries) | 5,000-10,000 |
| Discovery (all channels) | 5,000-15,000 |
| Backfill (created_at for new repos) | 5,000-10,000 |
| **Total** | **28,500-55,500** |
| **Headroom** | **65,000-90,000 (54-75%)** |

Even at 500K+ repos with continuous discovery, we never exceed 50% of the GitHub budget. The system has room to grow to 1M+ repos before budget becomes a constraint.

---

## What This Enables

At 500K repos with full enrichment:

- **500K pages** on the static site, each with a problem brief, quality scores, and comparison sentences. At the 1 visit/page/month baseline, that's 500K visits/month.
- **Complete domain coverage** — practitioners in reinforcement learning, robotics, drug discovery, etc. find relevant tools instead of getting nothing.
- **Dependency-aware recommendations** — "projects that use the same stack" becomes possible with the Phase 3 data.
- **Faster trend detection** — daily discovery catches breakout repos within 24 hours instead of 7 days.
- **Higher-quality comparisons** — more repos in each domain means denser comparison graphs and more meaningful "use X instead of Y" guidance.
