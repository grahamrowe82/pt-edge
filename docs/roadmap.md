# Roadmap

## Organising principle

Build what the data says matters. The allocation engine (Bayesian surprise, position strength, CTR vs benchmark) tells us where the demand/supply gap is widest. That drives what we enrich, what we write about, and what infrastructure we invest in. Speculative features wait until data validates them.

The primary growth mechanism is the **content flywheel:**

```
Deep dive → Substack → traffic → Umami + GSC data → allocation engine → next deep dive
```

Everything on this roadmap either feeds the flywheel or is deferred until the flywheel justifies it.

## What's done

- [x] 220K+ repo directory across 18 domains (MCP, agents, perception, RAG, AI coding, voice AI, diffusion, vector DB, embeddings, prompt engineering, ML frameworks, LLM tools, NLP, transformers, generative AI, computer vision, data engineering, MLOps)
- [x] Quality scoring (0-100) with 4 sub-dimensions, daily refresh
- [x] 2,267 embedding-discovered categories via UMAP + HDBSCAN + Haiku labelling
- [x] Decision paragraphs on every category page
- [x] AI summaries from READMEs (Haiku-generated, 4K/day via LLM_BUDGET_MULTIPLIER=2.0)
- [x] Template-generated metrics paragraphs on all detail pages
- [x] Daily metric snapshots for all 226K repos (stars, forks, downloads, commits)
- [x] 1536d embeddings for 219K+ repos (~97% coverage)
- [x] JSON-LD structured data, sitemaps, cross-domain navigation
- [x] MCP server (50+ tools) + REST API with keyed access
- [x] Comparison pages: embedding-similarity pairs within categories, decision sentences via Haiku
- [x] Domain reassignment via centroid similarity (10K/day in daily ingest)
- [x] Allocation engine: dual-score (EHS + ES) with Bayesian surprise, position strength, CTR vs benchmark, barbell strategy, daily snapshots, deep dive priority queue
- [x] Umami self-hosted analytics at a.phasetransitions.ai
- [x] CTR-optimised title tags and meta descriptions across all 6 page types
- [x] Deep dive infrastructure: reverse links from server detail pages, Substack companion workflow, process documented ([docs/briefs/deep-dive-process.md](briefs/deep-dive-process.md))
- [x] 9 published deep dives: OpenClaw ecosystem, voice AI landscape, voice app stack, embeddings shortcut, agent governance, agent memory, agent skills architecture, Obsidian PKM agents, perception/browser automation
- [x] Google Search Console pipeline wired into daily ingest
- [x] Coverage audit infrastructure: weekly awesome-list reconciliation ([scripts/audit_coverage.py](../scripts/audit_coverage.py))
- [x] LLM throughput ramp: ANTHROPIC_RPM 40→120 (Tier 2), LLM_BUDGET_MULTIPLIER 1.0→2.0
- [x] Commercial plan documented ([docs/commercial-plan.md](commercial-plan.md))
- [x] Strategy docs updated: "Where we win" section in strategy.md, Bayesian framework in allocation engine brief
- [x] Open Graph tags implemented on index, server detail, and comparison pages

## Immediate: make the flywheel turn

These are the things blocking the flywheel from running properly.

- [ ] **GSC data volume:** The pipeline runs and gsc_search_data has some rows (~48), but volume is minimal. Investigate whether GSC credentials are fully configured on Render and whether the API lag is still the bottleneck, or if there's a bug limiting the data pull.
- [ ] **Sitemap/generation alignment:** Confirmed bug — the sitemap includes repos below MIN_QUALITY_SCORE that don't have generated pages, producing 404s (e.g., roshan7783/Sentiment-Analyzer scores 8/100, no page exists, but URL is in sitemap). Fix: build the sitemap from the list of pages actually written during generation. One source of truth.
- [ ] **Domain reassignment redirects:** Confirmed bug — when a repo is reassigned to a different domain (e.g., k8sgpt moved from transformers to mlops), the old URL becomes a 404 while Google still has it indexed. Fix: track reassignment history in a `domain_reassignment_log` table (full_name, old_domain, new_domain, reassigned_at). During site generation, read the log and generate redirect HTML stubs at old paths. Permanent infrastructure.
- [ ] **Subcategory classifier quality:** High-quality repos land in wrong solo categories (ElevenLabs still in `ai-workflow-automation`). This isolates them from comparisons and related servers. Investigate the LLM classifier prompt/context and fix the process — not individual repos.
- [ ] **Cross-category comparison discovery:** Embedding similarity only runs within subcategories. The most valuable matchups (WhisperX vs whisper.cpp, ElevenLabs vs edge-tts) cross subcategory boundaries. Add a domain-level pass across top N projects.

## Foundational coverage gap (discovered via kairn audit)

The crewAI dependency audit exposed that PT-Edge's 18 domains are all application-level (what people build with AI). The foundational layer — what AI applications are built on — is not tracked: LLM provider SDKs (openai-python, anthropic-sdk-python), structural tools (pydantic), protocol SDKs (MCP python-sdk), and observability instrumentation (opentelemetry). These are some of the most depended-on packages in the AI ecosystem.

This is a core product gap, not just a kairn prerequisite. Someone searching "anthropic SDK quality" should find a scored answer on PT-Edge. Full analysis: [docs/briefs/kairn-product-plan.md — Finding 4](briefs/kairn-product-plan.md).

- [ ] **Decide: new domain vs distributed into existing domains.** A `foundations` or `ai-infrastructure` domain would cover provider SDKs, structured output, transport, observability, protocol SDKs. The alternative is distributing into existing domains (openai-python into llm-tools, pydantic into ml-frameworks). Needs architectural decision.
- [ ] **Seed the foundational repos.** Once the domain decision is made, ingest the ~50-100 foundational repos. These are high-star, high-quality repos that will immediately improve the site's credibility.
- [ ] **Build the package-to-repo mapping table** (`package_registry_map`). Bidirectional: PyPI→GitHub and GitHub→PyPI. Required for kairn and useful for dependency graph analysis generally. See [kairn plan — Finding 1](briefs/kairn-product-plan.md).

## Data-driven: build when GSC/allocation signals justify

These are high-value features, but we build them when the data says to — not on a fixed schedule.

### Deep dives (allocation-driven)

The allocation engine's `v_deep_dive_queue` ranks topics. Next candidates based on traffic data:
- ML frameworks landscape (now our largest indexed domain at 180+ pages, driving multi-page evaluation sessions from France, US, Hong Kong)
- Data engineering tools (unsexy, high practitioner demand)
- Computer vision (overshadowed by LLM narrative)
- MLOps (same dynamic as data engineering)

Process: [docs/briefs/deep-dive-process.md](briefs/deep-dive-process.md)

### Language pages

"All Rust MCP servers." "All Python agent frameworks." Language is a primary developer filtering criterion. Dense internal linking, catches long-tail queries. Build for domains where GSC shows language-specific search intent.

### Temporal layer

30+ days of snapshots accumulate late April 2026 (~Apr 27). Unlocks:
- Sparklines on detail pages (30-day star/download trends)
- "Gained X stars this week" on detail pages
- Star velocity-based trending (replace currently empty trending pages)
- Growth classification: accelerating, steady, declining

This is a freshness signal that compounds — Google sees content that changes meaningfully on every crawl. High priority once data is available.

### Cross-vertical stack pages

Architecture guides that link across multiple domains: "Build a document Q&A pipeline" → embeddings + vector DB + RAG framework. Validated by the voice-app-stack deep dive (cross-domain linking, 5x voice overrepresentation in Umami data across domains). Next candidates driven by allocation engine signals.

## Infrastructure quality

Lower priority but contributes to long-term health.

- [ ] Cross-vertical links for projects that appear in multiple domains
- [ ] OG tag visual verification on Twitter/LinkedIn (implementation done, needs testing)
- [ ] RSS feeds per domain (distribution channel for freshness signals)

## Commercial progression

The full journey from anonymous traffic to enterprise revenue is documented in [docs/commercial-plan.md](commercial-plan.md). Key points:

**Highest-priority commercial build: automated topical email digests.** This is the step we're completely missing — the 3→4 conversion where anonymous visitors become known contacts. Auto-generated weekly digests per domain from existing data (trending repos, score changes, new categories). No manual writing. Each digest links back to the site and includes an API promotion CTA.

**The API and key system already exist** but aren't promoted. Once we have email subscribers, API promotion is a line in the digest footer.

## Long-term: the data business

Once the flywheel is generating consistent organic traffic and temporal data reaches 90+ days:

### kairn: Strategic Dependency Intelligence

Strategic dependency auditing for AI projects — "is this the right library?" not just "is it safe?" Full plan: [docs/briefs/kairn-product-plan.md](briefs/kairn-product-plan.md)

The manual crewAI audit ([docs/briefs/kairn-crewai-audit.md](briefs/kairn-crewai-audit.md)) surfaced 7 findings that reshaped the build plan. Revised 9-step sequence (dependency-ordered):

1. **Reverse dependency counts** [quick win, no deps] — "used by X AI projects." Most novel metric, ships immediately.
2. **Unified quality score** (`mv_unified_quality`) [foundational] — domain-agnostic scoring for all 220K repos. Enables cross-domain comparison. The 18 domain MVs stay for browsing, unified MV powers all analytics.
3. **AI dependency boundary + foundational repo ingestion** — codify three-tier classification, ingest ~50-100 missing foundational repos (openai-python, anthropic SDK, pydantic, MCP SDK, opentelemetry).
4. **Package-to-repo mapping table** (`package_registry_map`) — bidirectional PyPI↔GitHub mapping with continuous validation.
5. **Embedding-based alternatives** — replace subcategory-peer alternatives with nearest-neighbour by embedding + unified score.
6. **Server detail page enrichment** — "Strategic Fitness" section (rank, momentum, alternatives, dependents).
7. **`POST /api/v1/audit` endpoint** — accept package lists, return strategic fitness via verified mapping + unified scoring.
8. **Open-source scanner CLI** (`kairn`) — reads lock files, calls API, renders report. Distribution channel.

### Quantitative analytics layer

- Moving averages and crossover signals on star velocity
- Factor analysis: quality, momentum, size, value (hype ratio), volatility
- Dependency risk indicators (feeds into kairn)
- Ecosystem-level analytics: sector rotation, concentration risk

### Enterprise data API

The directory proves data quality for free. The analytics layer is the product. Pricing: $12K-36K/year for API access to the signal layer. The free directory is both the marketing surface and the trust-building mechanism. The full commercial funnel — from anonymous visit to enterprise contract in 8 steps — is in [docs/commercial-plan.md](commercial-plan.md). kairn is the first concrete product on this API.

### Community features

- "Claim your project" for maintainers (badges for READMEs, metadata editing)
- Feedback button on every page (wrong category, dead link, security concern)
- On-site search
