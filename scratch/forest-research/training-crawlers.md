# Training Crawler Analysis: Meta-ExternalAgent and Amazonbot

**Date:** 2026-04-05
**Log window:** 2026-04-04 14:12 UTC to 2026-04-05 11:54 UTC (~22 hours)
**Total log rows:** 163,975

---

## 1. Meta-ExternalAgent

### Scale

- **126,903 hits** in ~22 hours — **77% of all logged traffic**
- **114,701 unique paths** visited
- All requests returned HTTP 200 (zero errors)

### Crawl Rate Over Time

| Hour (UTC)      | Hits   |
|-----------------|--------|
| Apr 4, 14:00    | 6,611  |
| Apr 4, 15:00    | 2,253  |
| Apr 4, 16:00    | 11,024 |
| Apr 4, 17:00    | 11,433 |
| Apr 4, 18:00    | 6,499  |
| Apr 4, 19:00    | 1,103  |
| Apr 4, 20:00    | 2,963  |
| Apr 4, 21:00    | 6,286  |
| Apr 4, 22:00    | 6,077  |
| Apr 4, 23:00    | 6,187  |
| Apr 5, 00:00    | 8,315  |
| Apr 5, 01:00    | 10,399 |
| Apr 5, 02:00    | 5,625  |
| Apr 5, 03:00    | 1,894  |
| Apr 5, 04:00    | 5,161  |
| Apr 5, 05:00    | 5,718  |
| Apr 5, 06:00    | 10,651 |
| Apr 5, 07:00    | 10,481 |
| Apr 5, 08:00    | 7,132  |
| Apr 5, 09:00    | 861    |
| Apr 5, 10:00    | 141    |
| Apr 5, 11:00    | 89     |

**Pattern:** Bursty, not steady. Alternates between ~10K/hr peaks and ~2K/hr troughs. Slowed dramatically after 09:00 on Apr 5 — possibly finished crawling available pages, or a rate-limit window. Average: ~5,768 hits/hour during active crawling.

### Fleet Composition

- **69 unique IPs**, all in the `57.141.6.x/24` subnet
- Load balanced almost perfectly: each IP handled 1,864-1,940 hits (spread of only 4%)
- This is a single coordinated fleet, not distributed infrastructure

### Crawl Strategy

**Systematic sitemap-following.** Evidence:

1. **Path ordering is NOT alphabetical.** The first 50 crawled paths span random domains (servers, compare pages) — consistent with traversing a sitemap or link graph, not an alpha sort.
2. **Median inter-request gap: 317ms** (avg 730ms). Multiple concurrent connections hitting different pages in parallel.
3. **90% of paths visited exactly once** (103,213 of 114,701). Only 10,825 paths visited twice, 615 three times, 49 four times. This is a breadth-first full-site scrape, not a recrawl.
4. All top-30 paths have exactly 4 hits — no heavy concentration on specific pages.

### What It Crawls

| Page Type         | Hits    | % of Total |
|-------------------|---------|------------|
| domain/servers    | 104,188 | 82.1%      |
| servers (root)    | 8,698   | 6.9%       |
| domain/compare    | 7,725   | 6.1%       |
| domain/categories | 3,836   | 3.0%       |
| compare (root)    | 2,393   | 1.9%       |
| other             | 63      | <0.1%      |

**Domain breakdown (top 10):**

| Domain             | Hits   |
|--------------------|--------|
| ml-frameworks      | 32,978 |
| llm-tools          | 24,784 |
| agents             | 23,712 |
| ai-coding          | 6,730  |
| voice-ai           | 6,653  |
| transformers       | 6,628  |
| rag                | 6,503  |
| prompt-engineering | 4,047  |
| embeddings         | 3,291  |
| vector-db          | 457    |

Meta is crawling the entire site. Server/project pages dominate because they are the bulk of the directory.

### Latency Impact

| Metric | Value |
|--------|-------|
| avg    | 2 ms  |
| p50    | 1 ms  |
| p95    | 3 ms  |
| p99    | 6 ms  |
| max    | 18,841 ms |

**No latency concern.** Pages are served from static cache. The p99 at 6ms means Meta is not causing any load. The 18.8s max is a single outlier (likely a cold-start or deployment).

---

## 2. Amazonbot

### Scale

- **18,625 hits** in ~22 hours — **11.4% of all traffic**
- **18,635 unique paths** (every single request hit a different page)
- All requests returned HTTP 200

### Crawl Rate Over Time

**Remarkably steady:** 700-895 hits per hour, every hour, with no bursting. This is a constant-rate polite crawler.

Average: ~847 hits/hour.

### Fleet Composition

- **432 unique IPs** across AWS IP space (3.x, 18.x, 34.x, 44.x, 50.x, 52.x, 54.x)
- Each IP handles 69-82 requests — highly uniform distribution
- Distributed across multiple AWS regions, unlike Meta's single /24 block
- **Median inter-request gap: 4,036ms** (~4 seconds). Much more polite than Meta.

### Crawl Strategy

**Systematic, one-hit-per-page.** Evidence:

1. Every single path visited exactly once (18,635 unique paths, 18,625 hits — essentially 1:1)
2. Requests spaced ~4 seconds apart consistently
3. Path ordering is random across domains — sitemap or link-graph traversal, not alphabetical
4. Covers all domain verticals including nlp, diffusion, computer-vision, generative-ai — domains that Meta also covers

### What It Crawls

| Page Type         | Hits   | % of Total |
|-------------------|--------|------------|
| domain/servers    | 16,237 | 87.2%      |
| servers (root)    | 1,778  | 9.5%       |
| domain/compare    | 441    | 2.4%       |
| compare (root)    | 138    | 0.7%       |
| domain/categories | 34     | 0.2%       |

**Domain breakdown (top 10):**

| Domain             | Hits  |
|--------------------|-------|
| agents             | 3,093 |
| llm-tools          | 2,984 |
| ml-frameworks      | 2,698 |
| nlp                | 1,790 |
| rag                | 1,061 |
| transformers       | 796   |
| voice-ai           | 764   |
| generative-ai      | 734   |
| diffusion          | 645   |
| prompt-engineering | 533   |

Amazonbot covers more domain verticals than Meta (includes nlp, diffusion, computer-vision, generative-ai) but with far fewer total pages.

### Latency Impact

| Metric | Value |
|--------|-------|
| avg    | 9 ms  |
| p50    | 1 ms  |
| p95    | 3 ms  |
| p99    | 6 ms  |
| max    | 18,852 ms |

**No latency concern.** Same profile as Meta — static pages served in 1-3ms. The avg is pulled up by a single outlier.

---

## 3. Overlap with AI User-Action Bots

AI user-action bots (ChatGPT-User, OAI-SearchBot, Perplexity-User) visited **986 unique paths** in the same window.

| Metric | Count |
|--------|-------|
| AI bot unique paths | 986 |
| Meta unique paths | 114,701 |
| Overlap (both Meta + AI bots) | 652 |
| AI-bot-only (not in Meta) | 334 |

**66% of pages visited by AI agents were also crawled by Meta.** Since Meta crawled 114K pages and AI bots only visited 986, the overlap is simply a function of Meta's near-total coverage.

### Meta vs Amazonbot Overlap

| Metric | Count |
|--------|-------|
| Amazonbot unique paths | 18,639 |
| Overlap with Meta | 11,735 |
| Amazonbot-only paths | 6,904 |

**63% of Amazonbot pages overlap with Meta.** The remaining 37% (6,904 pages) were crawled by Amazonbot but not Meta — likely because Meta's crawl is still in progress (it slowed dramatically after 09:00 UTC).

---

## 4. Key Findings

### Meta-ExternalAgent is the dominant crawler

- 77% of all traffic in the log window
- 69-node fleet from a single /24 subnet, perfectly load-balanced
- Systematic breadth-first scrape: 114K unique pages, most visited once
- Sub-second inter-request gaps — aggressive but not causing latency issues due to static serving
- This is almost certainly **training data collection**, not search indexing (Meta doesn't operate a search engine; this feeds Llama training)

### Amazonbot is a polite background crawler

- 11% of traffic, steady ~850/hr rate
- 432 IPs across AWS — truly distributed
- 4-second crawl delay — respectful of robots.txt crawl-delay
- Every page visited exactly once — reconnaissance/indexing crawl
- Likely feeding **Alexa/Rufus AI** features or **Amazon search**

### Neither causes performance issues

- p95 latency is 3ms for both crawlers
- Static site serving absorbs the load trivially
- No 4xx or 5xx responses — both crawlers see a healthy site

### The combinatorial forest is real

Meta crawled 114K pages in 22 hours. With 220K+ pages in the directory, this is a ~52% sweep in under a day. The page volume that makes the site valuable to Google also makes it a target for LLM training crawlers. These crawlers are consuming the content that PT-Edge generates — which validates the "combinatorial forest" thesis that large page counts attract crawler attention at scale.

---

## 5. Per-Bot Strategy Intelligence (Updated Apr 6)

The 48-hour dataset reveals that each indexing bot has a distinct crawl strategy that
functions as a fingerprint of its parent company's priorities. These aren't random
crawlers — they're intelligence-gathering operations with characteristic signatures.

### Meta-ExternalAgent: The Revisitor

- **20,984 perception domain hits** but only **10,644 unique pages** = ~2:1 revisit ratio
- Meta is re-crawling pages it considers important, not just sweeping breadth-first
- Prioritises perception/computer-vision — consistent with Llama multimodal roadmap
- 69-node fleet from a single /24 subnet, perfectly load-balanced
- **Signal:** Revisit frequency is a quality/freshness proxy. Pages Meta re-crawls
  every 6 hours are ones it considers high-value and time-sensitive.

### ClaudeBot: The Completionist

- **~181K hits**, near **1:1 hit-to-unique-page ratio** — trying to inhale the entire site
- Single aggressive IP with **628 req/min peaks**
- No apparent domain preference — wants everything equally
- **Signal:** ClaudeBot coverage ratio (unique pages hit / total pages in category)
  measures how thoroughly Anthropic has indexed a domain. Low coverage = discovery gap.

### Amazonbot: The Diplomat

- Perfect **1:1 hit-to-unique-page ratio** — every request is a new page
- **432 IPs** distributed across AWS regions
- Polite **4-second crawl delay** — respects robots.txt crawl-delay
- Steady ~850 hits/hour, no bursting
- No strong domain preference — wants everything equally
- **Signal:** Amazonbot's even-handed coverage provides a baseline. Categories it
  skips are genuinely low-signal.

### Google (various): The Strategist

- Selective crawling — heavy on **embeddings** and **ml-frameworks**, light on **rag**
- GoogleOther (AI training, feeds Gemini) distinct from Googlebot (search indexing)
- Stealth renderer (Nexus 5X UA from 66.249.70.x) adds a second evaluation pass
- **Signal:** Google's domain preferences reveal what it thinks will matter for
  Gemini's competitive positioning. Embeddings punching above its weight in Google's
  crawl suggests Google sees embedding infrastructure as strategically important.

### PerplexityBot: The Specialist

- **NLP domain nearly equals ml-frameworks** — unique among all bots
- Hit methodology and about pages (unusual — most bots ignore non-project pages)
- Reflects Perplexity's search-product orientation: NLP and understanding queries
  matters more to a search engine than to a model trainer
- **Signal:** PerplexityBot's domain weights are the most differentiated from the
  pack. Where Perplexity diverges from consensus reveals search-specific demand.

### GPTBot: The Ghost

- **~19 hits/day** — nearly absent
- Meanwhile OAI-SearchBot surges (user-action retrieval)
- OpenAI has strategically shifted from training-crawl to real-time retrieval
- **Signal:** GPTBot absence confirms the shift to retrieval-augmented generation.
  Other labs may follow this pattern. Track whether ClaudeBot or Meta volumes
  decrease over time as they too shift to real-time retrieval.

### Domain Preference Summary

| Domain | Meta | ClaudeBot | Amazonbot | Google | Perplexity |
|---|---|---|---|---|---|
| ml-frameworks | high | high | even | **heavy** | high |
| perception/CV | **heavy** | even | even | moderate | low |
| embeddings | low | even | even | **heavy** | moderate |
| NLP | moderate | even | even | moderate | **heavy** |
| agents | high | high | even | moderate | moderate |
| rag | moderate | even | even | **light** | moderate |
| prompt-engineering | low | even | even | **light** | **light** |
| diffusion | low | even | even | moderate | **light** |

**Bold** = notable deviation from the bot's baseline. "Even" = Amazonbot and ClaudeBot
show no strong preference, crawling proportional to site content.

### Implications for the ML pipeline

These crawl fingerprints feed directly into the `category_features_daily` feature store:
- `meta_revisit_ratio` — freshness signal
- `bot_consensus_count` — quality proxy (5+ families = independently validated)
- Per-bot coverage ratios — domain preference divergence
- Absence detection — categories no bot touches despite high quality scores
