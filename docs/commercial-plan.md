# Commercial Plan

## The connection between traffic and revenue

PT-Edge's free directory site drives organic search traffic. The enterprise data API generates revenue. This document describes how one leads to the other, what the steps are, what we're tracking, and where we are now.

## The user journey

A developer goes from anonymous visitor to paying customer in 8 steps. Each step is a small, natural progression — no big jumps.

### 1. Anonymous visit

They find a server detail page, comparison, or deep dive via Google. They get a useful answer. They leave. This is 95%+ of visitors.

**What we capture:** Umami pageview (anonymous, no identity).

**What makes them come back:** The answer was genuinely useful — not a data dump, but a quality-scored recommendation that helped them make a decision.

### 2. Second visit

They return days or weeks later with a different question. Maybe they're now comparing two options in a different domain. PT-Edge is becoming a known resource.

**What we capture:** Umami returning session.

**What makes this happen:** Freshness. The site changes daily. Scores update, new repos appear, trending projects shift. Static sites don't earn return visits.

### 3. Habitual reference

They check PT-Edge whenever evaluating a new tool. They share links with colleagues. At this point they'd value something that comes to them rather than remembering to visit.

**What we capture:** Umami multi-session patterns, direct traffic referrer.

**What's missing:** There's no mechanism to stay connected. No email, no RSS, no push notification. We rely entirely on them remembering to come back.

### 4. Email subscriber

They sign up for a topical digest — "Voice AI weekly" or "MCP ecosystem updates." This is the first time we capture identity. It's free, low commitment, high value.

**What we capture:** Email address, domain interest, open rates, click-throughs.

**What makes this work:** The digest is auto-generated from data we already have — trending repos, quality score changes, new categories, notable risk flag changes. No manual writing needed. Each domain gets its own digest. A developer interested in voice-ai doesn't get MCP content.

**What's missing:** This doesn't exist yet. It's the highest-priority commercial build. See "What to build next" below.

### 5. Free API user

They want to pull data into their own tooling. Maybe they're building an internal evaluation dashboard, checking quality scores in CI, or building an AI agent that recommends tools. They sign up for a free API key.

**What we capture:** API key identity, usage patterns (endpoints, frequency, query types).

**What makes this work:** A clear CTA in the digest and on the site. "Want this data in your pipeline? Get a free API key." The free tier is rate-limited (e.g., 100 requests/day, last 7 days of data) but immediately useful.

**What exists today:** The API and API key system are built (`/api/v1/`, `api_keys` table with tier system). API docs page exists at `/api/docs`. Not promoted anywhere on the site.

### 6. Power free user

They're hitting rate limits or want historical data, bulk queries, or webhook notifications for score changes. The free tier is useful but constraining.

**What we capture:** Rate limit hits, upgrade page views.

**What makes this happen:** Natural friction. The free tier constraints do the selling — we don't need to push.

### 7. Paid subscriber

They pay for higher limits, full historical data (90+ days of daily snapshots), webhooks for score changes on repos they care about, custom alerts. Pricing: $99-299/month for individual/small team.

**What makes this work:** They've already been using the data. The value is proven. The upgrade removes friction they're already experiencing.

### 8. Enterprise contract

Their whole team uses it. They want SLAs, dedicated support, custom integrations, bulk data exports, white-label embedding in their own tools. Pricing: $12K-36K/year.

**What makes this work:** Internal champions who started as individual paid subscribers. The enterprise sale is bottom-up, not top-down — a developer convinced their team, not a sales team convinced a VP.

## Conversion benchmarks

These are conventional SaaS/content funnel ratios. Actual numbers will vary — the point is having targets to measure against.

| Stage | Metric | Target | Realistic timeline |
|-------|--------|--------|-------------------|
| Monthly unique visitors | Umami | 10,000 | 3-6 months from now |
| Return visitors (2+ visits/month) | Umami | 5-10% of uniques = 500-1,000 | 4-7 months |
| Email subscribers | Digest signups | 2-5% of return visitors = 25-50 | 5-8 months |
| Free API keys | API signups | 5-10% of email subscribers = 3-5 | 6-9 months |
| Paid conversions | Revenue | 10-20% of free API users = 1 | 9-12 months |

The first paid conversion is probably 9-12 months away. That's normal for a data product with no existing audience beyond a 300-subscriber Substack.

## KPIs we track now

Even before the full funnel exists, we should watch these weekly:

| KPI | Source | Why it matters |
|-----|--------|---------------|
| Monthly unique visitors | Umami | Top of funnel. Are we growing? |
| Return visitor rate | Umami (sessions per unique) | Are we becoming a reference? |
| Pages per session | Umami | Are people exploring or bouncing? |
| Referrer mix | Umami (organic vs Substack vs direct) | Which channel drives deepest engagement? |
| GSC impressions + clicks | gsc_search_data | Is Google showing us more? Are people clicking? |
| GSC average position by domain | gsc_search_data | Which domains are we winning? |
| API key signups | api_keys table | Early signal of programmatic interest |
| MCP tool usage | tool_usage table | AI agents using us programmatically |

## Where we are now (March 2026)

- **Stage 1-2:** ~5-10 real visitors/day (Umami). 79 pages in GSC, 168 impressions, 1 click. Pre-flywheel.
- **Stage 3:** No mechanism for staying connected. Substack exists (300 subscribers) but is manual, general, and not integrated with the site.
- **Stage 4:** No email capture on the site. No automated digests.
- **Stage 5:** API exists, API key system exists, not promoted.
- **Stage 6-8:** Not relevant yet.

## What to build next (highest-priority commercial)

### Automated topical email digests

This is the 3→4 conversion — the first point where someone gives us their identity. Everything before is anonymous. Everything after is a relationship.

**What it looks like:**
- A signup form on every domain landing page: "Get weekly Voice AI updates"
- 17 domain-specific digests, auto-generated from data: trending repos this week, biggest score changes, new categories, notable risk flags (famous project went stale)
- Sent weekly, not daily (developers don't want daily email)
- Each digest links back to PT-Edge pages (drives traffic, trains the flywheel)
- Footer includes: "Want this data in your pipeline? Get a free API key"

**What it requires:**
- Email infrastructure (SendGrid, Resend, or similar)
- Signup form + subscriber table in PT-Edge DB
- Digest generation script (runs weekly after view refresh)
- Unsubscribe handling (CAN-SPAM compliance)
- Template for the digest email (simple HTML, matches site style)

**Why it's highest priority:**
- It's the step we're completely missing
- It converts anonymous traffic into known contacts
- It's auto-generated from existing data — no manual writing
- It feeds the flywheel (digest links → site traffic → GSC signals)
- It's the natural bridge to API promotion

### After the digest: API promotion

Once we have email subscribers, promoting the API is a line in the digest footer. No separate build needed — just a CTA and a clear free tier landing page. The API and key system already exist.

## Commercial model summary

```
Free directory (SEO) → organic traffic → return visits → email digest
  → free API key → rate limit friction → paid subscription → enterprise
```

Revenue is a trailing indicator of a working content flywheel. We don't sell the API — we let the data sell itself through free, progressively deeper engagement. The directory is the trust-building surface. The digest is the relationship builder. The API is the monetisation layer. Each step is a natural, small progression from the previous one.
