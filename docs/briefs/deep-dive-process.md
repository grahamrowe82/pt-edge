# Deep Dive Process

A deep dive is a hub page that creates a cluster of cross-linked content, drives internal authority to pages Google is already ranking, and feeds the allocation engine. Writing the article is one step of many.

## Why we choose topics

Topics are chosen where the **demand/supply gap** is widest, not where absolute demand is highest. Our structural advantage is in categories that content creators don't cover — voice-ai, embeddings, data engineering, MLOps — because they're unsexy to write about but developers still need to make decisions there.

The allocation engine identifies these gaps via:
- **Bayesian surprise ratio:** actual impression share vs expected (proportional to repos). A 10x deviation is a strong signal even at low volumes.
- **Position strength:** Google placing us at position 3 on a new domain = thin competition. This is Google telling us directly where the content gap is.
- The further a topic is from the LLM/agent hype cycle, the bigger our advantage.

For Substack companion pieces specifically, we also use the **nucleation pipeline** — a five-step process that identifies topics with high building activity, low narrative crystallisation, and large frustrated audiences. This optimises for readership on Substack, where "Your ___" framing and decision-driven content performs best. See `docs/briefs/topic-discovery-methodology.md` for the full methodology.

Deep dives are framed as **decision guides** because that's the unique value daily quality scores enable. "What should I use?" is a question only daily scoring can answer well — static blog posts can't.

## Prerequisites

- Allocation engine signal (surprise ratio, position strength, or ES score) indicating a demand/supply gap
- A clear editorial angle framed around the searcher's decision

## Research toolkit

PT-Edge has a rich set of data tools for deep dive research. **Use the right tool for each job — never fall back to ILIKE keyword matching or manual GitHub browsing.**

### Semantic search (primary discovery tool)

Use embedding search to discover the landscape. It finds thematically related projects regardless of naming conventions — ILIKE misses repos that use different terminology for the same concept.

| Tool | What it searches | How to use |
|------|-----------------|------------|
| `find_ai_tool(query)` | 100K+ AI repos (256-dim embeddings on `ai_repos.embedding`) | MCP tool or `GET /api/v1/projects?q=query` |
| `find_mcp_server(query)` | MCP server ecosystem | MCP tool |
| `find_public_api(query)` | 2.5K+ REST APIs with OpenAPI specs | MCP tool |
| `find_dataset(query)` | 42K+ HuggingFace datasets | MCP tool (via `more_tools()`) |
| `find_model(query)` | 18K+ HuggingFace models | MCP tool (via `more_tools()`) |
| FTS fallback | `ai_repos.fts` tsvector (name=A, description=B, topics=C weights) | `WHERE fts @@ plainto_tsquery('english', :query)` |

**Example:** To research agent governance, run:
- `find_ai_tool("agent governance framework guardrails safety")`
- `find_ai_tool("AI agent security audit compliance")`
- `find_ai_tool("agent access control permissions")`

NOT: `WHERE subcategory ILIKE '%governance%'`

### MCP research tools (structured exploration)

| Tool | Best for |
|------|----------|
| `topic(query)` | Ecosystem search — projects + HN posts + candidates in one call |
| `trending(domain=X)` | What's gaining stars fastest |
| `breakouts()` | Explosive % growth — rising from obscurity |
| `hype_check(slug)` / `hype_landscape(category=X)` | Stars vs actual downloads — are projects overhyped? |
| `compare(slugs)` | Side-by-side metrics for 2-5 projects |
| `project_pulse(slug)` | Deep profile on one project |
| `market_map()` | Concentration analysis, power law, lab dominance |
| `ecosystem_layer(layer)` | Explore by stack layer (MCP gateways, agents, perception, etc.) |
| `find_dependents(package)` | Reverse dependency lookup — who builds on this? |
| `velocity(domain=X)` | Development pace by commits/contributors |
| `scout()` | Rising projects not yet on the radar |

### Demand signals

| Source | What it tells you | How to query |
|--------|------------------|-------------|
| GSC (`gsc_search_data`) | What queries Google is ranking us for, impressions, CTR, position | `psql $DATABASE_URL` — join on page URL to map to domain/subcategory |
| Umami views | Who's visiting, what intent (business/research/directory), visitor class | `psql $UMAMI_DATABASE_URL` — `v_visitors`, `v_sessions`, `v_page_classes`, `v_business_leads` |
| Allocation engine (`mv_allocation_scores`) | EHS (demand heat from GSC+Umami) and ES (emergence from GitHub signals) | `psql $DATABASE_URL` — filter by domain, sort by `opportunity_score` |
| `v_deep_dive_queue` | Editorial priority ranking combining all signals | `psql $DATABASE_URL` |

### Contextual intelligence

| Source | What it tells you | How to query |
|--------|------------------|-------------|
| HN posts | Community sentiment, what's getting traction | `hn_pulse()` MCP tool or `GET /api/v1/hn?q=query` |
| Briefings | Curated intelligence per domain | `briefing(domain=X)` MCP tool |
| Papers | Academic citations for a project | `GET /api/v1/papers?project=X` |
| Commercial projects | Paid solutions in a category | `GET /api/v1/commercial-projects?category=X` |
| Dependencies | What packages a project uses / who depends on it | `find_dependents(package)` or `GET /api/v1/dependencies/{pkg}/dependents` |

### Anti-patterns

- **Never use ILIKE** for discovery on subcategory/description fields. It misses repos with different terminology but identical purpose. Use embedding search.
- **Never manually browse GitHub.** Every data point should come from PT-Edge queries. If you can't answer a question from our data, that's a feature gap to fix, not a reason to research manually.
- **Never skip HuggingFace.** Datasets and models are often the most valuable complement to the software tools — they tell you what people are actually building with.

## Process

### 1. Research the landscape

Use the research toolkit above to map the landscape. The workflow for each deep dive:

1. **Start with semantic search** to discover the landscape — run 3-5 embedding queries with different phrasings to cast a wide net. Run at least one **unfiltered** search (no domain filter) to catch cross-domain repos that are relevant but classified elsewhere. The governance deep dive nearly missed guardrails-ai (6.5K stars, in llm-tools) because initial searches were filtered to agents only.
2. **Pull the subcategory quality distribution early.** Query `avg(quality_score)`, `max(quality_score)`, and repo count per relevant subcategory. This does two things: it reveals the article's section structure (subcategories often map to sections), and the contrast between volume and quality becomes the core editorial tension. "250 repos, average quality 24/100" is more powerful than either number alone.
3. **Check HN for community signal.** HN posts tell a story the repo data can't — where community energy is concentrated, what's generating meta-discussion, what pain points people are articulating. This shapes the narrative arc and helps you identify which layers/areas are mature vs early. Do this before outlining sections.
4. **Use allocation scores** to identify which subcategories have the strongest demand signal (EHS for established demand, ES for emerging opportunity)
5. **Cross-reference GSC** for which pages Google is already ranking — reinforce what's working. Even one click at good position tells you which page to anchor the article to. For topics where GSC data is thin, the deep dive itself becomes the demand generation.
6. **Check Umami** for which pages attract business-intent or research-intent visitors
7. **Use trending/breakouts** to find emerging projects the static search might miss
8. **Check HuggingFace** for relevant datasets and models that complement the software tools
9. **Map dependencies** to understand which tools are infrastructure vs application layer

**After research, before writing:** Draft the section structure based on the subcategory distribution and HN signal. This was the most generative step in the governance deep dive — the four-layer stack (sandbox → guardrails → monitoring → auditing) emerged from the subcategory data and HN attention patterns, not from the article outline.

**Save research outputs** to `docs/briefs/{slug}-research.md` before writing — this preserves the research for future reference and ensures expensive queries aren't repeated.

### 2. Identify featured repos and categories

Select 15-30 repos for `featured_repos` in the manifest. These drive the reverse links from server detail pages back to the deep dive. Include:

- Top quality-scored projects (the recommendations)
- Popular-but-dead projects (the warnings)
- Emerging/trending projects (the "watch these" picks)
- Projects Google is already ranking (reinforce what's working)

Select 5-10 categories for `featured_categories`.

**Important:** Verify repo owners haven't changed. Check `ai_repos.full_name` matches what you expect — owners change (e.g., `ggerganov/whisper.cpp` became `ggml-org/whisper.cpp`).

### 3. Write the article

**JSON manifest** (`docs/deep_dives/{slug}.json`):
```json
{
    "slug": "voice-ai-landscape",
    "title": "Choosing a Voice AI Library in 2026: What's Actually Worth Building On",
    "subtitle": "...",
    "author": "Graham Rowe",
    "primary_domain": "voice-ai",
    "domains": ["voice-ai", "agents", "nlp"],
    "meta_description": "...",
    "template_file": "{slug}.html",
    "featured_repos": ["espnet/espnet", "rany2/edge-tts", ...],
    "featured_categories": ["voice-ai:lightweight-tts-libraries", ...],
    "status": "published"
}
```

**HTML template** (`docs/deep_dives/{slug}.html`):
- Jinja2 rendered at build time with live data
- `repos.get('owner/repo', {})` for live metrics (stars, commits, quality_score)
- `domain_path('domain')` for internal link prefixes
- Link every project name to its PT-Edge server detail page
- Link category references to category pages
- End with CTAs: category directory, trending page

**Tone:** Frame around the searcher's decision. Not a data dump.

### 4. Insert into the database

```bash
source .env && .venv/bin/python scripts/insert_deep_dive.py docs/deep_dives/{slug}.json
```

This upserts into the `deep_dives` table. The `generate_deep_dives.py` script reads from this table at container startup.

### 5. Write the Substack companion

A simplified HTML version at `docs/substack/{slug}.html`:

- ~800 words (Substack audience skims)
- Basic HTML only — no tables, no CSS, no scripts (Substack strips them)
- Every project name links to its PT-Edge server detail page
- Ends with CTA to the full deep dive on the site
- Ends with links to directory, categories, and trending pages

### 6. Verify all links

Before publishing, check every link returns HTTP 200:

```bash
# Check all PT-Edge links in the Substack HTML
grep -oP 'href="https://mcp\.phasetransitions\.ai[^"]*"' docs/substack/{slug}.html | \
  tr -d '"' | sed 's/href=//' | while read url; do
    code=$(python3 -c "import urllib.request; print(urllib.request.urlopen('$url').getcode())" 2>&1)
    echo "$code $url"
  done
```

### 7. Deploy and verify

1. Commit the JSON, HTML, Substack HTML, and any template changes
2. Push and merge the PR
3. Trigger a deploy on the `pt-edge` web service (clear build cache if needed)
4. Verify the deep dive renders at `/insights/{slug}/`
5. Verify "Featured in" links appear on featured repo server detail pages
6. Verify the deep dive appears on the `/insights/` index
7. Publish the Substack companion with links to the live deep dive
8. Check Umami for traffic flowing from Substack to the site

## What's automated

- **Reverse links** from server detail pages to deep dives: two mechanisms, both zero-maintenance:
  1. **Explicit repo links** via `featured_repos`: repos whose live metrics appear inside the deep dive template get a "Featured in" link. These are the 15-30 repos you explicitly analyse.
  2. **Subcategory-level links** via `featured_categories`: every repo in a relevant subcategory gets a "Featured in" link. This means a deep dive about agent governance automatically links from all 1,263 governance repos, not just the 25 you featured. Users browsing any part of the landscape can discover the zoomed-out analysis. When `generate_site.py` runs, it builds both lookups and deduplicates them per repo.
- **Live data** in deep dive templates: `repos.get()` pulls current stars, commits, quality scores at build time. Numbers stay fresh on every deploy.
- **Insights index**: automatically lists all published deep dives from the database.
- **Cross-linking between deep dives**: automatic via shared `domains` and `featured_categories` in the manifest. Each deep dive shows up to 4 related deep dives in a "Related analysis" section at the bottom. Ensure your manifest's domains and categories accurately reflect the deep dive's scope — this drives the cross-links. Shared categories are weighted higher than shared domains.

The subcategory-level linking was added after observing real visitor behaviour: an Indian developer browsed three agent-governance repos in 90 seconds, but none were in the deep dive's `featured_repos`. With category-level linking, every repo in the relevant subcategories gets a path to the analysis page.

## Lessons from production

Observations from producing deep dives, updated as we learn.

**Semantic search is dramatically better than keyword matching.** Three embedding queries for the governance piece returned a coherent landscape that naturally clustered into four layers. ILIKE on subcategory would have found about half the repos and missed all the cross-domain connections.

**The subcategory taxonomy reveals article structure.** Pulling subcategory counts + avg/max quality early gives you the section outline almost for free. The governance four-layer stack emerged from the subcategory data, not from pre-planning.

**HN is the best narrative signal.** Repo metrics tell you what exists. HN tells you what people care about and where they feel pain. The governance article's central claim — "sandboxing is the only mature layer" — came from seeing 492 HN points for Agent Safehouse vs. near-silence on policy enforcement tools.

**Write the full article first, Substack second.** The Substack companion is a compression of the full piece. It wrote itself once the article structure was clear. Don't try to write them in parallel.

**One GSC click can anchor an entire article.** The governance piece had just one click (agent governance toolkit, position 9.8), but that told us exactly which page and audience to anchor to. For topics with thin GSC data, the deep dive itself creates the demand — write the content that will generate future impressions.

**Quality distribution is the editorial hook.** "250 repos exist" is a fact. "250 repos, average quality 24/100" is a story. Always pull avg and max quality per subcategory — the gap between volume and quality is where the analysis lives.

## Known gaps (on roadmap)

- **Cross-category comparisons:** The comparison system only generates pairs within subcategories. High-value matchups (WhisperX vs whisper.cpp) that cross subcategory boundaries are never generated. Needs architectural change to `build_comparison_pairs()`.
- **Subcategory classifier quality:** High-quality repos sometimes land in wrong solo categories (e.g., ElevenLabs in `ai-workflow-automation`). This isolates them from comparisons and related servers. Needs classifier investigation.
