# Discovery Expansion: Implementation Plan

*5 April 2026 — companion to [discovery-expansion.md](discovery-expansion.md)*

This document maps the strategy doc's three phases into a sequence of pull requests, identifies the files each PR touches, and flags dependencies between them.

---

## PR Sequence

### Phase 1: Use What We Have

#### PR 1 — Remove backlog throttle

Bump the scheduler constants so the worker always has work available for the `github_api` slot during backlog clearing.

**Files changed:**
- `app/queue/scheduler.py` — `PENDING_CAP` 500 → 5,000; `BATCH_LIMIT` 1,000 → 5,000 for `fetch_readme` and `backfill_created_at`

**Risk:** GitHub REST utilisation jumps from 12% to ~80% during the clearing window. Monitor rate-limit headers for the first 24 hours.

**Dependencies:** None. Ship first — every day of delay is another day on the 55-day backlog.

---

#### PR 2 — Daily discovery

Switch `discover_ai_repos` from weekly to daily so incremental crawls catch new repos within 24 hours instead of 7 days.

**Files changed:**
- `app/queue/scheduler.py` — `staleness_hours` for `discover_ai_repos`: 168 → 24

**Risk:** Search API utilisation rises from 1% to ~7%. Well within budget but worth confirming the first few daily runs complete without hitting rate limits.

**Dependencies:** None. Independent of PR 1.

---

#### PR 3 — Add 11 new domains

Expand topic coverage from 18 to 29 domains: reinforcement-learning, robotics, recommendation-systems, time-series, graph-neural-networks, interpretability, federated-learning, edge-ai, drug-discovery, audio-ai, simulation.

**Files changed:**
- `app/ingest/ai_repo_domains.py` — add entries to `DOMAINS` dict (topics + `min_stars` per domain), extend `DOMAIN_ORDER`
- `scripts/generate_site.py` — add `DOMAIN_CONFIG` entry for each new domain (view name, snapshot table, labels, description, explainer)
- `scripts/start.sh` — add site generation line for each new domain (one `generate_site.py --domain X --output-dir site/X` per domain)
- `app/queue/handlers/enrich_repo_brief.py` — add entry to `DOMAIN_VIEW_MAP`
- `app/ingest/project_briefs.py` — add entry to the duplicate `DOMAIN_VIEW_MAP` (these two maps should be consolidated eventually)
- New Alembic migration — create `mv_*_quality` materialised views for each new domain (follow the template in migration 051)

**Risk:** Largest Phase 1 PR. The migration creates 11 new MVs which will be empty until the first discovery run populates repos in those domains. Site generation should handle empty domains gracefully (verify before merging).

**Dependencies:** Deploy after PRs 1 & 2 so new repos are discovered daily and enriched promptly.

---

### Phase 2: New Discovery Channels

PRs 4–7 are independent of each other. They can be built and merged in any order or in parallel. Each follows the same pattern: new ingest module → new handler → scheduler registration.

**Handler pattern note:** The existing `discover_ai_repos` handler lives in the grouped file `compute_post_process.py`, not in its own file. New discovery handlers can follow either pattern — individual files or additions to the grouped file. Either way, they must be registered in `TASK_HANDLERS` in `__init__.py`.

#### PR 4 — PyPI classifier discovery

Discover AI repos via the PyPI `Topic :: Scientific/Engineering :: Artificial Intelligence` trove classifier. These are repos that published packages (strong usage signal) but may lack GitHub topic tags.

**Files changed:**
- `app/ingest/pypi_discovery.py` (new) — fetch classifier page / Simple API, resolve source URLs from `project_urls` metadata, cross-reference against `ai_repos`
- `app/queue/handlers/` — handler (new file or added to `compute_post_process.py`)
- `app/queue/handlers/__init__.py` — register `discover_pypi` in `TASK_HANDLERS`
- `app/queue/scheduler.py` — add weekly coarse task (`staleness_hours=168`, resource_type `pypi`)

**Expected yield:** 10,000–20,000 new repos. ~5,000 PyPI API calls per run, zero GitHub budget for discovery itself.

**Dependencies:** Phase 1 complete (so new discoveries get enriched promptly).

---

#### PR 5 — Description-based GitHub search

Find AI repos that lack topic tags but describe themselves as AI in their description or README. This is the biggest single opportunity — the 15–20% of repos invisible to topic search.

**Files changed:**
- `app/ingest/description_discovery.py` (new) — ~20 keyword queries (`"neural network" in:description language:python stars:>=5`, etc.), reuse `adaptive_search()` from `github_search.py` for shard management
- `app/queue/handlers/` — handler (new file or added to `compute_post_process.py`)
- `app/queue/handlers/__init__.py` — register in `TASK_HANDLERS`
- `app/queue/scheduler.py` — add weekly coarse task (`staleness_hours=168`, resource_type `github_api` — there is no separate `github_search` resource type; all GitHub calls share one budget)

**Expected yield:** 20,000–50,000 new repos. ~5,000–10,000 Search API calls per run.

**Risk:** Keyword queries may pull in non-AI repos (e.g. "neural network" in a neuroscience context). May need a quality filter or domain-classifier pass on results.

**Dependencies:** Phase 1 complete.

---

#### PR 6 — Awesome list ingestion

Parse curated "awesome" lists for GitHub URLs we don't already track. Low volume but high quality — these are repos vetted by domain experts.

**Files changed:**
- `app/ingest/awesome_list_discovery.py` (new) — maintain a list of ~20 awesome-list repos, fetch each README, parse Markdown for GitHub URLs, cross-reference against `ai_repos`
- `app/queue/handlers/` — handler (new file or added to `compute_post_process.py`)
- `app/queue/handlers/__init__.py` — register in `TASK_HANDLERS`
- `app/queue/scheduler.py` — add monthly coarse task (`staleness_hours=720`, resource_type `github_api`)

**Expected yield:** 5,000–10,000 repos. ~20 README fetches + ~5,000 metadata fetches. Negligible budget cost.

**Dependencies:** Phase 1 complete.

---

#### PR 7 — HuggingFace source repo linking

Cross-reference `hf_models` and `hf_datasets` for GitHub URLs not already in `ai_repos`. These repos have associated ML models or datasets — strong signal of real research or production use.

**Files changed:**
- `app/ingest/hf_linking.py` (new) — query HF tables for GitHub URLs, extract repo slugs, cross-reference against `ai_repos`, fetch metadata for new discoveries
- `app/queue/handlers/` — handler (new file or added to `compute_post_process.py`)
- `app/queue/handlers/__init__.py` — register in `TASK_HANDLERS`
- `app/queue/scheduler.py` — add weekly coarse task (`staleness_hours=168`), scheduled after `fetch_hf_models` / `fetch_hf_datasets`

**Expected yield:** 2,000–5,000 repos. Mostly DB-only with a few hundred GitHub calls for metadata.

**Dependencies:** Phase 1 complete.

---

### Phase 3: Dependency-Based Discovery

#### PR 8 — Reverse dependency client

Build the external API integration for looking up which packages depend on a given seed package. This is infrastructure — the plumbing that PR 9 consumes.

**Files changed:**
- `app/ingest/reverse_deps.py` (new) — client for Libraries.io API (or BigQuery), npm dependents endpoint, and crates.io reverse-deps. Accepts a seed package name, returns a list of dependent packages with their source URLs.
- Seed list of ~50 AI framework packages (pytorch, tensorflow, transformers, langchain, openai, scikit-learn, keras, jax, spacy, huggingface-hub, chromadb, pinecone, weaviate, llamaindex, crewai, autogen, etc.)
- Quality filter: ≥5 GitHub stars OR ≥100 monthly downloads

**Decision needed:** Libraries.io (free, 60 req/min rate limit) vs BigQuery (~$5/scan). Libraries.io is simpler to start; BigQuery scales better if we need the full PyPI graph.

**Dependencies:** Phase 2 complete. This is the most speculative phase — wait until Phases 1–2 prove out the enrichment pipeline at higher volume.

---

#### PR 9 — Reverse-dep discovery sweep

Use PR 8's client to run the actual monthly discovery: look up dependents for all seed packages, resolve source URLs, cross-reference against `ai_repos`, and create enrichment tasks for new discoveries.

**Files changed:**
- `app/ingest/dep_discovery.py` (new) — orchestrates the sweep: iterate seeds, call reverse-dep client, deduplicate, classify into domains (using existing embedding + nearest-domain logic), insert into `ai_repos`
- `app/queue/handlers/` — handler (new file or added to `compute_post_process.py`)
- `app/queue/handlers/__init__.py` — register in `TASK_HANDLERS`
- `app/queue/scheduler.py` — add monthly coarse task (`staleness_hours=720`)

**Expected yield:** 42,000–85,000 repos across PyPI, npm, and crates.io dependents.

**Risk:** Domain classification for dependency-discovered repos is harder — a repo that imports PyTorch could be in any of 29 domains. May need a classifier pass or fallback to embedding similarity.

**Dependencies:** PR 8.

**Optional split:** Separate PyPI and npm into two PRs if smaller deploys are preferred.

---

## Dependency Graph

```
PR 1 (throttle) ──┐
PR 2 (daily)   ───┤── Phase 1 complete ──┬── PR 4 (PyPI classifiers)
PR 3 (domains) ──┘                       ├── PR 5 (description search)
                                          ├── PR 6 (awesome lists)
                                          └── PR 7 (HF linking)
                                                     │
                                               Phase 2 complete
                                                     │
                                               PR 8 (dep client)
                                                     │
                                               PR 9 (dep sweep)
```

## Summary Table

| PR | Phase | Scope | Key files | Dependencies |
|----|-------|-------|-----------|-------------|
| 1 — Backlog throttle | 1 | Constants only | `scheduler.py` | None |
| 2 — Daily discovery | 1 | One-line config | `scheduler.py` | None |
| 3 — 11 new domains | 1 | Config + migration + site gen | `ai_repo_domains.py`, `generate_site.py`, `start.sh`, migration | None (deploy after 1 & 2) |
| 4 — PyPI classifiers | 2 | New handler + ingest | New `pypi_discovery.py` + handler | Phase 1 |
| 5 — Description search | 2 | New ingest module | New `description_discovery.py` + handler | Phase 1 |
| 6 — Awesome lists | 2 | New handler | New `awesome_list_discovery.py` + handler | Phase 1 |
| 7 — HF linking | 2 | SQL + handler | New `hf_linking.py` + handler | Phase 1 |
| 8 — Dep client | 3 | External API integration | New `reverse_deps.py` | Phase 2 |
| 9 — Dep sweep | 3 | New discovery sweep | New `dep_discovery.py` + handler | PR 8 |
