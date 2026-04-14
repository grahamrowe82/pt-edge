# CyberEdge Future Work

Post-launch quality audit (2026-04-14) identified these improvements beyond the initial fix pass.

## 1. Data Pipeline Gaps

### Populate `pattern_techniques` table
The junction table linking CAPEC attack patterns to MITRE ATT&CK techniques has **0 rows**, despite `techniques` having 691 rows and `weakness_patterns` having 1,212. The kill chain (CVE → CWE → CAPEC → ATT&CK) breaks at the CAPEC→ATT&CK step.

**Impact:** Technique pages are empty. Homepage hides the "ATT&CK Techniques" card (0 count). `mv_technique_scores` produces 0 rows.

**Fix:** Add MITRE ATT&CK data ingest that parses ATT&CK STIX data and populates `pattern_techniques` with CAPEC→technique mappings. MITRE publishes this as part of their ATT&CK STIX bundle.

### Snapshot history depth
Only 3 days of score snapshots exist (Apr 12-14). Trending requires 7+ days of history to produce meaningful results. The trending page currently shows "No trending data yet" (by design — the fix pass added a 7-day minimum).

**Action:** Verify the daily snapshot cron is running. After 2+ weeks, trending should populate naturally.


## 2. Content Depth Parity with AI Open Source Site

The AI open source directory (phasetransitions.ai) has significantly richer detail pages. Key gaps:

### Decision guidance
- **AI open source:** "Use this if" / "Not ideal if" per repo (from `repo_briefs`)
- **CyberEdge:** "Am I affected?" / "What to do" exists for CVEs (from `cve_metadata`), but products, vendors, and weaknesses have only generic tier-based guidance
- **Action:** Extend Gemini enrichment to generate product-level and weakness-level guidance

### Related/similar items
- **AI open source:** 5 related servers with scores on each detail page
- **CyberEdge:** No related items section
- **Action:** Use `product_metadata.peer_products` (already partially populated) and build similar linkage for weaknesses/patterns

### Community signals
- **AI open source:** Hacker News discussions, recent releases per repo
- **CyberEdge:** Only raw NVD references
- **Action:** Consider linking to vendor advisories, security blogs, or exploit write-ups where available

### Risk flags with explanations
- **AI open source:** Shows "archived", "stale", "no-license" flags with explanations
- **CyberEdge:** No equivalent warning system
- **Action:** Add flags like "end-of-life product", "no patches available", "internet-facing"

### Dense internal cross-linking
- **AI open source:** 10-15 internal links per page (categories, comparisons, related)
- **CyberEdge:** Minimal cross-linking (kill chain links only)
- **Action:** Add links to related CVEs, affected products (from product pages), vendor pages, weakness pages. Target 10+ internal links per detail page.

### Deep-dive analysis articles
- **AI open source:** Briefings and deep-dive articles per domain
- **CyberEdge:** No editorial content
- **Action:** Consider automated analysis articles (e.g., "Most exploited weaknesses of 2025", "Products with the fastest patch response")

### Comparison pages
- **AI open source:** Side-by-side comparison pages (repo A vs repo B)
- **CyberEdge:** No equivalent
- **Action:** Product comparison pages (e.g., "Apache vs Nginx vulnerability profile")


## 3. API Onboarding

API references were stripped from all templates in the initial fix pass because there was no way for users to discover or create API keys. The API infrastructure exists and works:

- **Routes:** `domains/cyber/app/api/routes.py` — 6 entity endpoints (CVEs, software, vendors, weaknesses, techniques, patterns)
- **Key creation:** `POST /api/v1/keys` — self-serve, requires email + company name, max 3 keys per email
- **Rate limiting:** 100 requests/day on free tier
- **Usage tracking:** `APIUsageMiddleware` logs every request

### To re-introduce the API:
1. **Sign-up page** — form that POSTs to `/api/v1/keys`, displays the generated key
2. **API documentation page** — endpoints, auth, rate limits, response schemas, example responses
3. **Link from detail pages** — re-add the curl blocks but with a link to the sign-up/docs page instead of "YOUR_KEY"
4. **OpenAPI spec** — FastAPI can auto-generate this; expose at `/api/docs`


## 4. Product Metadata Enrichment

The `product_metadata` table exists (migration 014) with fields for:
- `embedding` (vector 1536) — for semantic similarity
- `category` / `category_label` — product classification
- `risk_summary` — overrides default tier guidance
- `recommended_actions` — overrides default action list
- `peer_products` — similar products for comparison

Currently sparse. Expanding coverage would improve product detail pages significantly.

**Action:** Run Gemini enrichment batch across top-scored products (score > 50 or CVE count > 20). Prioritise products that get organic traffic.


## 5. Site Polish

### Breadcrumbs
Detail pages lack breadcrumb navigation. Add: Home → Entity Type → Entity Name.

### Human-readable freshness
Pages show "Last generated 2026-04-14" in the footer but don't state freshness in prose. Add per-page text like "Data as of April 14, 2026" near the top of detail pages.

### Suppress empty sections
Some detail pages render section headers with empty content (e.g., "0 exploits" headers, empty kill chain sections). Hide sections entirely when there's no data.

### JSON-LD structured data
Homepage has JSON-LD. Detail pages should have entity-specific structured data (CVE → SecurityAdvisory schema, Product → SoftwareApplication, etc.) for rich search results.

### Meta description quality
CVE meta descriptions now use Jinja2 `truncate(160)` for word-boundary-aware truncation. Other entity types should follow the same pattern rather than relying on the generic base template description.
