# Forest Infrastructure Roadmap

**Created:** 2026-04-05
**Branch:** `forest-research`
**Context:** [LAB-NOTES.md](LAB-NOTES.md) contains the raw research findings that inform this plan.

---

## Background

22 hours of access logs revealed that 99.5% of traffic is bots, AI agents are
actively comparison-shopping across project pages, and practitioner personas are
inferable from access patterns. The current tracking infrastructure supports
Layers 1 and 3 of the Combinatorial Forest but cannot support Layers 2, 4, or 5.

This roadmap turns the research findings into three sequential PRs.

---

## PR 1: Classification fixes + archival storage

**Goal:** Fix misclassified traffic and build a denser archival format so raw logs
can be retained indefinitely without eating the database.

**Why urgent:** 11,640 requests/day are misclassified (GoogleOther + stealth
renderer). The raw log table grows at ~58 MB/day and will cause storage pressure
within weeks if left in its current format.

### Classification fixes (migration update to mv_access_bot_demand)

Add to the CASE statement in the materialized view:

| Bot | UA pattern | Category |
|---|---|---|
| GoogleOther | `%GoogleOther%` | Google (AI training / non-search) |
| Claude-User | `%Claude-User%` | AI user-action (Tier 1 demand signal) |
| DuckAssistBot | `%DuckAssistBot%` | AI user-action (Tier 1 demand signal) |
| MJ12bot | `%MJ12bot%` | SEO crawler |
| PetalBot | `%PetalBot%` | Search engine |
| AdsBot-Google | `%AdsBot-Google%` | Google (ads) |
| Qwantbot | `%Qwantbot%` | Search engine |

Also consider: Google stealth renderer (Nexus 5X from 66.249.x.x with no bot
label) — requires IP-range matching, harder to do in a pure UA CASE statement.
May need a separate classification pass or an IP-lookup table for Google's ranges.

### Archival storage design

The raw `http_access_log` table is the hot buffer (last 1-3 days). After session
detection runs, processed data moves into a denser archival table that preserves
all dimensions that matter but drops the repetitive UA strings.

**Principle: never delete the underlying signal.** Every IP, path, timestamp, and
duration is potentially useful for future analysis. Storage is cheap; losing signal
is expensive.

Proposed archival table: `access_log_archive`

| Column | Type | Notes |
|---|---|---|
| id | serial | |
| bot_family | varchar(30) | Classified at write time, not re-derived |
| client_ip | inet | Native Postgres IP type, more compact |
| path | varchar(200) | |
| status_code | smallint | |
| duration_ms | smallint | |
| created_at | timestamptz | |

Drops: raw user_agent (300 bytes → replaced by 30-byte bot_family), method
(always GET). Keeps: everything needed for session detection, trend analysis,
and IP-level analysis.

**Estimated compression:** ~150 bytes/row vs 344 = ~2.3x smaller. At ~180K
rows/day = ~26 MB/day archived vs 58 MB/day raw. 1 year = ~9.5 GB, well within
a Render plan upgrade.

A daily cron job would: (1) refresh the materialized view, (2) run session
detection on the hot buffer, (3) INSERT INTO archive SELECT ... with bot_family
classification, (4) DELETE from hot buffer rows older than the archive cutoff,
(5) VACUUM the hot buffer.

---

## PR 2: Session detection (Layer 2 enabler)

**Goal:** Automatically cluster AI user-action bot requests into sessions,
enabling comparison page generation driven by real demand.

**Depends on:** PR 1 (classification fixes — need Claude-User and DuckAssistBot
in the Tier 1 bot family list).

### Session detection logic

Based on the research findings:

**OAI-SearchBot:** Cluster by (client_ip, 5-minute inactivity gap). Works well
because it uses only 8 stable IPs. Additionally detect cross-IP fan-out bursts:
if 2+ OAI-SearchBot IPs fetch pages in the same subcategory within a 30-second
window, merge into one session.

**ChatGPT-User:** Treat each request as an independent intent signal unless
timestamps from the same IP are < 60 seconds apart. IP rotation (437 IPs for
735 hits) makes session detection unreliable for this bot.

**Other Tier 1 bots:** Use the OAI-SearchBot heuristic (IP + 5-min gap) as
default; refine as traffic grows.

### New table: `bot_sessions`

| Column | Type | Notes |
|---|---|---|
| id | serial | |
| bot_family | varchar(30) | |
| session_started_at | timestamptz | First request in session |
| session_ended_at | timestamptz | Last request in session |
| page_count | smallint | |
| paths | text[] | Ordered list of paths fetched |
| domains | text[] | Distinct domains touched |
| subcategories | text[] | Distinct subcategories touched |
| client_ips | inet[] | IPs involved (for cross-IP sessions) |
| is_comparison | boolean | 2+ project pages in same subcategory |
| is_drilldown | boolean | Category page + project pages |

### Daily batch job

Runs after the archive step in PR 1. Reads from the hot buffer (last 24h of
raw logs), applies session clustering, writes to `bot_sessions`. The session
table is append-only and never purged — it's the comparison demand signal.

### Downstream use

The `is_comparison` flag feeds Layer 2: when a session shows 2+ projects in the
same subcategory, queue a comparison page for that pair if one doesn't exist.
The `subcategories` array feeds the allocation engine as a richer signal than
raw hit counts.

---

## PR 3: Demand-gap detection (Layer 5 enabler)

**Goal:** Automatically identify categories where AI agents are sending humans
but content is thin, and queue enrichment work.

**Depends on:** PR 1 (accurate classification) and PR 2 (session data for
richer demand signal).

### Demand-gap query

Join the materialized view (or session table) against content coverage:

```sql
SELECT
    ar.domain,
    ar.subcategory,
    COUNT(DISTINCT bad.path) AS pages_with_demand,
    SUM(bad.hits) AS total_hits,
    COUNT(*) FILTER (WHERE ar.ai_summary IS NOT NULL)::numeric
        / COUNT(*) AS coverage_ratio,
    COUNT(*) AS total_repos
FROM ai_repos ar
LEFT JOIN mv_access_bot_demand bad
    ON bad.path LIKE '%/servers/' || ar.full_name || '/%'
    AND bad.bot_family IN ('ChatGPT-User', 'OAI-SearchBot', ...)
    AND bad.access_date >= CURRENT_DATE - 7
WHERE ar.subcategory IS NOT NULL
GROUP BY ar.domain, ar.subcategory
HAVING SUM(bad.hits) > 0
ORDER BY coverage_ratio ASC, total_hits DESC
```

### New view or table: `v_demand_gaps`

| Column | Type |
|---|---|
| domain | varchar |
| subcategory | varchar |
| ai_demand_hits_7d | int |
| ai_demand_sessions_7d | int |
| total_repos | int |
| enriched_repos | int |
| coverage_ratio | numeric |
| gap_score | numeric |

`gap_score` = demand signal * (1 - coverage_ratio). High demand + low coverage
= high gap score = generate content here first.

### Integration with enrichment pipeline

The demand-gap view feeds into the existing allocation engine / deep dive queue.
Categories with high gap scores get prioritised for AI summary generation in the
next pipeline run. This closes the Layer 5 loop: demand → detection → generation
→ better content → more demand.

---

## Deferred: Practitioner-domain mapping (Layer 4)

Not included in the initial 3 PRs. This is a lookup table mapping subcategories
to practitioner problem domains (e.g., "anomaly-detection-systems" → "operations
/ reliability engineering", "chest-xray-pathology-detection" → "clinical radiology").

Can be built incrementally once sessions are flowing, because the session data
will reveal which subcategories cluster together in real practitioner workflows.
The mapping emerges from the data rather than being imposed top-down.

---

## Sequencing

```
PR 1 (classification + archival)
  └── PR 2 (session detection)
        └── PR 3 (demand-gap detection)
                  └── [future] Layer 4 practitioner mapping
```

Each PR is independently shippable and valuable. PR 1 is the foundation — without
accurate classification and sustainable storage, everything downstream is built on
bad data.
