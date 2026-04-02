# kairn: Strategic Dependency Intelligence for AI

**A PT-Edge product concept — April 2026**

## The gap

Security scanners (Snyk, Trivy) tell you a library is safe. Version bumpers (Dependabot, Renovate) tell you it's up to date. Neither tells you it's the right library to be using at all — whether it's losing momentum, whether a better alternative exists in the same category, or whether the maintainer has quietly stopped shipping.

That strategic layer — ongoing intelligence about whether your dependency *choices* are sound — is the gap kairn fills. And it's a gap that matters most in AI, where the ecosystem moves faster than any software category in history.

## Why PT-Edge is uniquely positioned

This product requires:
- Category mapping (which libraries compete with each other) — solved via embedding-based subcategory clustering across 220K+ repos
- Quality scoring (maintenance, adoption, maturity, community) — running daily in production
- Momentum tracking (7d/30d star deltas, download growth, commit velocity) — computed in `mv_momentum`
- Lifecycle staging (experimental → growth → mature → declining) — computed in `mv_lifecycle`
- Dependency graph data — `package_deps` table with PyPI/npm linkages across tracked repos

No other dataset combines all five. A security scanner knows packages but not categories. A GitHub trending page knows momentum but not quality. PT-Edge knows all of it.

## Five-step build plan

### Step 1: Manual audit deep dive (the proof of concept)

Pick a real, well-known open-source AI project and audit its AI dependencies by hand against PT-Edge data. Publish as a deep dive: "We Audited the AI Dependencies of [Project]: Here's What We Found."

**Purpose:** Validate the concept with real data. Discover which metrics are load-bearing, where the gaps are, and what a useful strategic fitness report actually looks like — before building any infrastructure.

**What the audit covers per AI dependency:**
- Quality score and category rank
- Momentum direction (gaining or losing stars/downloads)
- Lifecycle stage
- Maintenance velocity (commits, releases, issue response)
- The top-ranked alternative in the same subcategory
- A strategic assessment: keep, watch, or evaluate alternatives

**Candidate projects (shortlist):**

1. **crewAI** (45.9K stars, agents) — **recommended for first audit**
   - 47 direct dependencies, clean and focused
   - Key AI deps already trackable: litellm (38.9K stars), tokenizers (10.5K), lancedb (9.4K), qdrant-client (1.2K)
   - Massive audience: most-discussed agent framework, developers will care about the findings
   - The dependency choices are genuinely interesting — CrewAI picked LiteLLM over direct OpenAI/Anthropic clients, LanceDB over Chroma, qdrant-client as a secondary vector store
   - Clean narrative: "The AI dependency decisions behind the most popular agent framework"

2. **gpt-researcher** (25.7K stars, llm-tools) — strong alternative
   - 159 dependencies, much broader surface area
   - Heavy cross-domain: web scraping (Firecrawl, Scrapy), LLM clients (LiteLLM, LangChain, Ollama), RAG tooling (Unstructured, LangGraph)
   - Narrative: "Building a production research agent — the dependency supply chain"
   - More complex audit, better for showing breadth of the concept

3. **camel-ai/camel** (16.3K stars, agents) — maximum depth
   - 167 dependencies across 17 AI domains
   - Most diverse AI dependency profile in the database
   - Includes HF Transformers, Diffusers, Gradio, LiteLLM, Langfuse, AgentOps, Milvus, Qdrant
   - Narrative: "How a multi-agent framework orchestrates the entire AI stack"
   - Best for comprehensive audit, but may be too complex for a first attempt

**Recommendation:** Start with crewAI. It's the right size (focused enough to be thorough, complex enough to be interesting), the audience is large, and the dependency choices are genuinely debatable. Save camel-ai for a follow-up that shows the concept at scale.

### Step 2: Formalise the metrics (materialised view)

Based on what we learn from the manual audit, build `mv_strategic_fitness` — a pre-computed view that scores each trackable AI repo on:

- **Category rank** — percentile position within subcategory by quality score
- **Momentum direction** — classified from `mv_momentum` (accelerating / steady / declining)
- **Maintenance risk** — derived from commits_30d, last_pushed_at, open issue response time
- **Top alternative** — the highest-quality-scored repo in the same subcategory (excluding self)
- **Dependency risk exposure** — % of tracked AI projects that depend on this repo (from `package_deps`)

**Existing MVs that feed this (already computed daily):**
- `mv_*_quality` (18 domain views) — quality scores
- `mv_lifecycle` — lifecycle stage
- `mv_velocity` — commit frequency
- `mv_momentum` — star/download acceleration
- `mv_hype_ratio` — stars vs actual usage
- `mv_traction_score` — combined adoption signal

**New data needed:**
- Reverse dependency counts (how many tracked repos depend on X) — derivable from existing `package_deps`
- Category percentile rank — simple window function over quality scores per subcategory
- Top alternative lookup — `FIRST_VALUE` over quality-ordered subcategory peers

### Step 3: Integrate into server detail pages

Add a "Strategic Fitness" section to server detail pages for repos where category context is meaningful. Not a new page — an enrichment of the existing detail page.

**What it shows:**
- Category rank: "Ranked #3 of 47 in lightweight-tts-libraries"
- Momentum: "Rising — gained 1,200 stars in the last 30 days"
- Top alternative: "Category leader: edge-tts (69/100)"
- Lifecycle: "Growth stage — active development, expanding adoption"

**Where it appears:** Only on repos with a quality score > 20 and a subcategory with 5+ peers. Below that, the category context isn't meaningful enough to rank.

This turns every server detail page into a mini kairn report — the same strategic intelligence, delivered as a web page.

### Step 4: Add the API endpoint

`POST /api/v1/audit` — accept a list of package names (or a raw `requirements.txt`), match against `ai_repos` via package registry mappings, return strategic fitness data from the MV.

**Request:**
```json
{
  "packages": ["litellm", "lancedb", "qdrant-client", "tokenizers"],
  "source": "pypi"
}
```

**Response per matched package:**
```json
{
  "package": "litellm",
  "matched_repo": "BerriAI/litellm",
  "quality_score": 85,
  "category": "llm-proxy-routers",
  "category_rank": 1,
  "category_size": 34,
  "momentum": "accelerating",
  "lifecycle": "growth",
  "top_alternative": {"repo": "portkey-ai/gateway", "score": 72},
  "assessment": "category_leader"
}
```

**Free tier:** Quality score, lifecycle stage, category rank.
**Paid tier:** Momentum data, alternative recommendations, historical comparisons, batch audits.

### Step 5: Open-source scanner (distribution layer)

A CLI tool (`kairn`) that reads `requirements.txt` / `pyproject.toml` / `package.json`, calls the audit endpoint, and renders a strategic dependency health report.

```bash
$ kairn scan requirements.txt
Scanning 47 dependencies... 12 matched PT-Edge AI records.

  litellm        85/100  #1 of 34  ↑ accelerating  ✓ category leader
  lancedb        72/100  #2 of 19  ↑ accelerating  ✓ strong
  tokenizers     68/100  #1 of 8   → steady         ✓ category leader
  qdrant-client  61/100  #3 of 19  → steady         ⚠ watch: lancedb gaining
  ...

35 dependencies outside AI tooling scope (not scored).
```

Open source (MIT). Every scan is an API call. The scanner is the distribution channel; the data stays proprietary.

## Buyer personas

From [docs/briefs/pt-edge-api-buyers.md](pt-edge-api-buyers.md):

| Buyer | kairn value | Price sensitivity |
|---|---|---|
| **CTOs / architects** (H4) | Live technology radar for their AI stack | $18-36K/year — replaces manual quarterly reviews |
| **VC due diligence** (H2) | Dependency risk scoring for portfolio companies | $12-24K/year — data for investment memos |
| **AI consultancies** (H1) | Embed dependency audits in client deliverables | $12-36K/year — billable to clients |
| **Developer tool companies** (H3) | Competitive intelligence on which libs rivals use | $12-24K/year — strategic |

CTO/architects is the primary market. They already buy ThoughtWorks Radar (annual, static) and Gartner (expensive, slow). A live, data-backed, AI-specific alternative is immediately differentiated.

## Revenue model

- **Open source:** The scanner CLI (reads lock files, generates reports)
- **Proprietary:** The PT-Edge API powering scores, rankings, alternatives, momentum data
- **Free tier:** Quality scores and lifecycle stages per dependency
- **Paid tier:** Category rankings, alternative recommendations, trend data, historical comparisons, team dashboards, CI integration

## The flywheel

Every kairn scan generates two signals:
1. **API usage** — reinforces PT-Edge as canonical source of AI ecosystem intelligence
2. **Dependency discovery** — unrecognised AI packages signal what developers actually use in production, expanding coverage organically toward what matters most

## Name

**kairn** — a trail marker that tells you you're on the right path.

The cairn (a stone marker left on trails), a kernel of truth (real signal about your dependencies), and the tech kernel (the foundational layer your stack runs on).

*Know your path.*
