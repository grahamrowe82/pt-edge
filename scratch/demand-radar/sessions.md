# AI Agent Session Detection in Access Logs

**Date:** 2026-04-05
**Data window:** 2026-04-04 14:13 UTC to 2026-04-05 11:48 UTC (~21 hours)
**Method:** Group requests by (client_ip, bot_type) with a 5-minute inactivity gap to define session boundaries.

## Summary

We can detect multi-page "sessions" in the access logs. 17.6% of all AI bot sessions involve 2+ pages, and several show clear comparison-shopping behaviour. However, **OAI-SearchBot uses a small IP pool that is heavily reused**, which means IP-based sessions are reliable within a 5-minute window but unreliable across longer gaps.

## Raw Numbers

| Metric | Value |
|---|---|
| Total AI bot requests (200s only) | ~1,362 |
| Total sessions (all sizes) | 979 |
| Multi-page sessions (2+ pages) | 172 (17.6%) |
| Avg pages per multi-page session | 3.2 |
| Max pages in a single session | 17 |

## Bot Breakdown

| Bot | Multi-page sessions | Total pages in those sessions | Avg pages | Max pages |
|---|---|---|---|---|
| OAI-SearchBot | 133 | 460 | 3.5 | 17 |
| ChatGPT-User | 38 | 88 | 2.3 | 5 |
| Claude-User | 1 | 7 | 7.0 | 7 |
| Perplexity-User | 0 | - | - | - |
| DuckAssistBot | 0 | - | - | - |

OAI-SearchBot dominates multi-page sessions. ChatGPT-User sessions are shorter (max 5 pages). The single Claude-User session fetched 7 pages in 13 seconds (anomaly detection research).

## Pages-per-Session Distribution

| Pages | Sessions |
|---|---|
| 2 | 99 |
| 3 | 34 |
| 4 | 18 |
| 5 | 7 |
| 6 | 3 |
| 7 | 1 |
| 8 | 1 |
| 10 | 2 |
| 12 | 1 |
| 13 | 4 |
| 14 | 1 |
| 17 | 1 |

Heavy tail: 58% of multi-page sessions are exactly 2 pages. But the 10+ page sessions are dramatic -- these represent deep research dives where the bot fetches an entire subcategory's worth of project pages.

## Top 5 Most Interesting Sessions

### 1. Chest X-ray Pneumonia Detection Deep Dive (17 pages, 46 seconds)

OAI-SearchBot from `74.7.242.129` fetched 17 pneumonia/chest-X-ray ML project pages in under a minute. Clear signal: a user asked "what are the best chest X-ray pneumonia detection models?" and the bot systematically surveyed the landscape.

### 2. Parallel Pneumonia Research (13-14 pages across 4 IPs, same minute)

Four different OAI-SearchBot IPs all started fetching chest-X-ray related pages at `01:56:24-01:56:42` -- within 18 seconds of each other. This is likely **a single OAI-SearchBot query fanning out across its IP pool**. Combined, these 4 IPs fetched ~53 unique pneumonia detection project pages plus category and compare pages. This is one massive research session split across IPs.

### 3. Claude-User Anomaly Detection Research (7 pages, 13 seconds)

IP `196.39.129.60` fetched Anomaly-Transformer, CausalDiscoveryToolbox, vectorbt, a marketing-agent-blueprints page, a Raman spectra project, the anomaly-detection-systems category page, and a compare page (deephyper vs orion). Classic comparison-shopping flow: project pages + category page + compare page.

### 4. Devinterview.io Comparison Marathon (4 pages, all compare pages)

OAI-SearchBot fetched 4 compare pages: pandas-vs-cnn, pandas-vs-numpy, pandas-vs-time-series, pandas-vs-linear-regression interview questions. Someone was evaluating our compare pages specifically.

### 5. Semantic Search Survey (10 pages, 8.6 minutes)

OAI-SearchBot from `74.7.242.171` fetched semantic search evaluation tools, BERT-based search, product search, course recommendation, and then pivoted to agent and LLM recommendation pages. Cross-domain session showing a user exploring "semantic search" broadly.

## Comparison-Shopping Behaviour

| Pattern | Count |
|---|---|
| Sessions with 2+ project pages in the same domain | 88 (51% of multi-page sessions) |
| Sessions that include a /compare/ page | 22 |
| Sessions that include a /categories/ page | 36 |
| Sessions with category + project pages (drill-down) | 36 |
| Cross-domain sessions (pages from 2+ domains) | 58 |

**Key finding:** 51% of multi-page sessions are same-domain multi-project -- the bot is comparing several projects within one subcategory. This is the strongest signal of comparison-shopping. 22 sessions explicitly used our /compare/ pages, confirming agents find and use the comparison feature.

## IP Reuse / Pooling Analysis

### OAI-SearchBot: Small, Stable IP Pool

OAI-SearchBot uses exactly **8 IPs**, all in the `74.7.228-243.*` range:

```
74.7.228.139    74.7.229.34
74.7.229.211    74.7.242.129
74.7.229.212    74.7.242.171
74.7.243.6      74.7.243.43
```

Each IP is active for the full 21-hour observation window (19-21 distinct hours each), averaging **76 hits per IP**. These IPs are heavily reused across completely different queries and time periods.

**Implication:** 5-minute session windows work well for OAI-SearchBot because queries complete within seconds/minutes. But any wider window (e.g., 30 minutes) would merge unrelated queries. The parallel-fetch pattern in Session #2 above shows that a single SearchBot query can fan out across multiple IPs simultaneously, meaning our session count for OAI-SearchBot is likely an **overcount** -- some "sessions" on different IPs are actually fragments of the same query.

### ChatGPT-User: Large, Dispersed IP Pool

ChatGPT-User uses **437 distinct IPs** for 735 hits (1.7 hits/IP). IPs are spread across many Azure subnets:

| Subnet | Distinct IPs | Hits |
|---|---|---|
| 23.98.142.* | 16 | 146 |
| 20.215.220.* | 47 | 93 |
| 20.169.78.* | 24 | 35 |
| 20.169.73.* | 17 | 25 |
| 40.67.183.* | 15 | 21 |

The `23.98.142.*` subnet has the highest hits-per-IP ratio (9.1), and these IPs are reused across 19-21 hour spans. However, with only 1.7 hits/IP overall, most ChatGPT-User requests are single-page fetches that cannot be grouped into sessions at all.

**Implication:** IP-based session detection works for ChatGPT-User only within tight windows (< 5 min). The `23.98.142.*` cluster might represent a specific data centre region where sessions are more reliable, but in general ChatGPT rotates IPs frequently enough that most multi-page conversations will appear as isolated single-page requests.

## Conclusions

1. **Sessions are real and detectable.** 172 multi-page sessions in 21 hours, with clear topical coherence within sessions.

2. **OAI-SearchBot is the main session producer.** 133 of 172 sessions (77%). It fetches deeply (up to 17 pages) and quickly (often < 1 minute for 10+ pages). But it uses a tiny IP pool (8 IPs) that are reused constantly, so the 5-minute gap is critical to avoid false merges.

3. **OAI-SearchBot fans out across IPs.** The pneumonia research burst shows 4+ IPs fetching the same topic simultaneously. True session count is likely lower than 172 because some "sessions" on different IPs belong to the same query. To detect this, we would need to cluster by (time_window + topic similarity) rather than just IP.

4. **ChatGPT-User sessions are sparse.** Most ChatGPT interactions produce a single page fetch. When multi-page sessions occur, they are short (2-5 pages). IP rotation makes session detection unreliable for this bot.

5. **Compare pages are used in context.** 22 sessions include /compare/ pages, typically alongside project pages in the same category. This validates the compare feature as agent-useful.

6. **Recommendation:** For product analytics, count OAI-SearchBot sessions by clustering (IP, 5-min gap) but also check for cross-IP bursts on the same topic within 30-second windows. For ChatGPT-User, treat each request as a separate "intent" unless timestamps within the same IP are < 60 seconds apart.
