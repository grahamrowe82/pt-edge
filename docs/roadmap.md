# Roadmap

## What's done

- [x] 165,000+ page directory across 17 domains (MCP, agents, RAG, AI coding, voice AI, diffusion, vector DB, embeddings, prompt engineering, ML frameworks, LLM tools, NLP, transformers, generative AI, computer vision, data engineering, MLOps)
- [x] Quality scoring (0-100) with 4 sub-dimensions, daily refresh
- [x] 2,400 embedding-discovered categories via UMAP + HDBSCAN + Haiku labelling
- [x] Decision paragraphs on every category page (template-generated from live data)
- [x] AI summaries from READMEs (Haiku-generated, 2K/day backfill)
- [x] Template-generated metrics paragraphs on all detail pages
- [x] Daily metric snapshots for all 220K repos (stars, forks, downloads, commits)
- [x] 1536d embeddings for 220K+ repos (analytics/clustering)
- [x] JSON-LD structured data, sitemaps, cross-domain navigation
- [x] Served from FastAPI alongside MCP server and REST API
- [x] Strategy and roadmap docs baked into repo
- [x] Category discovery results saved to JSON for instant re-application
- [x] Site polish: about page, methodology page, favicon, cross-domain nav in header, proper category labels via Haiku, API docs integrated
- [x] Site audit critical fixes: broken footer, NOASSERTION license, empty trending, categories sync, risk flags repositioned
- [x] Domain reassignment via centroid similarity: 1,717 applied, 10K/day in daily ingest
- [x] Allocation engine: dual-score (Established Heat + Emergence), barbell strategy, daily snapshots, deep dive priority queue
- [x] Umami self-hosted analytics at a.phasetransitions.ai (replaces Render log analysis)
- [x] CTR-optimised title tags and meta descriptions across all 6 page types
- [x] Deep dive infrastructure: reverse links from server detail pages to deep dives via featured_repos
- [x] Voice AI deep dive (driven by GSC data showing voice-ai as strongest domain)
- [x] Deep dive process documented (docs/briefs/deep-dive-process.md)

## Near-term infrastructure

- [ ] **Cross-category comparison discovery:** Embedding similarity currently only runs within subcategories, so the most valuable matchups (WhisperX vs whisper.cpp, ElevenLabs vs edge-tts) are never generated. Needs domain-level comparison pass across top N projects regardless of subcategory.
- [ ] **Subcategory classifier quality:** High-quality repos land in wrong solo categories (e.g., ElevenLabs in `ai-workflow-automation` with 1 repo). This isolates them from comparisons and related servers. Investigate why the LLM classifier misclassifies and fix the process.
- [ ] **GSC-driven deep dive queue automation:** The allocation engine's `v_deep_dive_queue` identifies topics but doesn't generate alerts or reports. Add a weekly summary of top candidates.

## Remaining site quality items

- [ ] Noindex thin pages until AI summaries backfill reaches them
- [ ] Cross-vertical links for projects in multiple directories
- [ ] Open Graph tag verification (Twitter/LinkedIn card rendering)
- [ ] RSS feeds per domain
- [ ] Google Programmable Search Engine
- [ ] Changelog / "what's new" page generated from data
- [ ] Feedback button on every page

## Phase 3: Comparison pages + language pages

**Comparison pages:** Head-to-head for top viable options in each category. "FastMCP vs MCP SDK" — side-by-side scores, capability differences, "when to use each." Catches extremely high-intent "X vs Y" queries.

**Language pages:** "All Rust MCP servers." "All Python agent frameworks." Language is a primary developer filtering criterion.

Both create dense internal linking and catch long-tail search queries.

## Phase 4: Temporal layer

Once 30+ days of snapshots accumulate (~late April 2026):

- Sparklines on detail pages (30-day star/download trends)
- "Gained X stars this week" on detail pages
- Star velocity-based trending (replace empty trending pages)
- Momentum materialized view for ai_repos
- Growth classification: accelerating, steady, declining

## Phase 5: Cross-vertical stack pages

Precomputed workflow recommendations for common capability patterns:

- "Build a document Q&A pipeline" → embeddings + vector DB + RAG framework
- "Add voice search to your application" → STT + embeddings + vector DB
- "Create a code review agent" → coding agent + code analysis tools

Highest-value, most defensible page type — requires quality-scored data across all 17 domains.

## Phase 6: Connect-X-to-Y matrix

Pages for client x service pairings: "Connecting Claude Desktop to Postgres via MCP."

5 clients x 30 services = 150 pages. Each lists tools supporting the pairing, ranked by quality.

## Phase 7: Quantitative analytics layer (the terminal)

Once 90+ days of daily snapshots accumulate:

- Moving averages and crossover signals (golden cross / death cross on star velocity)
- Factor analysis: quality, momentum, size, value (hype ratio), volatility
- Synthetic signals: accumulation patterns, distribution patterns, dependency risk
- Ecosystem-level analytics: capital flows, sector rotation, concentration risk
- Enterprise API: $12K-36K/year for access to the signal layer

## Future considerations

- Embedding-based "similar projects" (pre-computed nearest neighbours)
- "Claim your project" for maintainers (badges for READMEs, metadata editing)
- Feedback button on every page (wrong category, dead link, security concern)
- RSS feeds per category/vertical
- Changelog / "what's new" page generated from data
- Google Programmable Search Engine for on-site search
