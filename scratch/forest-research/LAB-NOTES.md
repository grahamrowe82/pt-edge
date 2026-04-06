# Forest Research: Lab Notes

**Date:** 2026-04-05 (Easter Saturday + 1 day of logs)
**Branch:** `forest-research`
**Data window:** 2026-04-04 14:12 UTC to 2026-04-05 11:54 UTC (~22 hours)
**Total requests:** 163,918

---

## Purpose

The Combinatorial Forest vision says "the light is the access logs." We turned on
logging 22 hours ago and now have our first dataset. This document records what we
found by hand-exploring the raw logs, assessing whether the current tracking
infrastructure can support the five layers of the forest, and identifying what
needs to change.

Detailed findings are in the companion reports:
- [sessions.md](sessions.md) — AI agent session detection
- [training-crawlers.md](training-crawlers.md) — Meta and Amazon crawl analysis
- [practitioner-intent.md](practitioner-intent.md) — what humans are asking AI about
- [bot-fingerprinting.md](bot-fingerprinting.md) — traffic classification and stealth bots
- [table-growth.md](table-growth.md) — database sustainability

---

## Finding 1: 99.5% of traffic is bots — the site is a machine-readable resource

Only ~650-700 of 163,918 requests are genuine humans. The rest:

| Category | Hits | % |
|---|---|---|
| Meta-ExternalAgent (AI training) | 126,903 | 77.4% |
| Amazonbot (AI/search) | 18,618 | 11.4% |
| PerplexityBot (AI training) | 7,396 | 4.5% |
| GoogleOther (AI training/products) | 5,858 | 3.6% |
| Google stealth rendering (no bot label) | 5,782 | 3.5% |
| SemrushBot (SEO) | 1,230 | 0.8% |
| AI user-action bots (demand signal) | 1,361 | 0.8% |
| Everything else | ~770 | 0.5% |

**Implication for the forest:** The site already functions as an AI-consumed
resource. The question isn't whether AI agents will read it — they already are,
overwhelmingly. The question is whether we can extract signal from the noise.

---

## Finding 2: Sessions ARE detectable — and they reveal comparison-shopping

Using a (client_ip, bot_type, 5-minute-gap) heuristic, we found **172 multi-page
sessions** in 21 hours. This is the Layer 2 signal the forest needs.

**Key numbers:**
- 17.6% of all AI bot sessions involve 2+ pages
- 51% of multi-page sessions show same-domain comparison-shopping
- 22 sessions explicitly used `/compare/` pages
- Max session depth: 17 pages (chest X-ray pneumonia detection survey)

**The standout session:** OAI-SearchBot fanned out across 4 IPs simultaneously,
fetching ~53 chest X-ray ML project pages in under a minute. This is one human
asking "what are the best chest X-ray pneumonia detection models?" and the bot
doing a comprehensive landscape scan.

**The complication:** OAI-SearchBot uses only 8 IPs, all reused across the full
observation window. The 5-minute gap is essential to avoid merging unrelated queries.
ChatGPT-User is the opposite — 437 IPs for 735 hits (1.7 hits/IP), making session
detection unreliable. Most ChatGPT interactions are single-page fetches.

**For Layer 2 (comparison pages):** OAI-SearchBot is the best session signal source.
ChatGPT-User sessions are too sparse for reliable comparison detection. A hybrid
approach would be: (1) IP+5min for OAI-SearchBot, (2) cross-IP topic clustering
within 30-second windows to catch the fan-out pattern, (3) treat each ChatGPT-User
request as an independent intent signal.

---

## Finding 3: We can infer practitioner personas from the pages AI agents fetch

1,361 AI user-action bot fetches across 874 unique pages reveal clear persona clusters:

1. **Quant finance / algorithmic trading** — vectorbt (14 fetches, strongest signal),
   torchquant, scikit-survival, financial trading ML category
2. **ML ops / anomaly detection** — Anomaly-Transformer, MTAD-GAT, concept drift,
   anomaly-detection-systems category
3. **Medical imaging / clinical ML** — chest X-ray pathology (17-page deep session),
   brain tumor detection, pathology whole-slide data
4. **Agent builders** — agent-governance-toolkit, hermes-plugins, agent-memory-systems,
   marketing-agent-blueprints
5. **Search / retrieval practitioners** — clip-as-service, bm25s, semantic-search-models
6. **OCR / document processing** — DocTR, deep-text-recognition-benchmark, mmocr

**For Layer 4 (cross-domain synthesis):** We can't see the human's query, but we CAN
see which subcategories and projects they land on. The path IS the intent proxy.
Clustering fetched paths by subcategory gives us a reasonable practitioner-domain
signal, especially when combined with session data (e.g., "this session touched 3
anomaly detection projects = operations/reliability persona").

**Multi-agent convergence as quality signal:** 30 pages were fetched by 2+ different
AI agents. vectorbt was fetched by both ChatGPT and Claude (14 hits). One Raman
spectra matching page hit the triple (ChatGPT + Claude + OAI-Search). Cross-platform
demand is the strongest signal that content is genuinely needed.

---

## Finding 4: Massive content coverage gaps where demand exists

Categories with real AI agent demand but <5% content enrichment:

| Category | Fetches | Repos | Enriched | Coverage |
|---|---|---|---|---|
| wireless-signal-processing | 4 | 90 | 3 | 3.3% |
| self-supervised-learning | 2 | 157 | 3 | 1.9% |
| chest-xray-pathology-detection | 2 | 157 | 3 | 1.9% |
| inventory-management-systems | 2 | 93 | 2 | 2.2% |
| code-repository-intelligence | 3 | 139 | 19 | 13.7% |
| agent-memory-systems | 3 | 153 | 26 | 17.0% |

**For Layer 5 (demand-responsive generation):** These are the exact gaps the forest
should fill. Someone asked about wireless signal processing and we had 3 enriched
pages out of 90. Someone asked about chest X-ray pathology and we had 3 out of 157.
The demand signal is there — the content response is not yet automated.

---

## Finding 5: Meta is doing a full-site scrape for Llama training

Meta-ExternalAgent crawled 114,701 unique pages in 22 hours — 52% of the entire
directory. Key characteristics:

- **69-node fleet** from a single `57.141.6.x/24` subnet, perfectly load-balanced
- **Breadth-first**, sitemap-following, 90% of paths visited exactly once
- **317ms median inter-request gap** — aggressive but our static serving handles
  it at 1-3ms p95, zero errors
- Bursty: alternates between ~10K/hr peaks and ~2K/hr troughs

**Amazonbot** is similar but politer: 18,625 hits, 432 AWS IPs, 4-second crawl delay,
every page visited exactly once. Steady ~850 hits/hour.

**Implication:** The combinatorial forest thesis is validated — large page counts
attract training crawlers at scale. Meta attempted to ingest half the site in a day.
This means our content is entering Llama's training data, which in turn means
future ChatGPT/Claude/Perplexity answers about AI tools may be influenced by what
PT-Edge publishes. That's the content quality loop from the vision document.

---

## Finding 6: 11,640 requests are misclassified — GoogleOther and stealth rendering

The materialized view misses:

| Bot | Hits | Problem |
|---|---|---|
| GoogleOther | 5,858 | Falls through to "human" — no CASE rule |
| Google stealth renderer | 5,782 | Nexus 5X UA with no bot label, from 66.249.70.x |
| MJ12bot | 530 | Falls to "other_bot" — should be named |
| PetalBot | 31 | Falls to "other_bot" — should be named |
| DuckAssistBot | 3 | Not classified — should be Tier 1 AI user-action |
| Claude-User | 8 | Not classified — should be Tier 1 AI user-action |
| AdsBot-Google-Mobile | 3 | Not classified |
| Qwantbot | 1 | Not classified |

**GoogleOther is the big one.** It's Google's AI training crawler (feeds Gemini, not
Search). 5,858 hits is more than all AI user-action bots combined. It should be
classified separately from Googlebot so we can track AI training vs search indexing.

The stealth rendering (5,782 hits from 66.249.70.x with plain Nexus 5X UA) is
Google's render budget — they fetch pages as a mobile browser to see what real users
see. These are currently counted as human traffic, inflating human metrics by ~8x.

---

## Finding 7: The access log table will eat the database in 17 days

| Metric | Value |
|---|---|
| Current size | 54 MB (after 22 hours) |
| Growth rate | ~58 MB/day |
| Time to 500 MB | ~8 days |
| Time to 1 GB | ~17 days |
| Total DB size | 4,240 MB |

**This is urgent.** The materialized view only achieves 3.6x compression because
path cardinality is extremely high (127K distinct paths in 164K rows). Even the MV
grows at ~15 MB/day.

**Recommended:** Keep raw logs 1 day max (refresh MV first, then purge + VACUUM).
Add monthly rollup for the MV itself after 30 days.

---

## Assessment: Is the tracking infrastructure up to the job?

### What works (Layers 1 & 3)

The `http_access_log` → `mv_access_bot_demand` → `mv_allocation_scores` pipeline
correctly captures per-page, per-bot-family demand and aggregates it into the
allocation engine at 10% ES weight. This supports Layer 1 (which pages are needed)
and Layer 3 (which categories are hot).

### What's structurally missing

**For Layer 2 (comparison detection):** Sessions are detectable but the infrastructure
doesn't support them. The raw table has no session_id, no clustering logic, and no
automated session detection. The materialized view discards the timing and IP data
needed for session reconstruction. Building Layer 2 requires either:
- A session-detection step between raw logs and the MV (e.g., a CTE or intermediate
  table that clusters requests into sessions before aggregation)
- Or keeping raw logs longer (at least 24h) and running session detection as a
  daily batch job that outputs `(session_id, paths[])` tuples

**For Layer 4 (practitioner-domain routing):** We proved that path-based intent
inference works — the fetched paths clearly cluster into practitioner personas. But
there's no automated classification. The allocation engine maps paths to
(domain, subcategory) which is our taxonomy, not the user's problem domain. A
practitioner-domain layer would need to map subcategories to problem domains
(e.g., "anomaly-detection-systems" → "operations/reliability engineering").

**For Layer 5 (demand-responsive generation):** The materialized view is a manual
refresh, not a stream. There's no trigger that says "this category just got its
first AI agent hit, generate content." The pipeline would need either:
- A scheduled job that diffs the MV against content coverage and queues generation
- Or an event-driven approach where the access log middleware itself detects
  "new category demand" in real-time

### Classification gaps

The CASE statement in migration 075 needs updates for GoogleOther, Claude-User,
DuckAssistBot, and the Google stealth renderer pattern. The stealth renderer is
the hardest — it requires IP-range matching, not just UA string matching.

### Operational sustainability

Without a retention policy, the raw log table kills the database in 2-3 weeks.
This is the most urgent fix.

---

## Recommended next steps (in priority order)

1. **Add retention policy** — daily cron: refresh MV, delete raw logs > 1 day,
   VACUUM. This is blocking; without it the DB fills up.

2. **Fix bot classification** — add GoogleOther, Claude-User, DuckAssistBot,
   AdsBot-Google, MJ12bot, PetalBot to the CASE statement. Consider IP-based
   classification for Google stealth rendering.

3. **Build session detection** — daily batch job that clusters AI user-action bot
   requests into sessions using (IP, bot_type, 5-min gap). Output to a
   `bot_sessions` table with (session_id, bot_family, paths[], started_at,
   page_count). This unlocks Layer 2.

4. **Add demand-gap detection** — scheduled job that joins MV demand data with
   content coverage (ai_repos.ai_summary IS NOT NULL) and outputs a priority
   queue of "categories with demand but low enrichment." This unlocks Layer 5.

5. **Build practitioner-domain mapping** — a lookup table mapping subcategories
   to practitioner problem domains. Combined with session data, this gives us
   Layer 4 intent signals.

---

*Lab notes compiled from 5 parallel research threads. All raw queries and
detailed findings are in the companion reports in this directory.*
