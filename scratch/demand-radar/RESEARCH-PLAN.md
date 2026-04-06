# Demand Radar: Research Plan

**Date:** 2026-04-06
**Context:** PR 206 established the initial framework from 22 hours of data. We now have ~48 hours and the conversation on Easter Saturday surfaced several insights that the current documents don't capture. This plan identifies the gaps and proposes research threads to fill them.

---

## What the current documents get right

- Bot classification taxonomy (training vs user-action vs search)
- Session detection heuristic for OAI-SearchBot (IP + 5-min gap)
- Practitioner persona clustering from path data
- Content coverage gap detection
- Archival storage design
- The 3-PR implementation roadmap (classification → sessions → demand gaps)

## What's missing or underdeveloped

### 1. Indexing bots as intelligence, not noise

**Gap:** The current docs treat indexing bots as a single "77.4% is Meta" statistic. The Easter Saturday analysis revealed that each bot has a completely different crawl strategy that reveals what its parent company values.

**Research needed:**
- **Crawl strategy fingerprinting per bot.** For each of Meta, ClaudeBot, Amazonbot, Google, PerplexityBot, GPTBot: document the hit-to-unique-page ratio (1:1 = systematic sweep, 2:1 = revisiting), domain preferences, crawl timing patterns, IP fleet size.
- **Meta's revisit signal.** Meta hits the same pages multiple times (20,984 perception hits but only 10,644 unique pages). Which pages does it revisit? Is revisit frequency correlated with page quality, recency, or topic? A page that Meta re-crawls every 6 hours is one it considers high-value and time-sensitive. That's a quality signal we could feed into allocation.
- **Domain preference divergence.** Each bot prioritises different domains (Meta → perception/computer-vision, Google → embeddings/ml-frameworks, Perplexity → NLP nearly equals ml-frameworks). Map each bot's domain weight distribution and compare. Where they diverge reveals product roadmap differences. Where they converge reveals consensus importance.
- **Bot consensus as quality proxy.** Pages hit by 5+ distinct bot families (we found 17 such pages) are independently validated by multiple AI companies. Test whether bot-consensus-count correlates with existing quality scores, stars, or user-action bot demand. If it does, it's a cheap signal to add to allocation.
- **GPTBot absence signal.** GPTBot has nearly stopped crawling (19 hits/day) while OAI-SearchBot surges. This suggests OpenAI has strategically shifted from training-crawl to real-time retrieval. Document this and track whether other labs follow.

### 2. The three-layer demand model

**Gap:** The docs identify user-action bots and indexing bots as separate categories, but don't articulate a unified model of how all three traffic layers (indexing, user-action, human) relate to each other and what each reveals.

**Research needed:**
- **Formalise the three-layer model.** Layer 1 (indexing) = what AI companies think will be valuable in future model weights. Layer 2 (user-action) = what real humans are asking AI right now. Layer 3 (human/Umami) = what real humans find through Google. Each layer has different latency (months for training, real-time for user-action, days-weeks for SEO), different value (weights = permanent, retrieval = ephemeral, SEO = transient), and different action implications.
- **Cross-layer correlation.** Does heavy indexing in a domain predict user-action demand weeks later? Does user-action demand in a category predict Google impression growth? If these correlations exist, the indexing data becomes a leading indicator for the other two layers.
- **Layer-specific allocation weights.** The current allocation engine weights GSC at 75% of Established Heat and AI browsing at 10% of Emergence Score. Should indexing bot signals have their own weight? A page that every lab has crawled but has zero user-action hits is being stockpiled for training — that's a different signal from active retrieval demand.

### 3. The ChatGPT Pro deep research pattern

**Gap:** The 251-page burst at 15:00 UTC on Apr 5 was a single ChatGPT Pro deep research session. The current session detection heuristic wouldn't have caught it properly because it fanned out across 8 IPs simultaneously.

**Research needed:**
- **Fan-out burst detection.** Define a heuristic: if N OAI-SearchBot IPs each hit a unique page within a T-second window, and the pages share a domain or subcategory, treat as one research session. Test different N and T values against the Apr 5 burst to calibrate.
- **Research session vs single-page fetch ratio.** What percentage of user-action traffic comes from deep research sessions (10+ pages) vs single-page fetches? This matters because a deep research session is a fundamentally different intent signal — it's someone making a major decision, not answering a quick question.
- **Topic reconstruction from bursts.** The Apr 5 burst was clearly "ML for healthcare risk prediction" + "embedding/RAG infrastructure." Can we automatically infer the research topic from the set of pages accessed? Clustering by subcategory within a session would work. This is the Layer 4 practitioner-domain signal.

### 4. Commercial entity detection at scale

**Gap:** The conversation identified that ~50% of the top 20 user-action-hit pages have a commercial entity behind them. This is the foundation of the sponsorship/claim-your-page business model, but there's no systematic way to identify commercial entities across 220K repos.

**Research needed:**
- **Heuristic for commercial entities.** GitHub org (not personal account) + has a website that isn't GitHub Pages + more than one repo = likely company. Test this against the known commercial entities (Mindee, Jina AI, QuantCo, etc.) to measure precision/recall.
- **Scale estimate.** How many of the 220K repos have an org owner with a company website? This gives the total addressable market for the claim-your-page model.
- **Cross-reference with user-action demand.** Of the repos with commercial entities, how many have received at least one user-action bot hit? This is the "warm lead" list — companies whose open source tools are being discovered through AI but who don't know it.

### 5. Feeding signals back into allocation

**Gap:** The current allocation engine uses GSC (75% of EHS) and AI browsing (10% of ES). The conversation revealed several new signals that could improve prioritisation.

**Research needed:**
- **Bot consensus score.** Number of distinct bot families that have crawled a page or category. Test as an ES component. Hypothesis: high bot consensus = the AI industry considers this content important regardless of current user demand.
- **Meta revisit frequency.** Pages that Meta re-crawls most often. Test as an EHS component. Hypothesis: Meta's internal quality/freshness scoring is a leading indicator of content importance.
- **User-action session depth.** Categories that appear in deep research sessions (10+ pages) vs single-page fetches. Test as an EHS component. Hypothesis: deep research sessions represent higher-value demand than individual fetches.
- **Cross-layer leading indicators.** If indexing volume in a category at time T predicts user-action demand at T+2 weeks, the indexing signal should have forward-looking weight in allocation.
- **Comparative A/B: current allocation vs signal-enriched allocation.** Take the current content budget output and compare it to what a signal-enriched version would produce. Where do they diverge? Which version better predicts where the next user-action hits will land?

### 6. Table growth and archival (deprioritised)

**Update:** Render storage auto-expands and cost per GB is low. This is no longer
urgent. Keep the analysis in [table-growth.md](table-growth.md) for reference but
table growth is not an action item.

### 7. The "absence" signal

**Gap:** Not discussed in PR 206 at all. The conversation identified that what bots DON'T crawl is as informative as what they do.

**Research needed:**
- **Uncrawled pages with high quality scores.** Pages that have strong GitHub metrics but zero bot visits. Why are the bots ignoring them? Possibly: poor internal linking, not in sitemaps, thin content.
- **Domain blind spots per bot.** Perplexity ignores diffusion/prompt-engineering. Meta barely touches embeddings. Google ignores prompt-engineering. These blind spots are either (a) the bot doesn't think the content is relevant to its use case, or (b) the pages aren't discoverable. Either way, it's actionable.
- **New content detection lag.** When a new page is added to the site, how long until each bot discovers it? This measures how well the sitemaps and internal linking are working.

---

## Proposed execution order

1. **Three-layer demand model formalisation** — this is the conceptual framework everything else hangs on
2. **Indexing bot crawl strategy fingerprinting** — the largest data source, most unexploited
3. **Fan-out burst detection calibration** — needed for accurate session detection
4. **Bot consensus + revisit signals for allocation** — turns research into allocation engine improvements
5. **Commercial entity detection** — enables the business model
6. **Absence signal analysis** — interesting but lower priority

---

## Output format

Each research thread should produce:
1. A findings section in LAB-NOTES.md (or a new companion doc if large enough)
2. Specific allocation engine recommendations (what signal, what weight, what component)
3. SQL queries that could be turned into materialized views or worker tasks

---

**Note:** This research plan feeds into the [ROADMAP.md](ROADMAP.md), which defines the ML infrastructure and model training pipeline that these research threads support.
