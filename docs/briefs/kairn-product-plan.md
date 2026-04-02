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

**Prerequisite: package-to-repo mapping table.** The manual crewAI audit (Step 1) immediately exposed a critical infrastructure gap. There is no reliable mapping between PyPI/npm package names and GitHub repos. Our current approach (`lower(ai_repos.name) = lower(dep_name)`) produced wrong matches and missed matches:

- `anthropic` on PyPI → matched to `tryAGI/Anthropic` (a C# wrapper), not `anthropics/anthropic-sdk-python`
- `openai` on PyPI → matched to `betalgo/openai` (.NET library), not `openai/openai-python`
- `mcp` on PyPI → matched to `awslabs/mcp` (AWS MCP), not `modelcontextprotocol/python-sdk`
- `chromadb` on PyPI → no match at all (repo is `chroma-core/chroma`)
- `mem0ai` on PyPI → no match (repo is `mem0ai/mem0`)
- `instructor` on PyPI → no match (repo is `jxnl/instructor`)

**Resolution: bidirectional mapping with continuous validation.** Build a `package_registry_map` table:

```
package_name  | registry | github_repo                      | verified_at
--------------+----------+----------------------------------+------------
litellm       | pypi     | BerriAI/litellm                  | 2026-04-02
anthropic     | pypi     | anthropics/anthropic-sdk-python   | 2026-04-02
chromadb      | pypi     | chroma-core/chroma                | 2026-04-02
```

Populated from two directions:
1. **PyPI/npm → GitHub (Direction A):** Hit `https://pypi.org/pypi/{package}/json`, extract `project_urls.Repository` or `Homepage` containing github.com. This is the direction the audit endpoint needs.
2. **GitHub → PyPI/npm (Direction B):** For repos in `ai_repos`, check their `pyproject.toml` or `package.json` for the published package name. This is the reverse direction for pre-building the lookup.

Both directions run continuously. If A→B and B→A agree, the mapping is verified. If they disagree, flag for investigation. This also serves as a crawling mechanism: walk the dependency graph from any node, discover new repos and packages at each edge, and expand coverage organically.

`POST /api/v1/audit` — accept a list of package names (or a raw `requirements.txt`), match against `ai_repos` via the verified mapping table, return strategic fitness data from the MV.

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

## Findings from manual audit (updated as we learn)

Running log of insights from the crewAI dependency audit. Each finding updates the plan above.

### Finding 1: Package-to-repo mapping is a prerequisite, not an afterthought

**Date:** 2026-04-02

**What happened:** First attempt to match crewAI's 47 PyPI dependencies against `ai_repos` by name (`lower(name) = lower(dep_name)`) produced 9 matches. Of those, 3 were wrong (matched to .NET wrappers or unrelated repos with the same name). Major dependencies like chromadb, mem0ai, instructor, anthropic SDK, and openai SDK were missed entirely.

**Root cause:** PyPI package names and GitHub repo names are not the same thing. `chromadb` publishes from `chroma-core/chroma`. `anthropic` publishes from `anthropics/anthropic-sdk-python`. There's no lookup table mapping between them.

**Impact on plan:** This blocks Step 4 (API endpoint) entirely. Without a reliable mapping, the audit endpoint can't match package names to scored repos. Added `package_registry_map` table and bidirectional validation to the plan.

**Broader insight:** The bidirectional mapping also enables a dependency graph crawl — walk from any node (repo or package), discover new nodes at each edge, expand coverage organically. This is the mechanism behind the second flywheel (dependency discovery).

### Finding 2: PyPI metadata resolves most mappings, but coverage gaps are significant

**Date:** 2026-04-02

**What happened:** Running Direction A (PyPI → GitHub) on crewAI's 47 deps:
- **30 resolved** to a GitHub repo via `project_urls` or `homepage`
- **17 had no GitHub URL** in PyPI metadata (including major packages: lancedb, mem0ai, instructor, tiktoken, voyageai, docling, pandas)
- Of the 30 resolved, **8 are tracked in ai_repos** with quality scores
- **24 are not tracked** — including critical AI infrastructure: `anthropics/anthropic-sdk-python`, `openai/openai-python`, `modelcontextprotocol/python-sdk`, `pydantic/pydantic`

**The coverage picture for crewAI:**

| Category | Count | Examples |
|---|---|---|
| **Tracked + scored** | 8 | litellm (98), chroma (94), lancedb (94), tokenizers (90), qdrant-client (86), json_repair (75), mem0 (72) |
| **PyPI resolved but not tracked** | 22 | anthropic SDK, openai SDK, pydantic, MCP python-sdk, httpx, opentelemetry, uv, boto3 |
| **No PyPI GitHub URL** | 17 | instructor, tiktoken, lancedb*, mem0ai*, voyageai, docling, pandas |

*lancedb and mem0ai are tracked in ai_repos but PyPI didn't resolve to GitHub — we know them from our own ingestion, not from PyPI metadata.

**Key insight:** PT-Edge tracks AI-specific repos (220K+) but doesn't track foundational Python infrastructure (pydantic, httpx, click) or LLM provider SDKs (openai-python, anthropic-sdk-python). This is correct for the directory but creates a gap for kairn: a dependency audit needs to score *all* AI-relevant deps, including the provider SDKs.

**Decision for the manual audit:** For the 8 tracked deps, use full quality scoring. For the untracked AI-relevant deps (anthropic SDK, openai SDK, MCP SDK, pydantic), note them as "outside current scoring but strategically important." For general infrastructure (click, httpx, tomli), classify as "out of scope — not AI-specific." This mirrors what a real kairn report would look like.

### Finding 3: The "AI dependency" boundary is blurry

**Date:** 2026-04-02

**What happened:** crewAI's 47 deps include a spectrum from clearly-AI (litellm, chromadb) to clearly-not-AI (tomli, click, regex) to ambiguous (pydantic — foundational but critical for AI structured outputs; opentelemetry — general but increasingly AI-agent-specific; httpx — general but the standard for async LLM API calls).

**Impact:** The kairn report needs a clear framework for what counts as "AI dependency" vs "general infrastructure." Three tiers:
1. **AI-specific** — repos in PT-Edge's AI taxonomy (litellm, chromadb, tokenizers, etc.). Full scoring.
2. **AI-adjacent** — provider SDKs (openai, anthropic), AI-heavy general tools (pydantic for structured outputs, opentelemetry for agent tracing). Strategic commentary without quality scoring.
3. **General infrastructure** — (click, httpx, tomli, regex). Out of scope, noted as such.

This tiering should be documented in the kairn output so users understand why 35 of 47 deps aren't scored.

### Finding 4: PT-Edge has a foundational coverage gap — not just a kairn problem

**Date:** 2026-04-02

**What happened:** The crewAI audit revealed that PT-Edge's 18 domains are all *application-level* categories (what people build with AI). The *foundation-level* — what AI applications are built on top of — is not tracked at all. This includes some of the most critical infrastructure in the AI ecosystem:

**Not tracked:**
- `openai/openai-python` (~20K stars) — the most depended-on AI SDK in existence
- `anthropics/anthropic-sdk-python` — Claude's official SDK
- `modelcontextprotocol/python-sdk` — the MCP protocol SDK (we track 12K MCP *servers* but not the protocol SDK itself)
- `pydantic/pydantic` (~22K stars) — structural backbone of every LLM application
- `googleapis/python-genai` — Google's GenAI SDK
- `open-telemetry/opentelemetry-python` — the observability standard, increasingly critical for agent tracing

**Why this matters beyond kairn:** This isn't just a data gap for dependency auditing. It's a gap in the core directory product. Someone searching "best Python SDK for Claude" or "anthropic SDK quality" should find a scored, ranked answer on PT-Edge. They won't, because these repos aren't in the index. The site claims to track AI infrastructure but misses the foundational layer everything else depends on.

**Potential fix:** A new domain (e.g., `foundations` or `ai-infrastructure`) covering:
- LLM provider SDKs (openai, anthropic, google-genai, cohere, mistral)
- Structured output / validation (pydantic, instructor, outlines, marvin)
- Async HTTP / transport (httpx, aiohttp — the plumbing every LLM call flows through)
- Observability instrumentation (opentelemetry, datadog — the tracing layer agents need)
- Protocol SDKs (MCP python-sdk, MCP typescript-sdk, A2A SDKs)
- Tokenisation (tiktoken — already partially tracked in transformers but conceptually foundational)

The argument for a distinct domain rather than distributing into existing domains: these aren't tools you choose between in the same way as agent frameworks. They're layers you build on. The decision framework is different ("which provider SDK is best maintained?" not "which agent framework should I use?") and the audience is different (every AI developer, not just developers in one vertical).

**Impact:** This is a core product coverage issue, not just a kairn prerequisite. Should be addressed in the roadmap independently of kairn. However, kairn makes it urgent — you can't audit AI dependencies if you don't track the most fundamental ones.

**Not solving now.** Recording for proper follow-up. The manual audit continues with the 8 tracked deps and strategic commentary on the untracked AI-relevant ones.

### Finding 5: Subcategory classification makes "top alternative" unreliable

**Date:** 2026-04-02

**What happened:** The "top alternative" for each crewAI dep was computed as the highest-quality repo in the same subcategory. Results were often useless: Chroma's top alternative was `chroma-go` (a Go client, not a competing database). LanceDB's was `VectorDBBench` (a benchmarking tool). Qdrant-client's was `qdrant` (the server itself).

**Root cause:** Subcategories are too narrow and sometimes group by ecosystem rather than function. "chroma-database-tools" (27 repos) contains Chroma ecosystem projects, not competing vector databases. A real alternative to Chroma is Qdrant or LanceDB — but those are in different subcategories.

**Impact on plan:** The `mv_strategic_fitness` view's "top alternative" field (Step 2) can't just use subcategory peers. It needs either domain-level comparison (all vector-db repos) or embedding-similarity to find functionally equivalent repos. This is the same cross-category comparison problem already flagged in the roadmap for the directory.

### Finding 6: Reverse dependency count is the most novel metric

**Date:** 2026-04-02

**What happened:** Querying `package_deps` for how many tracked repos depend on each crewAI dep produced the most differentiated data in the entire audit. No existing tool provides "how many AI projects depend on this?"

Key numbers: pydantic (1,029 repos), openai (866), httpx (579), mcp (421), anthropic (229), litellm (155), chromadb (126). These tell you systemic importance — how much of the ecosystem breaks if this library has a problem.

**Impact on plan:** Reverse dependency count should be a headline metric in kairn reports, not just a secondary signal. It's the metric no other tool can provide and it answers the question "how important is this dependency to the broader ecosystem, not just to my project?"
