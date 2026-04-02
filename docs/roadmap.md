# Roadmap

## Organising principle

Build what the data says matters. The allocation engine (Bayesian surprise, position strength, CTR vs benchmark) tells us where the demand/supply gap is widest. That drives what we enrich, what we write about, and what infrastructure we invest in. Speculative features wait until data validates them.

The primary growth mechanism is the **content flywheel:**

```
Deep dive → Substack → traffic → Umami + GSC data → allocation engine → next deep dive
```

Everything on this roadmap either feeds the flywheel or is deferred until the flywheel justifies it.

## What's done

- [x] 165,000+ page directory across 17 domains
- [x] Quality scoring (0-100) with 4 sub-dimensions, daily refresh
- [x] 2,400 embedding-discovered categories via UMAP + HDBSCAN + Haiku labelling
- [x] Decision paragraphs on every category page
- [x] AI summaries from READMEs (Haiku-generated, 2K/day backfill)
- [x] Template-generated metrics paragraphs on all detail pages
- [x] Daily metric snapshots for all 220K repos (stars, forks, downloads, commits)
- [x] 1536d embeddings for 220K+ repos (analytics/clustering)
- [x] JSON-LD structured data, sitemaps, cross-domain navigation
- [x] MCP server (47 tools) + REST API with keyed access
- [x] Comparison pages: embedding-similarity pairs within categories, decision sentences via Haiku
- [x] Domain reassignment via centroid similarity (10K/day in daily ingest)
- [x] Allocation engine: dual-score (EHS + ES) with Bayesian surprise, position strength, CTR vs benchmark, barbell strategy, daily snapshots, deep dive priority queue
- [x] Umami self-hosted analytics at a.phasetransitions.ai
- [x] CTR-optimised title tags and meta descriptions across all 6 page types
- [x] Deep dive infrastructure: reverse links from server detail pages, Substack companion workflow, process documented
- [x] Voice AI deep dive (first data-driven deep dive, validated by GSC signals)
- [x] Google Search Console pipeline wired into daily ingest

## Immediate: make the flywheel turn

These are the things blocking the flywheel from running properly.

- [ ] **GSC data flowing:** The pipeline is wired (`app/ingest/gsc.py`) but `gsc_search_data` is empty. Verify GSC credentials are set on Render and the daily cron is successfully pulling data. Without this, the allocation engine has no demand signal.
- [ ] **Sitemap/generation alignment:** The sitemap includes URLs for repos that don't have generated pages (below quality threshold, no description), producing 404s that waste crawl budget and erode Google's trust. Fix: build the sitemap from the list of pages actually written during generation, not from a separate DB query. One source of truth — if a page wasn't generated, it doesn't go in the sitemap.
- [ ] **Domain reassignment redirects:** When a repo is reassigned to a different domain (e.g., k8sgpt moved from transformers to mlops), the old URL becomes a 404 while Google still has it indexed. Fix: track reassignment history in a `domain_reassignment_log` table (full_name, old_domain, new_domain, reassigned_at). During site generation, read the log and generate redirect HTML stubs at old paths (`<meta http-equiv="refresh">` + canonical link to new path). Handles multiple reassignments over time. The log is permanent infrastructure, not a one-off fix.
- [ ] **Subcategory classifier quality:** High-quality repos land in wrong solo categories (ElevenLabs in `ai-workflow-automation`). This isolates them from comparisons and related servers. Investigate the LLM classifier prompt/context and fix the process — not individual repos.
- [ ] **Cross-category comparison discovery:** Embedding similarity only runs within subcategories. The most valuable matchups (WhisperX vs whisper.cpp, ElevenLabs vs edge-tts) cross subcategory boundaries. Add a domain-level pass across top N projects.

## Data-driven: build when GSC/allocation signals justify

These are high-value features, but we build them when the data says to — not on a fixed schedule.

### Deep dives (allocation-driven)

The allocation engine's `v_deep_dive_queue` ranks topics. Next deep dive should be whatever scores highest once GSC data is flowing. Likely candidates based on early signals:
- Embeddings landscape (probably thin content supply, like voice-ai)
- Data engineering tools (unsexy, high practitioner demand)
- Computer vision (overshadowed by LLM narrative)
- MLOps (same dynamic as data engineering)

Process: [docs/briefs/deep-dive-process.md](briefs/deep-dive-process.md)

### Language pages

"All Rust MCP servers." "All Python agent frameworks." Language is a primary developer filtering criterion. Dense internal linking, catches long-tail queries. Build for domains where GSC shows language-specific search intent.

### Temporal layer

30+ days of snapshots accumulate late April 2026. Unlocks:
- Sparklines on detail pages (30-day star/download trends)
- "Gained X stars this week" on detail pages
- Star velocity-based trending (replace currently empty trending pages)
- Growth classification: accelerating, steady, declining

This is a freshness signal that compounds — Google sees content that changes meaningfully on every crawl. High priority once data is available.

### Cross-vertical stack pages

"Build a document Q&A pipeline" → embeddings + vector DB + RAG framework. Highest-value page type because it requires quality-scored data across multiple domains — nobody else can produce it. But speculative until GSC data shows cross-vertical search intent. Defer until allocation engine validates demand.

## Infrastructure quality

Lower priority but contributes to long-term health.

- [ ] Cross-vertical links for projects that appear in multiple domains
- [ ] Open Graph tag verification (Twitter/LinkedIn card rendering)
- [ ] RSS feeds per domain (distribution channel for freshness signals)

## Commercial progression

The full journey from anonymous traffic to enterprise revenue is documented in [docs/commercial-plan.md](commercial-plan.md). Key points:

**Highest-priority commercial build: automated topical email digests.** This is the step we're completely missing — the 3→4 conversion where anonymous visitors become known contacts. Auto-generated weekly digests per domain from existing data (trending repos, score changes, new categories). No manual writing. Each digest links back to the site and includes an API promotion CTA.

**The API and key system already exist** but aren't promoted. Once we have email subscribers, API promotion is a line in the digest footer.

## Long-term: the data business

Once the flywheel is generating consistent organic traffic and temporal data reaches 90+ days:

### Quantitative analytics layer

- Moving averages and crossover signals on star velocity
- Factor analysis: quality, momentum, size, value (hype ratio), volatility
- Dependency risk indicators
- Ecosystem-level analytics: sector rotation, concentration risk

### Enterprise data API

The directory proves data quality for free. The analytics layer is the product. Pricing: $12K-36K/year for API access to the signal layer. The free directory is both the marketing surface and the trust-building mechanism. The full commercial funnel — from anonymous visit to enterprise contract in 8 steps — is in [docs/commercial-plan.md](commercial-plan.md).

### Community features

- "Claim your project" for maintainers (badges for READMEs, metadata editing)
- Feedback button on every page (wrong category, dead link, security concern)
- On-site search
