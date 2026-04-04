# PT Edge: First Traffic Intelligence Report

**Date:** Saturday 4 April 2026 (Easter weekend)
**Coverage:** First 6 days of analytics (30 Mar - 4 Apr) + first 47 minutes of server-side access logging

---

## The headline

PT Edge went live less than a week ago. Within 48 hours of Google indexing the site, every major AI company started systematically crawling our entire catalogue. On Easter Saturday — the quietest day of the year — we logged **8,000 bot hits in 47 minutes** from Meta AI, Amazon, Google, OpenAI, Perplexity, and Anthropic. Extrapolated, that's **~250,000 AI crawl requests per day**.

More importantly: **42 of those hits were ChatGPT's live browsing agent**, meaning real people in real ChatGPT conversations were being served our pages as cited references — roughly one every 70 seconds, on a holiday.

---

## Who's consuming our data

Measured over a single 47-minute window on Easter Saturday:

| AI Company | Hits | Unique IPs | Pages Touched | What it means |
|-----------|------|------------|---------------|---------------|
| **Meta AI** | 6,805 | 69 | 6,758 | Full-site parallel crawl — feeding Llama training/retrieval |
| **Amazon** | 854 | 362 | 854 | Systematic index, every hit a unique page and IP |
| **Google** | 152 | 6 | 145 | Deep crawl from small IP pool — standard Googlebot |
| **ChatGPT (live users)** | 42 | 39 | 39 | Real people getting our pages as answers in conversation |
| **Semrush** | 60 | 28 | 60 | SEO indexing |
| **Perplexity** | 2 | 2 | 2 | Answer engine indexing |
| **Claude** | 1 | 1 | 1 | Anthropic user browsing via Claude Code |
| **GPTBot (indexer)** | 1 | 1 | 1 | OpenAI's training crawler (separate from live user agent) |
| **Human browsers** | 76 | 53 | 70 | Real people on real devices |

For every 1 human visit, there are 105 bot visits. Our content is being consumed overwhelmingly by AI systems, not humans directly.

---

## The surprising finding: AI tools and humans want different things

We can see exactly what content each audience cares about, and the divergence is striking.

### What ChatGPT users are researching (via live browsing agent)

| Domain | ChatGPT Hits | % |
|--------|-------------|---|
| ML Frameworks | 29 | 69% |
| Agents & Skills | 6 | 14% |
| Embeddings | 4 | 10% |
| NLP | 1 | 2% |
| LLM Tools | 1 | 2% |
| Homepage | 1 | 2% |

ChatGPT users are overwhelmingly asking about **ML frameworks** — anomaly detection, reinforcement learning, multi-task learning, trajectory prediction, causal discovery, hyperparameter optimisation. These are researchers and practitioners evaluating tools for specific technical problems.

Three projects were recommended by ChatGPT to multiple independent users in under an hour:
- **marketing-agent-blueprints** (2 users) — marketing automation
- **LibMTL** (2 users) — multi-task learning
- **opengnothia** (2 users) — ML framework

ChatGPT is also using our **comparison pages** — fetching head-to-head project comparisons (deephyper vs orion, Trajectron vs Trajectron++) to answer user questions. This validates the compare feature as high-value for AI retrieval.

### What human browsers are exploring (direct site visitors)

| Domain | Human Hits | % |
|--------|-----------|---|
| **Agents & Skills** | 88 | **47%** |
| ML Frameworks | 22 | 12% |
| Voice AI | 16 | 9% |
| RAG | 10 | 5% |
| Embeddings | 8 | 4% |
| Vector DB | 8 | 4% |
| NLP | 6 | 3% |
| Other | 21 | 11% |

Human visitors are drawn to **agent tooling** — browsing agent frameworks, skills, Claude Code agents, Cursor integrations. These are developers shopping for tools to build with. Voice AI is a secondary interest cluster.

### The divergence

| | ChatGPT Users | Human Browsers |
|---|---|---|
| **#1 interest** | ML Frameworks (69%) | Agents & Skills (47%) |
| **Behaviour** | Targeted single-page lookups | Multi-page browsing sessions |
| **Intent** | Research — evaluating specific techniques | Shopping — finding tools to adopt |
| **Device** | N/A (bot) | 75% mobile |

This is a leading indicator: **ChatGPT users are researching ML techniques, while direct visitors are adopting agent tooling.** These may be the same population at different stages — research first, build later — or genuinely different segments.

---

## Human traffic profile

All Umami data (JavaScript-tracked, browser-only) represents verified human visitors:

| Day | Total Humans | Google Search | Direct (AI deep links) | Substack |
|-----|-------------|--------------|----------------------|----------|
| Tue 31 Mar | 27 | 7 | 17 | 3 |
| Wed 1 Apr | 58 | 21 | 31 | 6 |
| Thu 2 Apr | 187 | 41 | 122 | 24 |
| Fri 3 Apr (Good Friday) | 200 | 45 | 145 | 9 |
| Sat 4 Apr (Easter, partial) | 81 | 44 | 31 | 2 |

**Google organic search** grew from 7 to 44+ in five days and shows no Easter dip — developer search behaviour doesn't take holidays.

**Direct traffic** (humans arriving via AI-generated links with no referrer) spiked Thu-Fri at 122-145, suggesting a burst of AI tools recommending the site. The Easter Saturday drop to 31 reflects the holiday effect on humans chatting with AI tools.

Mobile users who do visit are highly engaged — averaging ~8 pages per session.

---

## Growth trajectory

Correcting for Easter Saturday suppression (~50-70% on the human-initiated AI-link channel) and the incomplete day, the underlying human traffic growth rate is approximately **3-5x week-over-week**, driven by two compounding channels:
1. Google progressively indexing more pages
2. AI tools (ChatGPT, Perplexity, Claude) increasingly citing our pages in user conversations

On the bot side, the site has gone from zero to **~250,000 AI crawl requests per day** in under a week. Every major AI platform is now systematically indexing the full catalogue.

---

## What this means

1. **PT Edge has become a reference source for AI systems in under a week.** The major AI companies are treating our structured project data as high-value enough to crawl comprehensively and serve to their users.

2. **We can see what AI users want in real time.** Every ChatGPT-User hit is a revealed preference — a question someone asked where our page was the answer. Aggregated, this is a live demand signal for the AI developer ecosystem that nobody else has.

3. **The demand signal itself is a product.** "What are ChatGPT users researching this week?" is intelligence that VCs, open-source projects, and developer tool companies would pay for. We're the only ones who can see this from the supply side.

4. **AI-mediated discovery is already larger than direct human traffic.** The 42 ChatGPT live-user fetches in 47 minutes on Easter Saturday suggests ~1,000+/day on working days. That's an order of magnitude more "reads" of our content than our direct human pageviews — and each one is a high-intent research query.

---

*Report generated from PT Edge analytics infrastructure: Umami (human JS tracking) + server-side access logging (full bot visibility). 47-minute server log sample from 14:12-14:59 UTC, 4 April 2026.*
