# Roadmap

## What's done

- [x] Static directory site serving 59K+ pages across 9 domains
- [x] Quality scoring (0-100) with 4 sub-dimensions, daily refresh
- [x] Subcategory classification for all 9 domains (regex + LLM)
- [x] AI summaries from READMEs (Haiku-generated, 2K/day backfill)
- [x] Template-generated metrics paragraphs (live data on every page)
- [x] Daily metric snapshots for all 220K repos (stars, forks, downloads, commits)
- [x] JSON-LD structured data, sitemaps, cross-domain navigation
- [x] Served from FastAPI alongside the MCP server and REST API
- [x] Daily deploy hook triggers rebuild after ingest

## Phase 1: Use-case pages with decision layer

The highest-leverage gap. Pages currently organised by supply ("here are all MCP servers") but not by demand ("here are the ones for Postgres"). Use-case pages match the exact queries users ask agents.

**What to build:**
- Mine descriptions/READMEs/topics for service/technology names (Postgres, Slack, GitHub, etc.)
- Generate use-case pages: "MCP Servers for PostgreSQL" — 47 options ranked by quality
- Each page opens with a decision paragraph: how many options, quality distribution, key tradeoffs, conditional recommendations ("best for read-only" vs "best for read-write")
- Decision paragraph is template-generated from structured data + LLM for tradeoff articulation
- Start with MCP vertical (most active), top 50-100 use-case clusters

**Why it matters:**
- Directly matches the search queries agents run
- The decision paragraph is what agents cite — it's the precomputed reasoning
- Creates massive new indexable surface with high-intent long-tail keywords

## Phase 2: Replicate use-cases across verticals

Same use-case page template applied to agents, RAG, vector databases, and remaining domains. The template is identical; only the data source changes.

- "RAG tools for PDF processing"
- "Agent frameworks for browser automation"
- "Embedding models for code search"

Multiplies the indexable surface and establishes cross-vertical topical authority.

## Phase 3: Comparison pages + language pages

**Comparison pages:** Head-to-head for top viable options in each use-case cluster. "FastMCP vs MCP SDK" — side-by-side scores, capability differences, "when to use each." These catch extremely high-intent "X vs Y" queries.

**Language pages:** Browse-by-language views. "All Rust MCP servers." "All Python agent frameworks." Language is a primary developer filtering criterion — making it a first-class dimension adds a major browsable axis.

Both create dense internal linking and catch long-tail search queries.

## Phase 4: Temporal layer

Once enough daily snapshots accumulate (30+ days):

- Sparklines on detail pages (30-day star/download trends)
- "Gained X stars this week" on detail pages
- Star velocity-based trending (more intuitive than quality score deltas alone)
- Momentum materialized view for ai_repos (stars_7d_delta, stars_30d_delta, dl_30d_delta)
- Growth classification: accelerating, steady, declining

This is the freshness moat — visible, daily proof that the data is current.

## Phase 5: Cross-vertical stack pages

Precomputed workflow recommendations for common capability patterns:

- "Build a document Q&A pipeline" → needs embeddings + vector DB + RAG framework
- "Add voice search to your application" → needs STT + embeddings + vector DB
- "Create a code review agent" → needs coding agent + code analysis tools

Each stack page draws scored recommendations from whichever verticals are relevant. This is the highest-value, most defensible page type — requires quality-scored data across all 9 domains.

## Phase 6: Connect-X-to-Y matrix

Pages for client × service pairings: "Connecting Claude Desktop to Postgres via MCP."

Start with 5 clients (Claude Desktop, Cursor, Claude Code, VS Code, Windsurf) × 30 services = 150 pages. Each page lists which tools support the pairing, ranked by quality, with transport compatibility notes.

## Future considerations

- **Remaining domains**: ml-frameworks (45K repos), llm-tools (24K), nlp (13K), transformers (5K), generative-ai (4.5K) — need subcategory taxonomies before they're useful as directories
- **Embedding-based "similar projects"**: pre-computed nearest neighbours for better related-project suggestions across categories and domains
- **"Claim your project"**: let maintainers verify ownership and add metadata — badges for READMEs ("PT-Edge Verified"), installation instructions, changelogs
- **Enterprise data feeds**: the $12K-36K/year B2B contracts — the directory proves data quality, the feed is the product
