# PT-Edge Strategy: The Precomputed Reasoning Cache

## What PT-Edge is

PT-Edge is the canonical reference for AI infrastructure decisions. It tracks 220,000+ AI repos across GitHub, PyPI, npm, Docker Hub, and HuggingFace, scores them daily on quality (maintenance, adoption, maturity, community), and publishes the results as a static directory site at mcp.phasetransitions.ai — currently 59,000+ pages across 9 domains.

The site is a precomputed reasoning cache. Every time an AI agent has to recommend, compare, or assemble AI infrastructure components, it performs a chain of reasoning: decompose the need, search for tools, evaluate quality, compare alternatives, synthesise a recommendation. This chain is expensive, unreliable, and duplicated across millions of queries. PT-Edge runs this chain once, properly, with complete data, and publishes the result.

## The two users

The site has two primary users, neither of whom is a human browsing directly.

**AI agents in chat interfaces.** When a user asks Claude (or any capable model) an AI infrastructure question, the agent runs a web search and lands on whatever pages rank highest. The agent needs to find a page that answers the question quickly, confidently, and completely — so it can cite the page and move on. Pages must be structured for fast extraction: clear recommendations, scored options, consistent metadata fields, front-loaded answers.

**Google's ranking algorithm.** Google decides which pages the agents land on. Google rewards freshness, topical authority, original analysis, structured data, internal linking density, and content that actually answers the query implied by the search terms. The site must be built so that Google sees it as the canonical authority on AI infrastructure tooling.

A third user — the human who lands on the site directly — is served as a byproduct of serving the first two well.

## Why the gap exists

The discovery surface for AI tooling has not kept pace with supply:

- **GitHub**: comprehensive but unnavigable — no quality scoring, no cross-project comparison
- **Awesome lists**: curated but stale — one person's opinion, frozen at last commit
- **SEO blog roundups**: written for search ranking, not accuracy — go stale on day one
- **Competitor directories** (PulseMCP, Glama, Smithery): catalogues, not recommendation engines — they answer "what exists?" but not "what should I use, and why?"
- **Vendor docs**: comprehensive for individual products but inherently biased and siloed

Result: when an AI agent searches for "MCP server Postgres," it lands on a mix of these sources and has to do significant synthesis work every time.

## What makes this defensible

**Quality scores are the moat.** Every other directory can list tools. Only PT-Edge scores them with transparent, multi-dimensional, daily-updated quality signals. The score transforms a catalogue into a recommendation engine.

**Breadth across 9 verticals.** PulseMCP can compete on MCP listings. Another site could compete on vector databases. Nobody can compete on cross-vertical recommendations because nobody else has the data across all domains.

**Programmatic freshness.** Blog roundups go stale on day one. Awesome lists go stale when the maintainer gets busy. PT-Edge regenerates every page, every day, from current data.

**Temporal depth.** Daily metric snapshots (stars, forks, downloads, commits) create a historical record that literally cannot exist anywhere else because nobody else has been systematically tracking the ecosystem daily.

## What Google needs from us

Every page must earn its ranking by providing:

- **Information gain**: original analysis not available elsewhere (quality scores, decision paragraphs, comparisons, trend data)
- **Freshness**: visible content that changes on each crawl (scores, counts, dates in prose — not just a timestamp in the footer)
- **Topical authority**: depth, breadth, and internal coherence across thousands of interlinked pages
- **Structured data**: JSON-LD markup for rich results (SoftwareApplication, Review, BreadcrumbList)
- **No thin content**: every page must justify its existence with substantive content — a smaller number of rich pages outranks a large number of empty shells
- **Dense internal linking**: 10-15 purposeful links per page, not 3-4

## What AI agents need from us

Every page must be structured so an agent can extract a confident recommendation in one pass:

- **Front-loaded answers**: the recommendation goes in the first sentence, not after a preamble
- **Consistent templates**: every page type follows a rigid, predictable layout
- **Explicit tradeoffs**: "X is better than Y if you need Z" — conditional, not just ranked
- **Negative signals**: warnings about deprecated, vulnerable, or abandoned tools
- **Freshness in prose**: "as of March 28, 2026, there are 47 Postgres MCP servers" — agents need explicit dates to cite with confidence
- **Numerical precision**: specific scores (78 vs 65), not just tier labels

## Current state (March 2026)

- 220K+ repos tracked across 17 domains
- 9 directory verticals live: MCP, agents, RAG, AI coding, voice AI, diffusion, vector DB, embeddings, prompt engineering
- 59,000+ static pages with quality scores, metadata, risk flags, JSON-LD
- AI summaries from READMEs being backfilled (2,000/day via Haiku)
- Template-generated metrics paragraphs on all detail pages (live data, no LLM)
- Daily metric snapshots accumulating for all repos (stars, forks, downloads, commits)
- MCP server with 47 tools for programmatic access
- REST API with keyed access for B2B integrations
