# Demand Radar: Lab Notes

**Date:** 2026-04-05 (updated 2026-04-06)
**Branch:** `demand-radar`
**Data window:** 2026-04-04 14:12 UTC to 2026-04-06 11:54 UTC (~48 hours)
**Total requests:** ~557,000/day (peak 1,500 RPM)

---

## Purpose

The Combinatorial Forest vision says "the light is the access logs." We turned on
logging 48 hours ago and now have our first substantial dataset.

We call this the **Demand Radar** — the infrastructure and analysis layer that
detects what the AI ecosystem values by reading the signals that bots leave across
220K pages. Every hit — indexing, user-action, or human — is latent intelligence.
The Demand Radar extracts that signal and feeds it into content prioritisation,
eventually via trained ML models rather than hand-tuned weights.
Detailed findings are in the companion reports:
- [sessions.md](sessions.md) — AI agent session detection
- [training-crawlers.md](training-crawlers.md) — Meta, Amazon, and other crawler analysis
- [practitioner-intent.md](practitioner-intent.md) — what humans are asking AI about
- [bot-fingerprinting.md](bot-fingerprinting.md) — traffic classification and stealth bots
- [table-growth.md](table-growth.md) — database sustainability

---

## Finding 1: Three layers of traffic model

Traffic decomposes into three distinct layers, each with different latency, value,
and action implications:

| Layer | Volume | What it reveals |
|---|---|---|
| **Indexing bots** | ~550K/day (93%) | What AI companies think will be valuable in future model weights |
| **User-action bots** | ~1,400/day (0.8%) | What real humans are asking AI right now |
| **Humans** | ~200/day (via Umami) | What humans find through Google |

Each layer has different temporal characteristics:
- **Indexing:** months of latency (content enters training, appears in model weights next quarter)
- **User-action:** real-time (someone is asking a question right now)
- **Human/SEO:** days-to-weeks (Google re-ranks, impressions shift)

**Cross-layer hypothesis:** heavy indexing in a domain at time T may predict
user-action demand at T+2 weeks. If this correlation holds, the indexing data
becomes a leading indicator for the other two layers. This is testable once we
have enough temporal data.

---

## Finding 2: User-action bots reveal practitioner intent

~1,400 AI user-action bot fetches across 1,297 distinct pages reveal the demand
landscape. Key observations:

**Domain distribution is concentrated:**
- ml-frameworks: 72% of user-action hits
- agents: 7.7%
- Long tail across everything else

**The long tail is the story.** 1,297 distinct pages with almost 1 hit per page.
There is no "trend" — that IS the trend. Millions of engineers are solving unique
problems and asking AI for help. The demand surface is enormous and flat.

**Deep research sessions are real:**
- 251-page ChatGPT Pro deep research burst on Apr 5, 15:08-15:24 UTC
- Topic: healthcare ML / risk prediction
- Fanned out across 8 OAI-SearchBot IPs simultaneously
- This single session touched more pages than most bots hit in a day

**Comparison pages are pulling weight:** 95 hits across 78 comparison pages.
Users (via AI) are actively comparison-shopping.

**Multi-agent convergence as quality signal:** Pages fetched by 2+ different AI
agents represent independently validated demand. vectorbt was fetched by both
ChatGPT and Claude (14 hits). Cross-platform demand is the strongest signal that
content is genuinely needed.

---

## Finding 3: Indexing bots are intelligence, not noise

Each bot has a distinct crawl strategy that reveals what its parent company values.
This is the biggest underexploited signal in the access logs.

**Per-bot crawl fingerprints:**

| Bot | Hits/day | Unique pages | Ratio | IPs | Strategy |
|---|---|---|---|---|---|
| Meta-ExternalAgent | ~250K | ~115K | ~2:1 | 69 (single /24) | Revisits pages; prioritises perception/CV |
| ClaudeBot | ~181K | ~170K | ~1:1 | 1 aggressive IP | Completionist; trying to inhale entire site. 628 req/min peaks |
| Amazonbot | ~37K | ~37K | 1:1 | 432 (distributed AWS) | Perfect breadth-first; polite 4s delay; wants everything equally |
| Google (various) | ~40K | selective | varies | varies | Selective; heavy on embeddings + ml-frameworks, light on rag |
| PerplexityBot | ~15K | varies | varies | varies | NLP nearly = ml-frameworks (unique among bots); hit methodology/about pages |
| GPTBot | ~19 | ~19 | 1:1 | minimal | Nearly absent — shifted to real-time retrieval via OAI-SearchBot |

**Signals extractable from crawl behaviour:**

1. **Bot consensus (5+ families hit same page) = quality proxy.** Pages independently
   validated by multiple AI companies. We found 17 such pages in 48h. If this
   correlates with quality scores or user-action demand, it's a cheap allocation signal.

2. **Meta revisit frequency = freshness/importance signal.** Meta hits the same pages
   multiple times (20,984 perception hits, 10,644 unique pages = re-crawling favourites).
   A page Meta re-crawls every 6 hours is one it considers high-value and time-sensitive.

3. **Domain preference divergence = product roadmap intelligence.** Meta prioritises
   perception/CV (Llama multimodal focus). Google focuses on embeddings + ml-frameworks
   (Gemini infrastructure). Perplexity uniquely weights NLP nearly equal to ml-frameworks
   (search product needs). Where they diverge reveals product strategy. Where they
   converge reveals consensus importance.

4. **Absence signal.** What bots DON'T crawl is informative. GPTBot's near-total
   absence (19 hits/day) while OAI-SearchBot surges means OpenAI has strategically
   shifted from training-crawl to real-time retrieval. Perplexity ignores
   diffusion/prompt-engineering. Meta barely touches embeddings.

---

## Finding 4: Sessions ARE detectable — but fan-out complicates detection

Using a (client_ip, bot_type, 5-minute-gap) heuristic, we found **172 multi-page
sessions** in the first 21 hours. This is the demand signal the pipeline needs.

**Key numbers:**
- 17.6% of all AI bot sessions involve 2+ pages
- 51% of multi-page sessions show same-domain comparison-shopping
- 22 sessions explicitly used `/compare/` pages
- Max session depth: 17 pages (chest X-ray pneumonia detection survey)

**The complication:** The 251-page ChatGPT Pro deep research burst fanned out across
8 OAI-SearchBot IPs simultaneously. The single-IP heuristic would split this into 8
separate sessions. Cross-IP fan-out detection is needed: if N OAI-SearchBot IPs each
hit unique pages in the same subcategory within a 30-second window, merge into one
session.

ChatGPT-User remains unreliable for session detection — 437 IPs for 735 hits
(1.7 hits/IP). Most ChatGPT interactions are single-page fetches.

---

## Finding 5: ~50% of top pages have commercial entities

8 of the top 20 user-action-hit pages have a commercial company behind the repo.
This is the foundation of the "claim your page" business model.

**Worked examples:**
- **Mindee/DocTR** — French OCR company, open-source text recognition
- **Jina AI** — embedding/search infrastructure company
- **QuantCo** — ML for insurance/pricing
- **vectorbt Pro** — quantitative trading tools (strongest individual signal: 14 fetches)

**Heuristic for detection at scale:** GitHub org (not personal account) + has a
website that isn't GitHub Pages + more than one repo = likely commercial entity.
Cross-referencing with user-action demand gives a "warm lead" list — companies
whose open-source tools are being discovered through AI but who don't know it.

---

## Finding 6: Massive content coverage gaps where demand exists

Categories with real AI agent demand but low content enrichment:

| Category | Fetches | Repos | Enriched | Coverage |
|---|---|---|---|---|
| wireless-signal-processing | 4 | 90 | 3 | 3.3% |
| self-supervised-learning | 2 | 157 | 3 | 1.9% |
| chest-xray-pathology-detection | 2 | 157 | 3 | 1.9% |
| inventory-management-systems | 2 | 93 | 2 | 2.2% |
| code-repository-intelligence | 3 | 139 | 19 | 13.7% |
| agent-memory-systems | 3 | 153 | 26 | 17.0% |

These are the exact gaps a demand-responsive pipeline should fill. Someone asked
about wireless signal processing and we had 3 enriched pages out of 90.

---

## Finding 7: Bot classification gaps remain

The materialized view misclassifies ~11,640 requests/day:

| Bot | Hits | Problem |
|---|---|---|
| GoogleOther | 5,858 | Falls through to "human" — no CASE rule |
| Google stealth renderer | 5,782 | Nexus 5X UA with no bot label, from 66.249.70.x |
| MJ12bot | 530 | Falls to "other_bot" — should be named |
| PetalBot | 31 | Falls to "other_bot" — should be named |
| DuckAssistBot | 3 | Not classified — should be Tier 1 AI user-action |
| Claude-User | 8 | Not classified — should be Tier 1 AI user-action |

GoogleOther is the big one — it's Google's AI training crawler (feeds Gemini, not
Search). The stealth rendering (Nexus 5X from 66.249.70.x) inflates human metrics
by ~8x.

---

## Finding 8: Traffic growing exponentially

| Metric | First 22h | 48h mark |
|---|---|---|
| Requests/day | ~179K | **557K** |
| Peak RPM | ~220 | **1,500** |
| User-action hits/day | 542 | **1,434** (tripled) |
| p90 latency | 2ms | **20ms** (still fine on single instance) |

This is Easter weekend — the floor, not the ceiling. Weekday traffic will be higher.
The site is absorbing the load without issue; static serving scales trivially.

---

## Assessment: What's needed vs what's not urgent

### What works
The `http_access_log` -> `mv_access_bot_demand` -> `mv_allocation_scores` pipeline
correctly captures per-page, per-bot-family demand and feeds the allocation engine.
The static site handles 1,500 RPM without breaking a sweat.

### What's needed: ML infrastructure
The three-layer model, bot fingerprinting, and demand prediction all require
**temporal data that doesn't exist yet.** Every day without snapshot tables is a day
of lost training data. The priority is:

1. `bot_activity_daily` snapshot table — start immediately, data accumulates passively
2. Feature store for category-level signals (bot consensus, revisit ratios, etc.)
3. Retrospective labels for demand prediction (did this category get user-action hits in the next 7 days?)
4. Training pipeline (LightGBM, weekly, automated as a worker task)

See [ROADMAP.md](ROADMAP.md) for the full infrastructure plan.

### What's NOT urgent: table growth
Storage concern is deprioritised. Render storage auto-expands and cost per GB is low.
The urgency language in earlier versions of these notes was written when we thought
storage was blocking; it's not. See [table-growth.md](table-growth.md) for the
analysis, kept for reference.

### Classification gaps
The CASE statement needs updates for GoogleOther, Claude-User, DuckAssistBot. These
are tactical fixes that can happen in parallel with the ML infrastructure work.

---

*Lab notes compiled from multiple research threads over 48 hours. All raw queries and
detailed findings are in the companion reports in this directory.*
