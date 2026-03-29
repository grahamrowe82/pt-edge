# Site Audit — March 29, 2026

Issues discovered by crawling the live site at mcp.phasetransitions.ai. Ordered by severity.

## Critical (trust-destroying) — ALL FIXED

- [x] **Broken footer link.** Fixed — points to Substack now.
- [x] **Categories page out of sync.** Fixed — 2,400 embedding-discovered categories live.
- [x] **"Uncategorized" category link 404.** Fixed — categories page uses discovered categories.
- [x] **Top results miscategorised.** Fixed — 1,717 repos reassigned via centroid similarity. Daily ingest processes 10K/day to clear remaining backlog.
- [x] **NOASSERTION license.** Fixed — normalised to null (shows dash).
- [x] **Trending pages empty.** Fixed — uses earliest available snapshot dynamically.

## Important — MOSTLY FIXED

- [x] **About page.** Created at /about/ with author, data sources, methodology, contact.
- [x] **Methodology page.** Created at /methodology/ with full scoring explanation, tier table, limitations.
- [ ] **Cross-vertical links.** Not yet done — projects in multiple verticals should cross-link.
- [x] **Risk flags position.** Moved above score breakdown.
- [x] **Higher-rated alternatives.** Low-scoring repos show "Higher-rated alternatives" heading.
- [ ] **Thin content noindexing.** Not yet done — waiting for AI summary backfill to progress.
- [x] **Substack cross-linking.** Footer links to Substack, about page links to Substack.

## Infrastructure — MOSTLY FIXED

- [x] **Favicon.** Inline SVG, blue PT mark.
- [ ] **Canonical URLs for multi-vertical projects.**
- [x] **Robots.txt.** Allows all bots, includes sitemap.
- [ ] **Open Graph tags verification.**
- [ ] **404 page that suggests alternatives.**

## Content enrichment (medium-term)

- [ ] **Category-level health metrics.** Average score, distribution, community vs maturity gap.
- [ ] **Score dimension clickability.** Expandable to show why.
- [ ] **Bus factor alerts.** High adoption + single contributor.
- [ ] **Quality ceiling by category.** Best option only scores 40? Nobody's built a good version yet.
- [ ] **Feedback button on every page.**

## Distribution

- [ ] **Newsletter signup / Substack link on every page.**
- [ ] **RSS feeds** per category or vertical.
- [ ] **Changelog / "what's new" page** generated from data.
- [ ] **Google Programmable Search Engine.**
