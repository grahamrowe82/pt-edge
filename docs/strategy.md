# PT-Edge Strategy: The Precomputed Reasoning Cache

*This document covers the first domain (Open Source AI). For the multi-domain vision — six scored knowledge graphs forming one interconnected layer — see [vision.md](vision.md).*

## What PT-Edge is

PT-Edge is the canonical reference for AI infrastructure decisions. It tracks 220,000+ AI repos across GitHub, PyPI, npm, Docker Hub, and HuggingFace, scores them daily on quality (maintenance, adoption, maturity, community), and publishes the results as a 165,000+ page directory site at mcp.phasetransitions.ai — covering 17 domains with 2,400 embedding-discovered categories.

The site is a precomputed reasoning cache. Every time an AI agent has to recommend, compare, or assemble AI infrastructure components, it performs a chain of reasoning: decompose the need, search for tools, evaluate quality, compare alternatives, synthesise a recommendation. This chain is expensive, unreliable, and duplicated across millions of queries. PT-Edge runs this chain once, properly, with complete data, and publishes the result.

## The two users

The site has two primary users, neither of whom is a human browsing directly.

**AI agents in chat interfaces.** When a user asks Claude (or any capable model) an AI infrastructure question, the agent runs a web search and lands on whatever pages rank highest. The agent needs to find a page that answers the question quickly, confidently, and completely — so it can cite the page and move on. Pages must be structured for fast extraction: clear recommendations, scored options, consistent metadata fields, front-loaded answers.

**Google's ranking algorithm.** Google decides which pages the agents land on. Google rewards freshness, topical authority, original analysis, structured data, internal linking density, and content that actually answers the query implied by the search terms. The site must be built so that Google sees it as the canonical authority on AI infrastructure tooling.

A third user — the human who lands on the site directly — is served as a byproduct of serving the first two well.

## What Google needs from us

Every page must earn its ranking by providing:

- **Information gain**: original analysis not available elsewhere (quality scores, decision paragraphs, comparisons, trend data)
- **Freshness**: visible content that changes on each crawl (scores, counts, dates in prose — not just a timestamp in the footer)
- **Topical authority**: depth, breadth, and internal coherence across 165K+ interlinked pages
- **Structured data**: JSON-LD markup for rich results (SoftwareApplication, Review, BreadcrumbList)
- **No thin content**: every page must justify its existence with substantive content — a smaller number of rich pages outranks a large number of empty shells
- **Dense internal linking**: 10-15 purposeful links per page, not 3-4
- **Titles and meta descriptions** that match search queries and communicate unique value
- **No duplicate content**: projects in multiple verticals need distinct framing per vertical

## What AI agents need from us

Every page must be structured so an agent can extract a confident recommendation in one pass:

- **Front-loaded answers**: the recommendation goes in the first sentence, not after a preamble
- **Consistent templates**: every page type follows a rigid, predictable layout
- **Explicit tradeoffs**: "X is better than Y if you need Z" — conditional, not just ranked
- **Negative signals**: warnings about deprecated, vulnerable, or abandoned tools
- **Freshness in prose**: "as of March 29, 2026, there are 47 Postgres MCP servers" — agents need explicit dates to cite with confidence
- **Numerical precision**: specific scores (78 vs 65), not just tier labels
- **Depth invitation**: every recommendation links to a detail page substantive enough to confirm it

## Why the gap exists

- **GitHub**: comprehensive but unnavigable — no quality scoring, no cross-project comparison
- **Awesome lists**: curated but stale — one person's opinion, frozen at last commit
- **SEO blog roundups**: written for search ranking, not accuracy — go stale on day one
- **Competitor directories** (PulseMCP, Glama, Smithery): catalogues, not recommendation engines — they answer "what exists?" but not "what should I use, and why?"
- **Vendor docs**: comprehensive for individual products but inherently biased and siloed

## What makes this defensible

**Quality scores are the moat.** Every other directory can list tools. Only PT-Edge scores them with transparent, multi-dimensional, daily-updated quality signals. The score transforms a catalogue into a recommendation engine.

**Breadth across 17 verticals.** PulseMCP can compete on MCP listings. Another site could compete on vector databases. Nobody can compete on cross-vertical recommendations because nobody else has the data across all domains.

**Programmatic freshness.** Blog roundups go stale on day one. PT-Edge regenerates every page, every day, from current data.

**Temporal depth.** Daily metric snapshots (stars, forks, downloads, commits) for all 220K repos create a historical record that literally cannot exist anywhere else because nobody else has been systematically tracking the ecosystem daily. As this accumulates, it enables a Bloomberg-terminal-style analytics layer: moving averages, momentum signals, factor analysis, accumulation/distribution patterns, dependency risk indicators.

**2,400 embedding-discovered categories.** Categories found by clustering actual project embeddings, not hand-crafted taxonomies. From `mongodb-mcp-servers` to `protein-design-mcp` to `ham-radio-data` — the long tail that no competitor has indexed.

## Where we win

Our edge is strongest where content supply is thin relative to search demand. This is not about absolute traffic volume — it's about the gap.

**The demand/supply gap.** The AI content ecosystem is heavily skewed toward LLMs, agents, and RAG — that's where the VC money, the Twitter hype, and the blog posts are. Categories like voice AI, embeddings, data engineering, MLOps, and computer vision are "plumbing" — essential for products but unsexy to write about. Nobody builds a personal brand around TTS library reviews. The people who need these tools are product engineers shipping features, not content creators. So there's real search demand but no supply of quality content.

Google Search Console confirmed this in our first week of data: voice-ai pages ranked at position 3 on a brand new domain with zero backlinks. Google placed us that high because it doesn't have three better options. Meanwhile, our agents/LLM content — objectively a stronger domain for us — ranked lower because the space is crowded with competitors.

**Breadth is the structural advantage.** A human expert writing about TTS libraries can't pivot to writing about vector databases overnight. Our system can — the data infrastructure is identical across all 17 domains. We can produce authoritative content on voice-ai, embeddings, MLOps, or computer vision with equal confidence because the quality scoring, category discovery, and daily refresh work the same everywhere. No competitor has this breadth.

**Google's position assignment is a market signal.** When Google puts a page from a 2-week-old domain at position 3, it's directly telling us the supply of quality content for that query is thin. We treat position data as a competitive intelligence signal, not just a vanity metric. High position + new domain = content gap = opportunity.

**The allocation engine finds the gap.** The scoring function uses Bayesian surprise to detect where actual search demand deviates from expected demand (based on repo distribution). A domain getting 10x its expected share of impressions is a strong signal even at low volumes. This is how voice-ai surfaced as the top priority — not because we predicted it, but because the data showed a 10x deviation from prior.

## Current state (March 2026)

- 220K+ repos tracked across 17 domains
- 165,000+ static pages with quality scores, metadata, risk flags, JSON-LD
- 2,400 embedding-discovered categories with decision paragraphs
- AI summaries from READMEs backfilling at 2,000/day via Haiku
- Template-generated metrics paragraphs on all detail pages
- Daily metric snapshots accumulating for all repos
- 1536d embeddings for 220K+ repos (for clustering and analytics)
- 256d embeddings for real-time search
- MCP server with 47 tools for programmatic access
- REST API with keyed access for B2B integrations

## The long-term position

The directory proves the data quality for free. The terminal is the product. As temporal data accumulates (90+ days), derived signals emerge: momentum crossovers, accumulation patterns, dependency risk, category velocity, quality stability indices. The pricing model is the enterprise data feed: $12K-36K/year for API access to the full signal layer, with the free directory as both the marketing surface and the trust-building mechanism.

PT-Edge becomes the canonical reference for AI infrastructure decisions — not by curating opinions, but by computing answers from data.
