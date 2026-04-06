# Bot Fingerprinting: Unclassified and Masquerading Bots

**Date:** 2026-04-05 (updated)
**Data window:** 2026-04-04 14:12 UTC to 2026-04-05 11:52 UTC (~22 hours)
**Total requests:** ~164,000
**Classification source:** `mv_access_bot_demand` (migration 075)

---

## Executive Summary

99.5% of all traffic is bots. Only ~793 requests (0.48%) come from genuine browser UAs. **GoogleOther is the single biggest misclassification problem** -- 5,872 hits (3.6% of all traffic) currently falling through to `human` in the materialized view because its UA contains no `bot`/`crawler`/`spider` keyword.

Six bot families are entirely missing from `mv_access_bot_demand`: GoogleOther, MJ12bot, PetalBot, AdsBot-Google, Qwantbot, and Claude-User. Together they account for 6,437 misclassified requests.

---

## 1. Browser-Like UAs with Suspiciously High Request Counts (>20 hits/IP)

Only 10 IP+UA combinations cross the threshold. **9 of 10 are GoogleOther** from Google's 66.249.70.x range:

| IP | Hits | Verdict |
|---|---|---|
| 66.249.70.103 | 1,818 | GoogleOther bot |
| 66.249.70.110 | 1,765 | GoogleOther bot |
| 66.249.70.104 | 554 | GoogleOther bot |
| 66.249.70.105 | 484 | GoogleOther bot |
| 66.249.70.96 | 480 | GoogleOther bot |
| 66.249.70.106 | 299 | GoogleOther bot |
| 66.249.70.97 | 264 | GoogleOther bot |
| 66.249.70.107 | 64 | GoogleOther bot |
| 66.249.70.108 | 53 | GoogleOther bot |
| **196.39.129.60** | **30** | **Likely human** |

**196.39.129.60 analysis:** Chrome/146 on Mac. Browsing pattern shows 7 separate sessions over 14 hours, each starting with homepage then drilling into a domain (ml-frameworks, nlp, transformers, llm-tools). Timing has long inter-session gaps (hours) with fast intra-session browsing (2-10 seconds). This is consistent with a returning human visitor, not a bot.

Below the >20 threshold, only 3 more browser-like IPs exist with 5+ hits -- all look like normal human traffic.

---

## 2. Go-http-client Traffic

**Negligible.** 23 total requests from 8 IPs, all hitting `/` (homepage only), over ~13 hours. Likely health checks and uptime probes. Not worth classifying.

---

## 3. Request Timing Analysis

### GoogleOther (66.249.70.103, 66.249.70.110)

| Metric | 66.249.70.103 | 66.249.70.110 |
|---|---|---|
| Requests | 2,050 | 1,979 |
| Median gap | 13.2s | 12.6s |
| Avg gap | 35.9s | 39.4s |
| Min gap | 0.000s | 0.000s |

**Pattern:** Metronomic 24/7 crawling at ~280-300 hits/hour with zero diurnal variation. The hourly distribution is flat (261-307 hits/hour across all 22 observed hours). This is classic systematic bot crawling.

### Interval distribution (66.249.70.103):

| Gap range | Count | % |
|---|---|---|
| < 1 second | 101 | 5.5% |
| 1-5 seconds | 217 | 11.8% |
| 5-15 seconds | 594 | 32.4% |
| 15-60 seconds | 806 | 44.0% |
| > 60 seconds | 115 | 6.3% |

Bulk of requests land in the 5-60 second range -- well-throttled but relentless.

### 196.39.129.60 (browser)

Highly variable timing: sub-second bursts (parallel asset loads), 2-10 second page-read gaps, and multi-hour session breaks. **Verdict: human.**

---

## 4. Unclassified Bot User Agents

These bots are hitting the site but **missing from `mv_access_bot_demand`**:

| Bot | Hits | IPs | Currently classified as |
|---|---|---|---|
| **GoogleOther** | **5,872** | 17 | `human` (no bot/crawler/spider in UA) |
| **MJ12bot** | **530** | 2 | `other_bot` (contains "bot") |
| **PetalBot** | **31** | 7 | `other_bot` (contains "bot") |
| **AdsBot-Google** | **3** | 2 | `other_bot` (contains "bot") |
| **Qwantbot** | **1** | 1 | `other_bot` (contains "bot") |
| **Claude-User** | **8** | 2 | `human` (no bot keyword) |

Not observed: CCBot, DataForSEO, Sogou, Baidu.

Also found but already properly classified:
- OAI-SearchBot (608 hits) -- in view
- Bytespider (28 hits) -- in view

Additional unclassified bots found in "other_bot" catch-all:
- **OAI-SearchBot** (608 hits) -- OpenAI's search crawler, already has a rule in the view
- **Bytespider** (28 hits) -- TikTok/ByteDance, already has a rule

---

## 5. How Much "Human" Traffic Is Actually Bots?

### The math

| Metric | Value |
|---|---|
| Total traffic | ~164,000 |
| Traffic classified as `human` by the view | ~6,667 |
| Of that, actually GoogleOther | 5,872 (**88% of "human" is a bot**) |
| Of that, actually Claude-User | 8 |
| Remaining genuinely human | ~793 |

**88% of what the materialized view calls "human" is GoogleOther.**

Browser-like UAs with >20 hits from a single IP (excluding GoogleOther): just 30 hits from 1 IP (196.39.129.60, likely a real human). As a percentage of all traffic: 0.018% -- essentially zero bot-masquerading-as-human beyond GoogleOther.

---

## 6. GoogleOther Deep Dive

### What is it?
Google's secondary crawler for non-Search purposes: Gemini AI training, Google Translate, and other Google products. Uses a mobile Chrome UA with `(compatible; GoogleOther)` appended. Honors `User-agent: GoogleOther` in robots.txt.

### Scale
- 5,872 hits from 17 IPs in 66.249.70.x range
- Two UA variants: mobile Nexus 5X (5,795 hits) and desktop (66 hits)
- 100% 200 status codes -- never blocked

### What it's crawling

Broad, systematic coverage across the entire directory:

| Domain | Hits |
|---|---|
| nlp | 912 |
| transformers | 876 |
| servers | 844 |
| agents | 601 |
| ml-frameworks | 482 |
| embeddings | 431 |
| generative-ai | 375 |
| voice-ai | 353 |
| vector-db | 317 |
| rag | 134 |
| diffusion | 121 |
| mlops | 70 |
| ai-coding | 67 |
| compare | 66 |
| llm-tools | 52 |

Long tail is extremely flat (3 hits per unique path) -- systematic enumeration, not link-following.

### Crawl pattern
- **280-300 hits/hour, 24/7**, zero diurnal variation
- Median inter-request gap: ~13 seconds
- Started 2026-04-04 14:12 UTC, still active

### Significance
GoogleOther is a **demand signal for AI training data**, similar to GPTBot and ClaudeBot. It should be:
1. Added to `mv_access_bot_demand` as an AI training crawler
2. Optionally blocked via robots.txt if content should not be used for Gemini training

---

## 7. Full Corrected Traffic Breakdown

| Category | Bot Family | Hits | % | IPs |
|---|---|---|---|---|
| AI training | Meta-ExternalAgent | 126,907 | 77.4% | 69 |
| AI training | Amazonbot | 18,665 | 11.4% | 432 |
| AI training | PerplexityBot | 7,388 | 4.5% | 8 |
| **AI training** | **GoogleOther** | **5,872** | **3.6%** | **17** |
| SEO | SemrushBot | 1,232 | 0.8% | 39 |
| **Genuine human** | **Browser** | **~793** | **0.5%** | **724** |
| Search | Googlebot | 766 | 0.5% | 10 |
| AI user-action | ChatGPT-User | 736 | 0.4% | 438 |
| AI user-action | OAI-SearchBot | 608 | 0.4% | ~1 |
| **SEO** | **MJ12bot** | **530** | **0.3%** | **2** |
| AI training | GPTBot | 138 | 0.1% | 1 |
| SEO | AhrefsBot | 120 | 0.1% | 118 |
| Search | Bingbot | 119 | 0.1% | 63 |
| AI training | ClaudeBot | 46 | 0.03% | 1 |
| **Search** | **PetalBot** | **31** | **0.02%** | **7** |
| AI training | Bytespider | 28 | 0.02% | ~1 |
| Infra | Go-http-client | 23 | 0.01% | 8 |
| Dev | Claude-User (CLI) | 8 | 0.005% | 2 |
| Search | DuckDuckGo | 5 | 0.003% | 4 |
| Social | FacebookBot (externalhit) | 5 | 0.003% | ~2 |
| **Search** | **AdsBot-Google** | **3** | **0.002%** | **2** |
| **Search** | **Qwantbot** | **1** | **0.001%** | **1** |

**Bold = currently missing from or misclassified in `mv_access_bot_demand`.**

---

## 8. Recommended Fix for mv_access_bot_demand

Add these lines to the CASE statement in migration 075, **before** the `other_bot` catch-all:

```sql
-- Google secondary crawlers
WHEN user_agent ILIKE '%GoogleOther%'     THEN 'GoogleOther'
WHEN user_agent ILIKE '%AdsBot%'          THEN 'AdsBot-Google'
-- SEO crawlers
WHEN user_agent ILIKE '%MJ12bot%'         THEN 'MJ12bot'
-- Search engines
WHEN user_agent ILIKE '%PetalBot%'        THEN 'PetalBot'
WHEN user_agent ILIKE '%Qwant%'           THEN 'Qwantbot'
-- Dev tools
WHEN user_agent ILIKE '%Claude-User%'     THEN 'Claude-User'
```

This fixes **6,437 misclassified requests** (3.9% of all traffic). GoogleOther alone accounts for 91% of the problem.

### Also consider
- **Rate-limiting Perplexity**: 8 req/s sustained is aggressive relative to its value
- **robots.txt for GoogleOther**: block if you don't want Gemini training on your content
- **MJ12bot**: Majestic SEO backlink crawler, low value, consider blocking
