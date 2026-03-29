# Site Audit — March 29, 2026

Issues discovered by crawling the live site at mcp.phasetransitions.ai. Ordered by severity.

## Critical (trust-destroying, fix immediately)

- [ ] **Broken footer link on every page.** "Powered by PT-Edge" links to `phasetransitions.ai`, which returns 503. Dead link on all 165K pages. Google follows footer links — hitting 503 is a negative crawl signal.
- [ ] **Categories page out of sync.** MCP `/categories/` still shows old hand-crafted taxonomy (11 categories). Individual server pages reference the new embedding-discovered categories (168 categories). The listing page and detail pages disagree.
- [ ] **"Uncategorized" category link is 404.** Categories page links to `/categories/uncategorized/` but the URL returns 404.
- [ ] **Top results miscategorised in some verticals.** AI Coding top 3 are CasADi (symbolic optimisation), brian2 (spiking neural networks), devito (finite difference compiler) — scientific computing, not AI coding. LanceDB appears under "vector-db-benchmarking" — it's a database, not a benchmark. When homepage heroes are visibly wrong, trust collapses.
- [ ] **License field shows raw "NOASSERTION".** Visible on n8n (top MCP server, score 88). GitHub API artifact passed through unprocessed.
- [ ] **Trending pages empty across all verticals.** "Trending data is available after one week of quality score tracking." Daily snapshots have been running — likely a query or rendering issue.

## Important (quality and trust signals)

- [ ] **No about page.** Google's E-E-A-T signals reward identifiable expertise. A site with no author looks like a content farm.
- [ ] **No methodology page.** How scores are calculated, data sources, update frequency. Trust signal for humans and Google.
- [ ] **No cross-vertical links.** n8n is top MCP server — likely relevant in Agents too. Free internal linking.
- [ ] **Risk flags buried at bottom of detail pages.** Move up — more important than the score for agents deciding whether to recommend.
- [ ] **No "higher-rated alternatives" framing.** Related projects shows siblings. Reframe: "If you're considering X (score 20), look at Y (score 77)."
- [ ] **Many detail pages are thin content.** Pages without AI summaries have just score + metadata. Noindex until summaries backfill, or prioritise high-traffic pages.
- [ ] **Substack and directory not cross-linked.** They should cross-pollinate.

## Infrastructure

- [ ] **Favicon and basic brand identity.**
- [ ] **Canonical URLs for multi-vertical projects.**
- [ ] **Robots.txt audit.** Explicitly allow Googlebot, GPTBot, ClaudeBot.
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
