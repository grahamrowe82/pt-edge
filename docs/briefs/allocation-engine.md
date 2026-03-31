# Allocation Engine: Design Brief

## Strategic context

Our structural advantage is in topics where content supply is thin relative to search demand. The allocation engine exists to find that gap systematically.

Voice-ai proved this: it dominated GSC data in our first week — not because absolute demand was highest, but because the gap between demand and supply was widest. Nobody writes blog posts comparing TTS libraries. Our quality scores fill that gap. The further a topic is from the LLM/agent hype cycle, the bigger our advantage.

The engine uses two distinct signals from GSC:

1. **Position strength (Google's signal):** When Google places a brand new domain at position 3, it's saying "I don't have 3 better options." This is a direct measure of competitive density — a discovery signal that feeds the Emergence Score.

2. **CTR vs benchmark (the user's signal):** Once positioned, does the searcher click? Actual CTR divided by expected CTR for that position measures our presentation quality. Above benchmark = weak competition or strong titles. Below = crowded or poor titles. This is an optimisation signal that feeds the Established Heat Score.

These are different levers. Position tells us *where to invest*. CTR tells us *how to improve what we have*.

## Problem

PT-Edge has 59K+ pages across 17 domains, limited editorial time, and finite GitHub API crawl budget. Currently, all three processes — crawling, enrichment (comparisons/categories), and deep dives — run naively (top-to-bottom by star count). There is no feedback loop from demand signals (GSC, Umami, GitHub trends) back into allocation decisions.

We need a scoring function that answers: **given what we know about demand, competition, and momentum, where should we invest next?**

## Strategic Frame: Barbell Allocation

We explicitly avoid optimising for the middle. The allocation engine produces two queues:

**Established heat (85-90% of effort):** Topics where GSC shows impressions/clicks growing, Umami confirms real engagement, and Google is actively indexing. Low risk. The job is to deepen coverage — more comparisons, richer category pages, refreshed content. Defend and extend positions we already hold.

**Emerging signal (10-15% of effort):** Topics where GitHub velocity is accelerating but GSC has no data yet (because it's too new for Google to have indexed). High risk, convex payoff. If we're right early, we become the authority page that Google indexes first — a position that's very hard to displace. The OpenClaw deep dive is the canonical example.

**Dead zone (0% of effort):** Moderate-traffic topics that aren't growing. Automated pipelines keep these pages fresh, but no editorial time goes here.

## Theoretical Foundations

### Restless Multi-Armed Bandit

Each page/topic is an arm. Pulling an arm = investing editorial effort. Reward = traffic growth. Arms are "restless" — rankings decay and competitors publish even when we don't act. The Whittle index (Nino-Mora, 2025) extends the classic Gittins index to restless settings and scales linearly with the number of arms.

### Thompson Sampling (Explore/Exploit)

Maintains a posterior distribution for each page's "expected traffic uplift per unit of effort." High expected value = exploit. High uncertainty = explore. As data accumulates, the system naturally shifts from exploration to exploitation. Simple to implement as a Bayesian update after observing outcomes.

### Marginal Value Theorem (Patch Leaving)

From information foraging theory (Pirolli & Card, 1999): treat each topic cluster as a "patch." Keep investing until the marginal return drops below the average return across all patches, then move on. Prevents over-investing in already-covered topics. Directly governs deep dive sequencing — once we've written the OpenClaw deep dive, the marginal value of a second OpenClaw piece is lower than a first piece on Claude Code skills.

### Power Law Awareness

Web traffic follows power laws. A small number of pages drive the vast majority of traffic. The scoring function must optimise for expected value, not most likely outcome. A page with 10% chance of 100x uplift is worth more than one with 90% chance of 2x. This is why the speculative side of the barbell matters.

## Signal Sources

### 1. Google Search Console (lagging indicator, high confidence)

Available daily (with ~2 day lag). Tells us what Google is serving and what users click.

| Signal | Meaning |
|--------|---------|
| Impressions growing | Google thinks this content is relevant to real queries |
| Clicks growing | Users validate Google's judgement |
| High impressions, low CTR | Content matches intent but title/description underperform — enrichment opportunity |
| Position improving | We're gaining authority in this area |
| New queries appearing | Adjacent demand we could capture with new pages |

### 2. Umami (real-time, medium confidence)

Available immediately. Tells us what real visitors do on the site.

| Signal | Meaning |
|--------|---------|
| High pageviews | Page is being found (via search or direct) |
| Deep sessions (3+ pages) | Visitor is engaged, internal linking is working |
| Referrer patterns | Where organic traffic originates |
| Comparison page visits | Which head-to-head matchups people care about |
| Bounce on category pages | Category content is thin — enrichment needed |

### 3. PT-Edge Internal Data (leading indicator, lower confidence)

Available daily from GitHub ingest. Leading indicator of what will matter.

| Signal | Meaning |
|--------|---------|
| Star velocity (7d acceleration) | Repo is gaining momentum |
| New repos in category (7d count) | Ecosystem is actively forming |
| Fork rate acceleration | Developers are building on this |
| Contributor growth | Community is diversifying beyond creator |
| Category empty → populated | New ecosystem emerging (highest signal for speculative bets) |

## Statistical Framework: Bayesian Surprise

Hard minimum-impression thresholds are brittle. Instead, we use a prior-based approach:

**Prior:** Each domain's expected share of impressions = its share of total repos. If voice-ai has 5% of repos, the prior says it should get ~5% of impressions.

**Surprise ratio:** `actual_impression_share / expected_impression_share` per domain.

- Voice-ai getting 50% of impressions when the prior says 5% = surprise ratio of 10 = massive signal even at 80 total impressions
- A domain getting 6% when the prior says 5% = surprise ratio of 1.2 = noise

This naturally handles small samples: deviations must be large relative to the prior to matter, which requires either large absolute samples or extreme ratios. No arbitrary thresholds.

**Tiered confidence:**

- **Domain level** (50+ impressions across the domain): compute surprise ratio and directional CTR
- **Category level** (50+ impressions per category): inherit domain-level signal until threshold met
- **Page level** (100+ impressions): don't make page-level CTR decisions until sample is there

## Scoring Function Design

### Two scores per topic/category, not one blended score

**Established Heat Score (EHS):**

```
EHS = 25% * norm(gsc_impression_growth_7d)
    + 20% * norm(gsc_click_growth_7d)
    + 15% * norm(gsc_position_improvement)
    + 15% * norm(ctr_vs_benchmark)       # actual CTR / expected CTR for position
    + 15% * norm(umami_pageviews_7d)
    + 10% * norm(umami_avg_sessions)
```

High EHS = proven demand, validated by users clicking. Allocate from the 85-90% budget. The `ctr_vs_benchmark` component measures how well our presentation converts — above 1.0 means we're outperforming the benchmark for our position.

**Emergence Score (ES):**

```
ES = 25% * norm(github_star_velocity_7d)
   + 20% * norm(github_new_repos_in_category_7d)
   + 10% * norm(github_fork_acceleration_7d)
   + 25% * (1 - gsc_coverage_ratio)       # absence of GSC data is positive
   + 20% * norm(position_strength)         # high position = Google sees thin competition
```

High ES = emerging opportunity nobody else covers yet. Allocate from the 10-15% budget. The `position_strength` component is Google's direct signal that content supply is thin — a new domain ranking at position 3 means there aren't 3 better options.

**Dead zone filter:** If EHS < threshold_low AND ES < threshold_low, skip entirely.

### Marginal value adjustment

For each topic cluster, track cumulative editorial investment (number of deep dives, comparisons, enrichments). Apply diminishing returns:

```
marginal_multiplier = 1 / (1 + log(1 + prior_investments))
adjusted_score = raw_score * marginal_multiplier
```

This ensures the system naturally rotates across topics rather than over-investing in one area.

### Exploration bonus (Thompson Sampling)

For topics with few observations (new categories, recently discovered repos), add an uncertainty bonus:

```
exploration_bonus = c * sqrt(ln(total_rounds) / topic_observations)
final_score = adjusted_score + exploration_bonus
```

The constant `c` controls explore/exploit balance. Start with c=1.0, tune based on outcomes.

## Outputs

### 1. Automated Priority Queue (daily cron)

Consumed by the enrichment pipeline without human intervention:

- **Crawl priority:** Which GitHub repos/categories to refresh first in the daily ingest
- **Comparison generation:** Which new X-vs-Y pages to create, which stale ones to refresh
- **Category enrichment:** Which category pages need richer descriptions, more internal links
- **Freshness signals:** Which pages to touch (even minimally) to trigger Google recrawl

Stored as a materialized view, refreshed daily after GSC and GitHub ingests complete.

### 2. Deep Dive Queue (human-in-the-loop)

A ranked list of topics for editorial deep dives, queryable on demand:

```sql
SELECT topic, ehs, es, combined_score, evidence_summary
FROM mv_deep_dive_queue
ORDER BY combined_score DESC
LIMIT 10;
```

Each entry includes:
- The topic/category name
- EHS and ES scores with breakdown
- Evidence summary: "GSC impressions up 340% this week, 12 new repos, no existing deep dive"
- Suggested angle: "Ecosystem formation analysis" vs "Comparative landscape" vs "Getting started guide"

## Implementation Phases

### Phase 1: Foundation (materialized views + basic scoring)

- Create `mv_allocation_scores` with EHS and ES per category
- Wire GSC data into the scoring (once data starts flowing ~April 1)
- Wire Umami data via direct query to umami-db
- Basic weights (equal weighting to start, tune later)
- Expose deep dive queue as a simple SQL view

### Phase 2: Feedback loop (close the loop)

- Track editorial investments per topic (deep dives written, comparisons generated)
- Apply marginal value adjustment
- Add exploration bonus for under-observed topics
- Automated comparison generation reads from the priority queue
- Crawl priority weighted by allocation scores

### Phase 3: Adaptive weights (learn from outcomes)

- After enough data accumulates (~2-3 months), measure actual traffic uplift from editorial investments
- Use Thompson Sampling to update weight posteriors
- The system learns which signal combinations predict the best ROI
- Weights shift automatically as the competitive landscape changes

## Data Dependencies

| Source | Table | Refresh | Available |
|--------|-------|---------|-----------|
| GSC | `gsc_search_data` | Daily 6AM UTC | ~April 1 |
| Umami | `website_event`, `session` (umami-db) | Real-time | Now |
| GitHub stars | `daily_snapshots` | Daily 6AM UTC | Now |
| Repo metadata | `ai_repos` | Daily 6AM UTC | Now |
| Categories | `mv_*_quality` views | Daily 6AM UTC | Now |
| Deep dives | `deep_dives` | On publish | Now |

## Key Files

- `app/models/gsc.py` — GSC data model
- `app/ingest/gsc.py` — GSC ingestion
- `app/ingest/runner.py` — Daily ingest orchestrator
- `scripts/generate_site.py` — Site generation (consumes quality views)
- `scripts/generate_deep_dives.py` — Deep dive page generation

## References

- Auer et al. (2002) — UCB1 algorithm, logarithmic regret bounds
- Russo et al. — Stanford tutorial on Thompson Sampling
- Nino-Mora (2025) — Restless bandits and Whittle index policies
- Pirolli & Card (1999) — Information foraging theory
- Charnov (1976) — Marginal Value Theorem
- Taleb — Barbell strategy / Antifragile
- Omniscient Digital — Barbell content strategy in practice
