# Expanding the PT-Edge Universe

*5 April 2026 — updated 7 April 2026*

**Vision:** [master-plan.md](master-plan.md) — thesis, flywheel, and revenue model.
**Implementation plan:** [discovery-expansion-implementation.md](discovery-expansion-implementation.md) — PR sequence, file-level scope, and dependency graph.

> **Status as of 7 April 2026:** Phase 1 is ~70% complete. PRs 1 (backlog throttle) and 2 (daily discovery) are shipped. PR 3 (new domains) is not started — the 11 planned domains remain to be added. One unplanned domain (`perception` — web scraping/browser automation) was added separately. Phases 2 and 3 have not started. See inline status markers below.

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

**Domains we don't search:** LLM inference/serving, AI evaluation/observability, fine-tuning, document AI/OCR, AI safety/guardrails, recommendation systems, audio AI, synthetic data, time series/forecasting, multimodal AI, 3D vision, scientific ML. Also missing but lower priority (low tool-selection activity): reinforcement learning, robotics, graph neural networks, federated learning, interpretability, edge AI, drug discovery, simulation.

**Repos we can't see via topic search:** ~15-20% of GitHub AI repos lack topic tags. These are invisible to our current discovery regardless of how many topics we search. Older repos, academic code, non-English projects, and quick-publish experiments tend not to tag.

**Sources we don't use:** PyPI classifiers, npm tags, Papers with Code, awesome lists, dependency graphs, HuggingFace source repos, GitLab.

---

## Phase 1: Use What We Have

*Config changes only. No new code except tuning constants.*

### 1a. Remove the backlog throttle — DONE

The scheduler caps fine-grained tasks at 500 pending with 1,000 per batch, refilled every 15 minutes. At 4,500 claims/hour the worker runs dry between refills.

**Change:** Increase `PENDING_CAP` to 5,000 and `BATCH_LIMIT` to 5,000 for `fetch_readme` and `backfill_created_at`. The worker always has work available for the `github_api` slot.

**What shipped:** Global `PENDING_CAP` and `BATCH_LIMIT` raised to 5,000 in `scheduler.py`. `fetch_readme` uses the global limits. `backfill_created_at` intentionally kept at 500/1,000 to avoid flooding the tasks table with 225K+ rows — it uses its own `schedule_backfill_created_at()` function with batch control.

**Impact:** README and created_at backlogs clear in 4 days instead of 55. The github_api budget goes from 12% to ~80% utilised during the backlog clearing period, then drops back as the backlog drains.

### 1b. Run discovery daily instead of weekly — DONE

`discover_ai_repos` currently runs with `staleness_hours=168` (weekly). The Saturday cron job is gone. The task queue can run it every day.

**Change:** Set `staleness_hours=24` for `discover_ai_repos` in the scheduler.

**What shipped:** `staleness_hours=24` is live in `scheduler.py`.

**Impact:** Discovery rate increases 7x for the same 3,000 calls per run. Incremental crawls (searching for repos pushed since the last run) become much more current — catching repos within 24 hours of their first push instead of within 7 days.

### 1c. Add 12 new domains — NOT STARTED

Expand the topic list in `ai_repo_domains.py` to cover categories where AI agents are regularly asked tool-selection questions but PT-Edge has no answer.

> **Note:** One unplanned domain — `perception` (web scraping, browser automation) — was added separately. The original plan proposed 11 domains based on GitHub blind spots. This was revised on 7 April 2026 after a first-principles audit of what AI agents actually get asked about. The selection criterion changed from "fields with lots of GitHub repos" to "fields where developers ask 'what's the best X?' and expect a structured comparison." See `scratch/revised-domain-expansion.md` for the full analysis.

**Tier 1 — Clear gaps, high tool-selection intensity:**

| Domain | What it covers | GitHub topics | Est. repos |
|--------|---------------|---------------|------------|
| `llm-inference` | Self-hosted LLM serving and local runners | `llm-inference`, `model-serving`, `llm-server`, `inference-engine`, `gguf`, `ollama` | 3,000-8,000 |
| `ai-evals` | LLM evaluation, benchmarking, observability, tracing | `llm-evaluation`, `ai-evaluation`, `benchmarking`, `llm-observability`, `ai-observability`, `tracing` | 2,000-5,000 |
| `fine-tuning` | LLM and model fine-tuning tools | `fine-tuning`, `finetuning`, `lora`, `qlora`, `peft`, `llm-finetuning` | 3,000-8,000 |
| `document-ai` | Document parsing, OCR, table extraction for AI pipelines | `ocr`, `document-parsing`, `pdf-extraction`, `document-ai`, `table-extraction`, `pdf-to-text` | 3,000-6,000 |
| `ai-safety` | Guardrails, content filtering, red teaming, adversarial robustness | `guardrails`, `ai-safety`, `llm-security`, `red-teaming`, `adversarial-robustness`, `content-moderation` | 1,500-4,000 |

**Tier 2 — Real tool-selection activity, slightly less intense:**

| Domain | What it covers | GitHub topics | Est. repos |
|--------|---------------|---------------|------------|
| `recommendation-systems` | Collaborative filtering, content-based, sequential recs | `recommender-system`, `collaborative-filtering`, `recommendation-engine`, `content-based-filtering` | 8,000-15,000 |
| `audio-ai` | Music generation, source separation, audio classification (distinct from voice-ai's TTS/ASR) | `audio-generation`, `music-generation`, `audio-classification`, `source-separation`, `sound-event-detection` | 3,000-6,000 |
| `synthetic-data` | Training data generation, augmentation, simulation for ML | `synthetic-data`, `data-augmentation`, `data-generation`, `synthetic-data-generation` | 2,000-5,000 |
| `time-series` | Forecasting, anomaly detection, classification on temporal data | `time-series`, `forecasting`, `time-series-analysis`, `time-series-forecasting` | 5,000-10,000 |

**Tier 3 — Emerging or niche but defensible:**

| Domain | What it covers | GitHub topics | Est. repos |
|--------|---------------|---------------|------------|
| `multimodal` | Vision-language models, cross-modal retrieval, audio-visual | `multimodal`, `vision-language`, `vlm`, `multimodal-learning` | 2,000-5,000 |
| `3d-ai` | NeRF, gaussian splatting, point clouds, 3D reconstruction | `nerf`, `gaussian-splatting`, `3d-reconstruction`, `point-cloud`, `3d-generation` | 1,500-3,000 |
| `scientific-ml` | Physics-informed neural nets, neural operators, molecular ML | `physics-informed-neural-networks`, `scientific-computing`, `neural-operator`, `computational-biology` | 2,000-5,000 |

**Domains considered and rejected:**

| Domain | Why not |
|--------|---------|
| Reinforcement learning | Tool selection converged (Stable-Baselines3 + Gymnasium). Huge repo count, no active comparison debate. |
| Robotics | Hardware-coupled, domain-specific. Not what AI agents get asked for tool recommendations. |
| Graph neural networks | PyG vs DGL — conversation ended. Insufficient ongoing selection pressure. |
| Federated learning | Academic field, near-zero practitioner tool-selection discussion. |
| Interpretability/XAI | SHAP dominates. Minimal comparison activity outside research. |
| Edge AI/TinyML | Small ecosystem, overlaps with model compression. Deployment target, not tool category. |
| Simulation | Too niche standalone. Consumed within robotics/RL contexts. |
| Drug discovery | "AI applied to chemistry" not "AI tooling." Revisit if demand signals appear. |

**Impact:** 35,000-80,000 new repos discovered over 2-3 weeks of daily crawls. Total repo count reaches 283K-328K. Fewer repos than the original 11-domain plan but every new domain answers questions agents actually get asked.

**Prerequisite:** Each new domain needs a corresponding quality view (`mv_*_quality`) and an entry in `DOMAIN_VIEW_MAP` (duplicated in `enrich_repo_brief.py` and `project_briefs.py`), `DOMAIN_CONFIG` (in `generate_site.py`), `DOMAIN_ORDER` (in `ai_repo_domains.py`), and `start.sh` for site generation. This is mechanical but not zero work.

### Phase 1 summary

| Metric | Before | After | Status |
|--------|--------|-------|--------|
| Backlog clear time | 55 days | 4 days | DONE |
| Discovery frequency | Weekly | Daily | DONE |
| Domains | 18 | 30 | 18 (12 new domains to add) |
| Estimated repos | 248K | 283-328K | Pending domain expansion |
| GitHub REST utilisation | 12% | 60-80% during backlog, 30% steady state | DONE |
| GitHub Search utilisation | 1% | 7% | DONE |

---

## Phase 2: New Discovery Channels — NOT STARTED

*New task types and handlers. Finds repos that topic search can't reach.*

> **Status as of 7 April 2026:** None of the four Phase 2 channels have been implemented. Database tables for awesome list ingestion (`awesome_list_sources`, `awesome_list_repos`) were created in migration 068 (coverage audit) but no production handler uses them yet.

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

Combined with Phase 1: **320K-413K repos.**

---

## Phase 3: Dependency-Based Discovery — NOT STARTED

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
- Careful domain classification (a repo that depends on PyTorch could be in any of our 30 domains)

Phases 1 and 2 are higher leverage per unit of effort.

### Phase 3 summary

| Source | Expected new repos | Resource cost | Frequency |
|--------|-------------------|---------------|-----------|
| PyPI reverse deps (50 seeds) | 30,000-60,000 | Libraries.io or BigQuery | Monthly |
| npm reverse deps (20 seeds) | 10,000-20,000 | npm API | Monthly |
| Crates.io reverse deps (10 seeds) | 2,000-5,000 | crates.io API | Monthly |
| **Total** | **42,000-85,000** | | |

Combined with Phases 1 and 2: **362K-498K repos.**

---

## Projected Growth

| | Repos | Domains | GitHub REST utilisation | Timeline |
|---|---|---|---|---|
| **Today** | 248K | 18 | 12% | — |
| **After Phase 1** | 283-328K | 30 | 30% steady state | 2-3 weeks |
| **After Phase 2** | 320-413K | 30 | 35% steady state | 1-2 months |
| **After Phase 3** | 362-498K | 30+ | 40% steady state | 2-3 months |

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
- **Complete domain coverage** — practitioners asking about LLM inference, fine-tuning, document parsing, AI safety, etc. find structured answers instead of getting nothing.
- **Dependency-aware recommendations** — "projects that use the same stack" becomes possible with the Phase 3 data.
- **Faster trend detection** — daily discovery catches breakout repos within 24 hours instead of 7 days.
- **Higher-quality comparisons** — more repos in each domain means denser comparison graphs and more meaningful "use X instead of Y" guidance.
