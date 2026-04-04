# Co-View Recommendations: "People who viewed X also viewed Y"

## Opportunity

Umami session data gives us something no one else has: real browsing paths between AI projects. When someone views projects A, B, and C in a single session, those co-views encode genuine evaluation relationships — the user is comparing tools for the same job. Aggregated across thousands of sessions, this produces "people who viewed X also viewed Y" recommendations that are more relevant than subcategory-based suggestions.

## Current State

- Umami tracks sessions with country, browser, OS, device, and timestamped pageview events
- Session IDs fragment on the static site (each page navigation can create a new Umami session)
- We've built synthetic session stitching: group consecutive pageviews from the same fingerprint (country + browser + OS + device) where the gap is under 5 minutes
- With ~300 visitors and ~50 multi-page sessions in the first 5 days, the data is too sparse for recommendations yet
- Estimated threshold for useful recommendations: ~10K multi-page sessions (a few weeks at current growth)

## Data Pipeline

### Phase 1: Extract co-view pairs from Umami

Query the Umami database periodically (daily cron) to extract co-view pairs:

```sql
-- Synthetic sessions: group events by fingerprint + 5min gap
-- For each synthetic session with 2+ project pages:
--   Extract all (project_A, project_B) pairs where both were viewed
--   Store with session date and domain
```

### Phase 2: Store in PT-Edge database

New table:

```sql
CREATE TABLE coview_pairs (
    id SERIAL PRIMARY KEY,
    full_name_a VARCHAR(200) NOT NULL,
    full_name_b VARCHAR(200) NOT NULL,
    domain VARCHAR(50),
    coview_count INT DEFAULT 1,
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (full_name_a, full_name_b)
);
CREATE INDEX idx_coview_a ON coview_pairs (full_name_a);
CREATE INDEX idx_coview_b ON coview_pairs (full_name_b);
```

The pipeline upserts pairs, incrementing `coview_count` each time a pair is seen in a new session.

### Phase 3: Surface on detail pages

When `coview_count` exceeds a threshold (e.g. 3+ independent sessions), show the co-viewed projects on the detail page:

```
People also viewed
├── project-b (viewed together 12 times)
├── project-c (viewed together 8 times)
└── project-d (viewed together 5 times)
```

This replaces or supplements the current "Related servers" section which is purely subcategory-based.

## Privacy

- No personal data stored — only aggregate pair counts
- The fingerprint (country + browser + OS + device) is never stored in PT-Edge, only used transiently during Umami query
- Minimum threshold before surfacing (3+ sessions) prevents exposing individual browsing patterns

## Data Quality Considerations

- Filter out single-page sessions (no co-view signal)
- Filter out sessions that hit 20+ pages (likely bots or crawlers, not genuine evaluation)
- Only count co-views between project detail pages (`/servers/owner/repo/`), not category or index pages
- Weight recent co-views higher than old ones (decay factor)
- Domain-aware: only recommend projects within the same domain

## When to Build

- Start data collection when daily multi-page sessions exceed ~100 (probably within 1-2 weeks at current growth)
- Surface recommendations when top pairs have 5+ co-views
- The cross-linking features shipping now (category badge, explore section) serve as the interim solution
