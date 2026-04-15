# AI Supply Thesis

*Emerging strategy memo — April 2026*

This document captures a strategic thesis that sharpened through two weeks of observing AI crawler and citation behaviour on the live site. It sits alongside [strategy.md](strategy.md) (competitive positioning), [commercial-plan.md](commercial-plan.md) (user journey to revenue), and [vision.md](vision.md) (six-domain architecture). It doesn't replace any of those — it adds a lens that the data is now supporting.

## The core bet

The internet is splitting into two economies. The human web is paywalled, ad-supported, engagement-optimised, and increasingly hostile to AI consumption (robots.txt blocks, Cloudflare bot protection, legal battles over training data). The AI-readable web barely exists.

AI labs are desperate for high-quality, structured, fresh, citable sources. Their current approach — scraping a hostile web — doesn't scale. At some point they'll need *willing suppliers* of structured data, the same way Google needed willing webmasters in 2002 and built AdSense to pay them.

**PT-Edge is positioning as supply-side infrastructure for the AI economy.** Not an AI-powered app for humans. Not a tool that uses AI. A structured data source that AI systems consume as a primary customer. Humans benefit indirectly — through better answers from ChatGPT, through click-throughs from AI citations.

This is contrarian because almost everyone in the AI space is building *with* AI or *on* AI. Almost nobody is building *for* AI — being a supplier to the AI layer rather than a consumer of it. The supply side of AI knowledge is wildly underinvested because it doesn't look like a tech startup.

## What the data shows

Two weeks of access log and bot tracking data (April 4–15, 2026) produced signals that were not anticipated.

### AI agents are citing us at scale

ChatGPT-User (the bot that fires when a real person's AI assistant fetches a page to answer their question) went from 355/day to 1,532/day in 11 days. That's ~30% week-over-week growth. The hourly pattern is remarkably steady — 50–90 hits/hour, every hour, with no dependency on promotion or content pushes. This isn't viral traffic. It's utility traffic. We've become infrastructure.

### AI systems made autonomous decisions to invest in us

GPTBot went from 0 to 47K hits/day after OAI-SearchBot (the retrieval bot) proved the content was useful. This wasn't a scheduled crawl — the retrieval signal triggered the training crawl. ClaudeBot independently did a 264K-page single-day deep ingest. PerplexityBot and Bytespider also ramped. Four competing AI companies, unprompted, decided our content was worth deeply indexing based on observed quality.

### Trust carries to new properties

The cyber site (cyber.phasetransitions.ai) launched on April 14. GPTBot found it and started crawling within minutes — no sitemap, no backlinks, no DNS history. It consumed 80K unique pages in its first 14 hours. ClaudeBot joined 90 minutes after launch. Claude-User (real user citations) appeared within 3 minutes. This suggests domain-level reputation transfer — the trust built on mcp.phasetransitions.ai carries to new properties under the same origin.

### The demand reveals underserved niches

OAI-SearchBot fan-outs — where a single user query triggers 50–800 page fetches across a topic — provide a direct map of questions AI assistants are struggling to answer from existing sources. These fan-outs cluster around professional niches (algorithmic trading, anomaly detection, wireless signal processing) where practitioners ask specific tool-comparison questions and no structured source exists.

## The two KPIs

If this thesis is correct, the business tracks two numbers.

### 1. Daily AI Citations

**Definition:** The number of times per day a real person's AI assistant fetches one of our pages to answer their question.

**How we count:** Sum of hits from user-agent strings that identify AI assistants acting on behalf of a human in a conversation:
- ChatGPT-User (OpenAI)
- OAI-SearchBot (OpenAI retrieval)
- Claude-User (Anthropic)
- Perplexity-User (Perplexity)
- DuckAssistBot (DuckDuckGo AI)

These are distinct from training crawlers (GPTBot, ClaudeBot) which ingest content speculatively. Citation bots fetch a page because a human asked a question *right now*.

**Caveat on OAI-SearchBot:** It does fan-outs — one user question can trigger hundreds of fetches. The raw count measures *pages served to AI* (value delivered). Deduplicating bursts within a 60-second window gives *estimated conversations served* (humans helped). Both are worth tracking.

**Current state (April 15, 2026):** ~3,000–5,000 raw daily citations. ~30% week-over-week growth.

### 2. Trusted Pages (Favorites)

**Definition:** The number of pages that AI assistants keep coming back to across multiple days — not one-off fetches, but pages that have become a habitual source.

**How we count:** A page enters the set when it has been cited (by any Tier 1 user bot listed above) on **3 or more distinct calendar days** within the trailing 30-day window. A page exits the set if it hasn't been cited in the last 14 days.

**Why those thresholds:**
- 3 distinct days filters out fan-out noise and one-off fetches. Three different people on three different days, each getting this page as their answer — that's earned trust.
- 14-day recency window means dead pages fall out. The set reflects current authority.
- 30-day lookback gives enough time for pages to qualify without requiring daily citations.

**Current state (April 15, 2026):** 746 trusted pages. Growing at ~80–100 new pages per day. Roughly doubling weekly (36 on Apr 6 → 746 on Apr 15).

## Where we have an emerging monopoly

### The beachhead: specialist ML tooling

587 of 746 trusted pages (79%) are in the ml-frameworks domain. This is where AI systems have decided we're the default source for tool-quality questions.

The monopoly isn't in "ML frameworks" broadly — it's in specific professional niches where practitioners ask AI assistants tool-comparison questions and no structured source exists:

| Niche | Trusted pages | Strong (8+ days) | Character |
|-------|---------------|-------------------|-----------|
| Algorithmic trading bots | 14 | 3 | Finance + ML intersection |
| Anomaly detection systems | 14 | 2 | Enterprise ML |
| Time series forecasting | 12 | 0 | Growing fast |
| Portfolio optimisation ML | 10 | 2 | Finance + ML intersection |
| Reinforcement learning frameworks | 10 | 0 | Broad but we're winning |
| Chemical property ML | 9 | 0 | Science niche |
| Wireless signal processing | 8 | 3 | Deep niche, very high trust |
| LaTeX OCR tools | 8 | 2 | Tiny niche, very high trust |
| EEG/brain signal processing | 7 | 1 | Biotech niche |
| Audio source separation | 6 | 2 | Media/audio niche |

The pattern: **ML applied to a specific professional domain.** Not "how to use PyTorch" (saturated) but "what's the best library for anomaly detection in time series" (nobody else covers this with structured data).

The star-count sweetspot for trusted pages is **100–5,000 stars** — projects that are real and used, but underserved by existing content. This range is 5–20x over-represented in the favorites set relative to the catalog. Below 50 stars, about 30% of favorites are sub-50-star repos — long tail pages that are essentially free to generate but still win citations because they're the only structured assessment.

### Concentric rings

- **Ring 0 (monopoly):** ml-frameworks — 587 trusted pages, 54 strong favorites, deep subcategory coverage.
- **Ring 1 (emerging):** embeddings (51), agents (39). Growing but haven't reached ml-frameworks' trust density. Agent governance is a standout niche.
- **Ring 2 (early signal):** voice-ai (14), nlp (17), transformers (10), vector-db (6). Favorites forming, subcategory depth not there yet.
- **Ring 3 (opportunity):** ai-coding (4), rag (2), llm-tools (3). Hot topics but saturated by other sources. Our coverage isn't differentiated enough to win citations.

### Compare pages as high-value assets

35 compare pages are in the trusted set (27 in ml-frameworks). These directly answer "which should I use, X or Y?" — the highest-intent question type. AI systems are using these for decision-support answers. This page type punches above its weight relative to catalog share.

## How to deepen the monopoly

The citation data creates a proprietary feedback loop:

1. **Observe fan-out clusters** — which pages get fetched together by OAI-SearchBot? That's the AI trying to synthesise an answer to a question we haven't directly addressed. Each fan-out is a map of a demand gap.

2. **Precompute the synthesis** — build a landscape/decision page that directly answers the question the AI is currently assembling from multiple server pages. One fetch instead of eight. More reliable answer for the AI. Lower compute cost for the AI lab.

3. **Measure uptake** — does the new page become a trusted page? Does it replace the multi-page fan-out with a single citation?

4. **Repeat** — the new page generates new citation patterns that reveal the next layer of questions.

### How this differs from editorial content

A human-oriented "Top 10" blog post uses narrative, opinion, and hedging ("it depends on your use case"). A landscape page uses none of that. The signal *is* the content: these N projects, out of M tracked, are the ones AI agents keep coming back to. The data speaks for itself. No editorial voice required, no LLM enrichment needed, fully deterministic from existing DB fields.

## Landscape pages: acting on the signal

The favorites set doesn't just measure trust — it reveals which projects matter, regardless of GitHub popularity. The next step is building **landscape pages** that surface this signal as content.

### What a landscape page is

A landscape page aggregates everything we know about the favorites in a single subcategory. For algorithmic trading bots, that's 14 projects. Not the top 14 by quality score. Not the top 14 by stars. The 14 that AI agents keep citing to real users. That's a fundamentally different list and one nobody else can produce.

The page is **entirely deterministic** — no new LLM calls, no editorial curation. It pulls from existing data:
- The favorites list itself (from citation tracking)
- Quality scores, stars, language, last commit (from `ai_repos` + quality MVs)
- `use_this_if` / `not_ideal_if` (already LLM-enriched on server pages)
- `ai_summary` (already in the DB)
- Days cited / trust depth (from access logs)
- Cross-links to each server page and the subcategory page

What it does **not** include: editorial decision paths ("if you want X, use Y"), synthesised lead paragraphs picking winners, or any content that requires human judgement or LLM generation. The implicit signal — these 14, out of 242 — is the ranking.

### Why the favorites set, not quality scores

The existing category page already ranks all 242 projects by quality score. A landscape page that does the same thing with a nicer layout adds nothing.

What we uniquely know is which projects are actually being asked about. And the surprises prove the signal is real:

- `pawanjangid7017/How-To-Backtest-Correctly` — **0 stars, 0 forks, cited 4 days.** A guide to implementing Lopez de Prado's backtesting methods. The people asking about this aren't developers — they're traders who've read the theory and want to implement it.
- `danielsilvaperez/kalshi-trading-bot` — **0 stars, cited 3 days.** Kalshi BTC volatility scalper. An extremely specific, extremely current use case (regulated prediction markets) that almost nobody has written about.
- `CrunchyJohnHaven/elastifund` — **2 stars, cited 4 days.** Self-improving agent for Polymarket and Kalshi. Same prediction markets cluster.
- `GifariKemal/xaubot-ai` — **8 stars, cited 3 days.** Gold-specific trading on MetaTrader 5. Someone is asking about automating gold trading specifically.
- `Divyansh487/TradingAgents-CN` — **5 stars, cited 3 days.** Chinese market focus. Likely diaspora investors or Western funds exploring Chinese exposure.

These projects would never appear on any "best of" list. GitHub stars measure developer interest. Our favorites set measures **end-user intent** — people who want to *use* something, not people who want to *build* something. Those two populations barely overlap.

The prediction markets cluster (Kalshi, Polymarket) is particularly notable — it reveals an emerging asset class where demand for tooling is growing fast but the developer community hasn't caught up. We're seeing the demand before it shows up in stars.

### The hidden demand signal

The favorites data reveals demand that doesn't exist anywhere on the public internet:

1. **GitHub stars** measure what developers think is cool. Our data measures what practitioners actually need.
2. **Google Search Console** tells you what people type into search. Our data tells you what people ask AI assistants — a different population asking different questions.
3. **Stack Overflow / Reddit** capture explicit questions from people who know enough to formulate them. Our data captures the questions from people who don't know the right terminology — they describe what they want to *do* and the AI finds the tool.

This is proprietary signal. Nobody else has it because nobody else is building sites designed for AI consumption and then measuring the consumption patterns.

### Implementation

Landscape pages should be generated as part of the site build:

1. Query the favorites set (3+ distinct citation days in trailing 30 days, cited within last 14 days)
2. Group by subcategory where count >= a threshold (5 is a reasonable starting point)
3. For each qualifying subcategory, build a page from existing DB fields — no new LLM calls
4. Sort by days_cited (trust depth), not quality score
5. Cross-link: each server page in a landscape gets a backlink ("one of N actively cited projects in this landscape")
6. Regenerate daily — the set evolves as citation patterns change

A prototype for algorithmic trading bots was built locally at `site/landscapes/algorithmic-trading-bots/` (gitignored since `site/` is generated output). The design decisions from that prototype are documented below.

### Page structure (from the prototype)

The page has four sections, in order:

**1. Header and framing.** Title: "{Subcategory}: {N} Projects AI Agents Actually Cite". Subtitle explains what the page is: of M total tracked, these N are the ones AI assistants consistently cite. States the data source (live citation tracking across ChatGPT, Claude, Perplexity). States the date. This framing is critical — it tells both humans and AI agents that this is a demand-derived selection, not an editorial one.

**2. Favorites table.** All N favorites, sorted by `days_cited` descending (trust depth). Columns:
- Project (full_name, linked to server page)
- Days cited (bold — this is the primary ranking)
- Quality score + tier badge
- Stars (hidden on mobile)
- Language (hidden on mobile)
- Last commit date (hidden on mobile)

No "best for" column. No editorial labels. The table is pure data. The AI consuming this page can read `use_this_if` on the linked server page if it needs to match against a user's context.

**3. Project detail cards.** One card per favorite, containing:
- Name linked to server page, quality score, tier badge, and "cited X of Y days"
- `ai_summary` or `description` — whichever exists (already in DB)
- `use_this_if` / `not_ideal_if` in green/amber boxes (already LLM-enriched, only shown if present)
- Metadata line: stars, forks, language, last commit, commits/30d
- GitHub link

For projects with 0 or near-0 stars that are still in the favorites set, add a "high hidden demand" badge. This is the most differentiated signal we have — it highlights projects that practitioners are asking about through AI assistants but that have no visibility on GitHub. The badge is deterministic: show it when `stars < 10 AND days_cited >= 3`.

**4. Cross-links.** Links to:
- The full subcategory page ("All M projects in this category")
- Related subcategories (e.g., algorithmic-trading-bots links to portfolio-optimization-ml, time-series-forecasting)
- Methodology page

### Structured data (JSON-LD)

The page embeds a `CollectionPage` with an `ItemList` of the top favorites. The `itemListOrder` is explicitly `ItemListOrderDescending` (by citation depth). Each item is a `SoftwareApplication` with a PT-Edge `Review` and `Rating`. This allows AI systems to parse the recommendations without interpreting HTML.

### What the page does NOT contain

These were deliberately excluded after iterating on the prototype:

- **No projects outside the favorites set.** The page is about the N that matter, not the M that exist. The full category page already covers the M.
- **No editorial decision paths** ("if you want X, use Y"). These require human judgement or LLM generation and can't be deterministically produced. The `use_this_if` field on each project card serves the same function without editorial synthesis.
- **No synthesised lead paragraph** picking winners. The table sorted by days_cited is the ranking. An AI agent reading this page doesn't need a prose summary telling it which project is best — it can read the structured data.
- **No "best for" column** in the table. This would require per-row editorial judgement. The `use_this_if` data exists but belongs on the detail card, not compressed into a table cell.
- **No quality-score ranking.** The existing category page already does this. Landscape pages rank by citation depth because that's the proprietary signal.

### Backlinks from server pages

Each server page that appears in a landscape should get a backlink: "This project is one of N actively cited {subcategory} projects." This creates the cross-linking network and signals to both humans and AI agents that the project has been validated by citation data, not just scored by an algorithm.

## Cyber as proof of replayability

CyberEdge (cyber.phasetransitions.ai) launched April 14, 2026 using the same pattern: ingest a canonical data source (NVD/MITRE), compute quality/risk scores over entities (CVEs, products, vendors), publish as a structured static site.

GPTBot crawled 80K pages in 14 hours. ClaudeBot did 36K. Claude-User cited it within 3 minutes of launch.

This validates that the playbook is repeatable across domains. The same infrastructure, the same content architecture, the same crawlability principles — applied to cybersecurity instead of AI tooling — produced the same crawler response. The [vision doc](vision.md) describes six domains; cyber is evidence that the multi-domain thesis works.

## The business model question

**There isn't one yet.** This should be stated honestly.

- **Zero authenticated API calls.** 9 API keys exist, none used. The [B2B API buyer hypotheses](briefs/pt-edge-api-buyers.md) haven't found demand.
- **Zero MCP revenue.** Real MCP tool calls from non-test users: zero. Every connection is handshake-only bots.
- **Zero paying customers.** No inbound interest has converted.
- **Google Ads** are enabled as a low-friction experiment, but at current human traffic levels (~60–80 real daily visitors), revenue would be negligible.

The thesis is that the value is currently being captured by AI labs for free. They're getting precomputed reasoning at the cost of an HTTP fetch. When the human web closes off further and the AI labs need willing, structured data suppliers, payment rails will emerge — analogous to Google creating AdSense, or news organisations negotiating licensing deals with AI companies (which is already happening).

In the meantime, the strategic position is:
- **Keep the asset growing.** More domains, deeper coverage, fresher data. The moat compounds daily.
- **Build the demand signal.** The citation data and favorites tracking are proprietary intelligence about what AI systems need. This data itself may be the most valuable asset.
- **Stay patient.** This is funded by consulting revenue, not venture capital. The luxury of patience is a structural advantage — no pressure to force a business model before the market exists.

The [commercial plan](commercial-plan.md) describes a human-centric funnel (anonymous visitor → email subscriber → API user → enterprise customer). That funnel may still work. But the AI-supply thesis suggests a parallel path: the customer might not be the human developer at all. It might be the AI lab, the AI-powered search engine, or the next platform that needs structured data to ground its answers.

## What this memo is not

This is not a pivot. The existing strategy, roadmap, and commercial plan remain valid as parallel tracks. This memo captures an additional lens — that the most interesting signal from the first two weeks of observability data is not the human traffic (which is small) or the API usage (which is zero) but the AI citation behaviour (which is large, growing, and structurally unusual).

The bet is that this signal is early evidence of a market that doesn't have payment rails yet but will. The risk is that it never materialises and we're just a free resource for AI companies. The cost of being wrong is hosting bills. The upside of being right is being the established, trusted supplier when the market catches up.
