# Deep Dive Process

A deep dive is a hub page that creates a cluster of cross-linked content, drives internal authority to pages Google is already ranking, and feeds the allocation engine. Writing the article is one step of many.

## Why we choose topics

Topics are chosen where the **demand/supply gap** is widest, not where absolute demand is highest. Our structural advantage is in categories that content creators don't cover — voice-ai, embeddings, data engineering, MLOps — because they're unsexy to write about but developers still need to make decisions there.

The allocation engine identifies these gaps via:
- **Bayesian surprise ratio:** actual impression share vs expected (proportional to repos). A 10x deviation is a strong signal even at low volumes.
- **Position strength:** Google placing us at position 3 on a new domain = thin competition. This is Google telling us directly where the content gap is.
- The further a topic is from the LLM/agent hype cycle, the bigger our advantage.

Deep dives are framed as **decision guides** because that's the unique value daily quality scores enable. "What should I use?" is a question only daily scoring can answer well — static blog posts can't.

## Prerequisites

- Allocation engine signal (surprise ratio, position strength, or ES score) indicating a demand/supply gap
- A clear editorial angle framed around the searcher's decision

## Process

### 1. Pull the data

Query the PT-Edge database (`psql $DATABASE_URL`) for the domain/category data:

- Domain overview: repo count, quality distribution, category count
- Top projects by quality score (the recommendations)
- Top projects by stars (popular — may differ from quality leaders)
- Category landscape (subcategories with most activity)
- Stale high-star repos (dependency risk warnings — only if famous)
- Language distribution
- GSC data: which pages Google is already ranking, what queries drive impressions
- Umami data: which pages real visitors engage with

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

- **Reverse links** from server detail pages to deep dives: driven by `featured_repos` in the `deep_dives` table. When `generate_site.py` runs, it queries all published deep dives and builds a reverse lookup. Any repo in `featured_repos` gets a "Featured in" section on its detail page linking to the deep dive. Zero manual maintenance.
- **Live data** in deep dive templates: `repos.get()` pulls current stars, commits, quality scores at build time. Numbers stay fresh on every deploy.
- **Insights index**: automatically lists all published deep dives from the database.

## Known gaps (on roadmap)

- **Cross-category comparisons:** The comparison system only generates pairs within subcategories. High-value matchups (WhisperX vs whisper.cpp) that cross subcategory boundaries are never generated. Needs architectural change to `build_comparison_pairs()`.
- **Subcategory classifier quality:** High-quality repos sometimes land in wrong solo categories (e.g., ElevenLabs in `ai-workflow-automation`). This isolates them from comparisons and related servers. Needs classifier investigation.
