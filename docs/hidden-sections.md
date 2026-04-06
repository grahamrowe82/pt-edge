# Hidden Site Sections

*7 April 2026*

Three sections shipped as part of the worker-to-site audit (PRs 3, 4, 12) have been commented out in the templates. The data pipeline and site generator infrastructure remain in place — the sections are hidden at the template level only and can be re-enabled by uncommenting the Jinja blocks.

## What's hidden and why

### 1. Assessment section on project pages

**Template:** `templates/server_detail.html`
**Data source:** `repo_briefs` table (5,603 briefs), fetched by `fetch_repo_briefs()` in `generate_site.py`

**Problem:** The current repo brief prompt produces generic summaries like "This project is highly dependable, with very active development and broad adoption by a large community." This is a vacuous restatement of what the quality score already communicates. The evidence list (stars, downloads, commits) duplicates the key metrics table that appears lower on the page. The section adds noise and pushes more useful content down.

**To re-enable:** The repo brief prompt (`enrich_repo_brief.py`) needs to produce genuinely analytical content — comparative positioning, architectural trade-offs, specific strengths/weaknesses that aren't obvious from the metrics. The template should render this below the quality scores, not above them.

### 2. Domain brief on landing pages

**Template:** `templates/index.html`
**Data source:** `domain_briefs` table (17 briefs), fetched by `fetch_domain_brief()` in `generate_site.py`

**Problem:** A single static paragraph in a prime position (between hero and tier grid) doesn't add enough value. The content is generated once and goes stale. Some briefs are analytical ("Agent Orchestration Dominates...") but others are generic. The section occupies valuable above-the-fold space without earning it.

**To re-enable:** Either integrate with fresher signals (trending repos, recent activity) so the content changes meaningfully between rebuilds, or move below the fold where a static summary is less costly.

### 3. Briefings ("What's New") on landing pages

**Template:** `templates/index.html`
**Data source:** `briefings` table (38 briefings), fetched by `fetch_briefings()` in `generate_site.py`

**Problem:** The briefings render as text blocks with no links. On a website, content that looks like it should be clickable but isn't is worse than not showing it at all. Users expect to click through to read more.

**To re-enable:** Either generate dedicated briefing pages that the section can link to, or render briefings as expandable cards that show the full `detail` field inline.

## What stayed live

These sections from the audit shipped and are working well:

- **Community Discussion** (HN links on project pages) — strong social proof with real engagement data, links to external discussions
- **Recent Releases** (release history on project pages) — useful signal showing active shipping, links to GitHub releases
- **use_this_if / not_ideal_if** (decision guidance on project pages) — already in the template, coverage expanding via normal enrichment pipeline
