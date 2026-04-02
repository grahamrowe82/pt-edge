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

## Build plan (revised after crewAI audit)

The manual crewAI audit (see "Findings from manual audit" below) surfaced seven findings that reshape the build plan. The original five product steps remain, but they now depend on infrastructure fixes that the audit revealed. The steps below are ordered by dependency chain — each unblocks the next.

### Step 0: Manual audit deep dive [DONE]

Audited crewAI's 47 dependencies by hand against PT-Edge data. Published as a deep dive. Surfaced seven findings that inform everything below. Full results: [docs/briefs/kairn-crewai-audit.md](kairn-crewai-audit.md). Baseline comparison: [docs/briefs/kairn-crewai-baseline.md](kairn-crewai-baseline.md).

### Step 1: Reverse dependency counts (quick win)

*Addresses: Finding 6*

Add reverse dependency counts to the data layer. This is the most novel metric from the audit — no other tool provides "how many AI projects depend on this?" — and it requires no new infrastructure, just a query on the existing `package_deps` table.

```sql
SELECT dep_name, count(DISTINCT repo_id) as dependents
FROM package_deps GROUP BY dep_name
```

Add to an MV or lightweight view. Surface on server detail pages as "Used by X tracked AI projects." This can ship immediately and improves the core product regardless of kairn.

### Step 2: Unified quality score (architectural foundation)

*Addresses: Finding 7, Finding 5*

Build `mv_unified_quality` — a single quality score computed identically for all 220K+ repos, regardless of domain. Same weights, same methodology. This replaces the 18 domain-specific MVs as the analytical backbone (the domain MVs stay for the directory browsing UI).

This is the prerequisite for everything analytical: cross-domain comparison, kairn fitness scoring, embedding-based alternatives. Without it, comparing a vector-db repo to a rag repo means mixing scores from different methodologies.

Also add:
- **Category rank** — window function over unified scores per subcategory
- **Velocity risk flag** — flag when commits_30d exceeds threshold (LiteLLM at 2,399/month is the reference data point)
- **Momentum direction** — classified from existing `mv_momentum`

Once this exists, the subcategory silo problem (Finding 5) is resolved: "top alternative" uses embedding similarity + unified score instead of subcategory peers.

### Step 3: AI dependency boundary decision + foundational repo ingestion

*Addresses: Finding 3, Finding 4*

Codify the three-tier classification for what counts as an AI dependency:
1. **AI-specific** — repos in PT-Edge's AI taxonomy. Full scoring.
2. **AI-adjacent** — provider SDKs, structural tools (pydantic, instructor), observability (opentelemetry). Full scoring once ingested.
3. **General infrastructure** — (click, httpx, tomli). Out of scope for scoring.

Then ingest the foundational repos that Finding 4 identified as missing. These are ~50-100 high-star, high-importance repos:
- LLM provider SDKs: `openai/openai-python`, `anthropics/anthropic-sdk-python`, `googleapis/python-genai`, `cohere-ai/cohere-python`, `mistralai/client-python`
- Structural: `pydantic/pydantic`, `jxnl/instructor`
- Protocol SDKs: `modelcontextprotocol/python-sdk`
- Observability: `open-telemetry/opentelemetry-python`
- Tokenisation: `openai/tiktoken`

Decision: whether these go into a new `foundations` domain or are distributed into existing domains. Finding 7 makes this less critical than it first appeared — domains are a browsing affordance, not an analytical primitive. The unified quality score (Step 2) means they'll be scored correctly regardless of domain assignment. But for browsing, a `foundations` domain likely makes more sense than scattering provider SDKs across llm-tools, agents, etc.

### Step 4: Package-to-repo mapping table

*Addresses: Finding 1, Finding 2*

Build `package_registry_map` with bidirectional validation:

```
package_name  | registry | github_repo                      | verified_at
--------------+----------+----------------------------------+------------
litellm       | pypi     | BerriAI/litellm                  | 2026-04-02
anthropic     | pypi     | anthropics/anthropic-sdk-python   | 2026-04-02
chromadb      | pypi     | chroma-core/chroma                | 2026-04-02
```

Populated from two directions:
1. **Direction A (PyPI/npm → GitHub):** Hit `https://pypi.org/pypi/{package}/json`, extract `project_urls.Repository`. This is the direction the audit endpoint needs.
2. **Direction B (GitHub → PyPI/npm):** For repos in `ai_repos`, check `pyproject.toml` or `package.json` for published package name.

Both directions run continuously. Agreement = verified. Disagreement = flagged. This also enables the dependency graph crawl: walk from any node, discover new repos and packages at each edge, expand coverage toward what developers actually use.

Depends on Step 3 (foundational repos must be ingested before they can be mapped).

### Step 5: Embedding-based alternatives

*Addresses: Finding 5, Finding 7*

Replace subcategory-peer alternatives with embedding-similarity alternatives. For any repo, "top alternative" = nearest neighbour by 1536d embedding that has a unified quality score above threshold, regardless of domain or subcategory.

This fixes the broken alternatives from the audit (chroma-go for Chroma, VectorDBBench for LanceDB) and also improves the directory's cross-category comparison feature.

Depends on Step 2 (needs unified scores) and the existing embedding infrastructure (already in place — 97% of repos have 1536d embeddings).

### Step 6: Server detail page enrichment

Add "Strategic Fitness" section to server detail pages:
- Category rank (from Step 2): "Ranked #3 of 47 in lightweight-tts-libraries"
- Momentum direction (from Step 2): "Rising — gained 1,200 stars in 30 days"
- Top alternative (from Step 5): "Category leader: edge-tts (69/100)" — now via embedding similarity
- Reverse dependency count (from Step 1): "Used by 155 tracked AI projects"
- Velocity risk flag (from Step 2): "High velocity — 2,399 commits/month"

Where it appears: repos with unified quality > 20 and at least 5 embedding-similar peers.

### Step 7: Audit API endpoint

`POST /api/v1/audit` — accept package names or raw `requirements.txt`, match via `package_registry_map` (Step 4), return strategic fitness data from unified MV (Step 2) with embedding-based alternatives (Step 5) and reverse dependency counts (Step 1).

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
  "category_rank": 1,
  "category_size": 34,
  "dependents": 155,
  "momentum": "accelerating",
  "velocity_risk": false,
  "lifecycle": "growth",
  "top_alternative": {"repo": "portkey-ai/gateway", "score": 72, "similarity": 0.91},
  "assessment": "category_leader"
}
```

**Free tier:** Quality score, lifecycle stage, category rank, dependents count.
**Paid tier:** Momentum, velocity risk, alternative recommendations, historical trends, batch audits.

### Step 8: Open-source scanner CLI (distribution layer)

A CLI tool (`kairn`) that reads `requirements.txt` / `pyproject.toml` / `package.json`, calls the audit endpoint (Step 7), renders a strategic dependency health report.

```bash
$ kairn scan requirements.txt
Scanning 47 dependencies... 23 matched PT-Edge AI records.

  litellm        98/100  #1 of 285  ↑ accelerating  155 dependents  ✓ leader
  chromadb       94/100  #1 of 27   → steady         126 dependents  ✓ leader
  lancedb        94/100  #1 of 36   → steady          30 dependents  ✓ leader
  tokenizers     90/100  #1 of 26   → steady         119 dependents  ✓ leader
  anthropic      --/100  (scoring)  → steady         229 dependents  — new
  openai         --/100  (scoring)  → steady         866 dependents  — new
  mem0ai         72/100  #6 of 977  → steady          15 dependents  ⚠ evaluate cognee
  ...

24 dependencies outside AI tooling scope (not scored).
```

Open source (MIT). Every scan is an API call. The scanner is the distribution channel; the data stays proprietary.

### Dependency chain summary

```
Step 1 (reverse deps)     — no dependencies, ship immediately
Step 2 (unified scoring)  — no dependencies, foundational
Step 3 (boundary + ingest) — benefits from Step 2 for scoring
Step 4 (package mapping)  — depends on Step 3 (repos must exist to map)
Step 5 (embedding alts)   — depends on Step 2 (needs unified scores)
Step 6 (detail pages)     — depends on Steps 1, 2, 5
Step 7 (audit API)        — depends on Steps 1, 2, 4, 5
Step 8 (CLI scanner)      — depends on Step 7
```

Steps 1 and 2 can run in parallel. Steps 3 and 5 can run in parallel (after Step 2). Steps 6 and 7 can run in parallel (after their deps). Step 8 is last.

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

### Finding 7: Domain assignment is a browsing affordance, not an analytical primitive

**Date:** 2026-04-02

**What happened:** cognee (`topoteretes/cognee`) is classified as domain `vector-db` but its subcategory is `agent-memory-systems`. When we ranked agent-memory repos, we pulled quality scores from `mv_rag_quality` (where mem0 lives) and `mv_vector_db_quality` (where cognee lives) — two different MVs with potentially different scoring methodologies. The ranking mixed scores that weren't computed the same way.

More broadly, the `agent-memory-systems` subcategory spans 5 domains (mcp: 358, embeddings: 219, vector-db: 146, rag: 132, agents: 122). The same functional category is split across domains because different projects approach agent memory from different architectural angles. This is correct from a browsing perspective but breaks cross-domain comparison.

**Root cause:** The 18 domains carry too much structural weight. Domain assignment determines which quality MV scores a repo, which repos it's compared against, and which deep dives link to it. But domains are fundamentally a *navigational convenience* — aisles in a shop for human browsing. They shouldn't determine which products get compared to each other.

**Resolution direction:** Decouple browsing from analytics:
- **Domains stay as the browsing layer.** They're good at this — Google indexes them, users understand them, the directory structure works. Don't remove them.
- **Add a unified quality score** (`mv_unified_quality`) computed identically for all 220K+ repos regardless of domain. Same weights, same methodology. This powers all analytical features: kairn fitness, top alternatives, cross-domain comparison.
- **Use embedding similarity for alternatives**, not subcategory peers. The 1536d embeddings already capture "this does agent memory" whether the repo is in vector-db or rag. Top alternative = nearest neighbour by embedding with quality above threshold, regardless of domain.
- **Domains don't impede analytical work.** They're a UI layer, not wired into anything that needs to be correct for comparison or scoring purposes.

**Impact on plan:** This is the most architecturally significant finding. It affects Step 2 (the MV needs unified scoring, not domain-specific), Step 3 (detail page "top alternative" uses embeddings), and Step 4 (the API returns domain-agnostic comparisons). It also affects the directory itself — cross-category comparison (flagged in the roadmap) has the same root cause.
