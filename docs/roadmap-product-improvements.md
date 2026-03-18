# PT-Edge Product Roadmap

**Last revised:** 2026-03-18

PT-Edge detects phase transitions in the AI open-source ecosystem — shifts in adoption, tooling, and infrastructure that aren't yet visible in newsletters or social media. The value proposition is not "what's trending" but "what's actually being adopted by teams shipping AI products."

This roadmap is organized around that mission. We track what matters to expert builders, not spectators.

---

## What's shipped

Phases 1–3 from the original roadmap are complete. Summary for reference:

| Area | Items shipped | Key outcomes |
|------|-------------|--------------|
| **Data integrity** | Commits snapshot fix, contributor count fix, retention policy | Trustworthy baseline data |
| **Coverage** | VS Code Marketplace, Python deps, reverse-lookup, repo classification, commercial projects | Multi-platform adoption signals |
| **Data sources** | Academic papers, Reddit (stub), methodology docs | Citation tracking, transparency |
| **Velocity index** | `mv_velocity` MV, commit deltas, `/api/v1/velocity` endpoint, GraphQL commits for 2.7K ai_repos, candidate watchlist | Development pace classification, automated discovery of 1,000 high-potential repos |
| **Taxonomy** | 17 domains, MCP subcategories, content_type classification | Structured ecosystem view |
| **Project expansion** | 54 new curated projects promoted via velocity-driven discovery | Coverage of eval/observability, ML infra, edge deployment — previously invisible |

---

## The core problem with what we have now

Our signals are biased toward attention (stars, HN posts, newsletter mentions). These are lagging indicators that measure awareness, not adoption. A project can have 50K stars and zero production users. Another can have 3K stars and be a hard dependency in 200 production codebases.

**For expert builders evaluating tools, the questions are:**
- "Is this actually being adopted, or is it just starred?"
- "Is this replacing something I'm already using?"
- "Who's building on this — hobbyists or production teams?"
- "Is this a solo project or does it have a real contributor base forming?"

The roadmap below is designed to answer those questions.

---

## Phase 1: Adoption signals

These measure whether projects are being used, not just noticed. Highest priority — this is our core differentiator.

### 1.1 Dependency velocity tracking

**What it answers:** "Is this tool actually being adopted by other projects?"

**Problem:** We have `package_deps` (35K+ records) showing which repos depend on which packages, but it's a static snapshot. We can't tell if a tool is gaining or losing dependents over time.

**Solution:**
- Monthly snapshot of reverse-dependency counts per package: `dep_velocity` table with `(package_name, source, dependent_count, snapshot_date)`
- Compute `dep_30d_delta` — net new dependents in the last 30 days
- Expose via API: `/api/v1/dependencies/{package}/velocity`
- This is the closest proxy to a purchase signal in open source — when a team adds a dependency, they're committing to it

**Example insight:** "langfuse gained 40 new dependents this month while langsmith gained 5 — despite langsmith having 3x the stars"

**Effort:** Low (periodic query + new table, no new API calls)

---

### 1.2 Fork-to-star ratio tracking

**What it answers:** "Are people working with this code, or just bookmarking it?"

**Problem:** We track stars and forks separately but don't compute or trend the ratio. Forks indicate someone downloading the code to build with or on — a much stronger signal than starring.

**Solution:**
- Add `fork_star_ratio` to `mv_velocity` (trivial: `forks::numeric / NULLIF(stars, 0)`)
- Track ratio change over time via momentum deltas
- Flag projects where fork/star ratio is climbing (adoption accelerating) or falling (going spectator-ware)

**Example insight:** "Project X's fork/star ratio jumped from 0.03 to 0.08 in 30 days — builders are picking it up"

**Effort:** Low (MV change, no new data collection)

---

### 1.3 Cross-domain adoption mapping

**What it answers:** "Is this tool becoming a platform, or is it niche?"

**Problem:** When a library starts being depended on by projects across multiple domains (RAG, agents, eval, etc.), it's becoming foundational infrastructure. We have the data (`package_deps` + `ai_repos.domain`) but don't compute this.

**Solution:**
- For each tracked package, compute domain diversity of its dependents: how many distinct `ai_repos.domain` values appear in its reverse-dependency graph
- Surface packages with high domain diversity + growing dependent count — these are emerging platforms
- Expose as `domain_spread` metric on dependency endpoints

**Example insight:** "LanceDB is depended on by projects in 7 different domains — it's becoming infrastructure, not just a vector DB"

**Effort:** Low-Medium (query against existing data, new metric computation)

---

## Phase 2: Stack layer taxonomy

The current categorization doesn't serve builders. `category=tool` tells you nothing. `domain=llm-tools` is too broad. Builders think in terms of where things sit in the stack.

### 2.1 Introduce stack layer classification

**What it answers:** "Show me everything competing at my layer of the stack"

**Problem:** Our curated `projects` use form-factor categories (tool, library, framework) while `ai_repos` uses problem-domain labels (rag, agents, embeddings). Neither maps to how builders actually think about the stack. A builder choosing an inference engine doesn't care about chat UIs.

**Solution:** Add `stack_layer` to both `projects` and `ai_repos`:

| Layer | What lives here | Example projects |
|-------|----------------|-----------------|
| `model` | Training frameworks, architectures, fine-tuning | Megatron-LM, MS-Swift, MaxText |
| `inference` | Serving, compilation, edge deployment | ONNX Runtime, vLLM, TVM, Executorch, GGML |
| `orchestration` | Agent frameworks, workflow engines, chains | LangChain, CrewAI, Deer Flow, AG-UI |
| `data` | RAG, vector DBs, embeddings, document processing | LanceDB, Kreuzberg, Airweave, Onyx |
| `eval` | Testing, monitoring, prompt management, observability | Langfuse, Opik, Agenta, Langwatch, Kiln |
| `interface` | Chat UIs, IDE integrations, CLIs, API wrappers | big-AGI, Kilocode, Marimo, gptme |
| `infra` | Compute orchestration, deployment, MLOps | SkyPilot, Argo Workflows, Flower |

**Implementation:**
- Add `stack_layer` column to `projects` (migration)
- Classify existing ~440 projects (LLM-assisted with manual review for top 50)
- Backfill `ai_repos` using domain-to-layer mapping + heuristics
- Add `stack_layer` filter to all relevant API endpoints
- Expose via `/api/v1/velocity?layer=eval` etc.

**Effort:** Medium (schema change, classification, API updates)

---

### 2.2 Align project categories with ai_repos domains

**Problem:** `projects.category` and `ai_repos.domain` are independent taxonomies that can't be queried together. A buyer asking "what's happening in RAG?" gets fragmented results.

**Solution:**
- Add `domain` column to `projects`, populated from linked `ai_repos` record where available, manually set otherwise
- Deprecate `category` in API responses (keep in DB for backwards compat)
- Unified queries across curated projects and broader ai_repos index

**Effort:** Low (migration + backfill query)

---

## Phase 3: Technology transition detection

This is the most valuable and hardest signal — detecting when one tool is replacing another.

### 3.1 Dependency substitution tracking

**What it answers:** "Is tool Y replacing tool X in production codebases?"

**Problem:** Technology transitions happen when teams swap dependencies. We can detect this by diffing `package_deps` over time — if repos that depended on X now depend on Y, that's a substitution signal.

**Solution:**
- Monthly diff of `package_deps`: for each repo, detect added/removed dependencies
- Compute substitution pairs: packages frequently added in the same repos where another package was removed
- Surface as "migration signals" — e.g., "12 repos dropped `pinecone-client` and added `lancedb` this month"
- Requires storing `package_deps` history (currently overwritten on each ingest)

**Implementation notes:**
- Add `package_deps_history` table or snapshot mechanism
- Most valuable for the curated project set where we have dense dependency data
- False positive rate will be high initially — need co-occurrence filtering

**Effort:** High (new data model, diffing logic, careful analysis)

---

### 3.2 Lifecycle transition alerts

**What it answers:** "Which projects just changed trajectory?"

**Problem:** We compute `lifecycle_stage` daily and snapshot to `lifecycle_history`, but don't surface transitions. A project moving from `growing` → `established` or from `stable` → `fading` is a material signal.

**Solution:**
- Daily comparison of current `mv_lifecycle` against previous snapshot
- Generate alerts for stage transitions, especially:
  - `emerging` → `growing` (breakout)
  - `growing` → `established` (maturation)
  - `established` → `fading` (decline)
  - Any stage → `dormant` (abandonment)
- Expose via API: `/api/v1/transitions?days=30`
- Include in `/whats-new` response

**Effort:** Low (query against existing `lifecycle_history` table)

---

## Phase 4: Contributor and maintainer intelligence

These signals matter for teams making long-term bets on a tool.

### 4.1 Contributor trajectory tracking

**What it answers:** "Is a real community forming, or is this one person's project?"

**Problem:** A project going from 3 to 15 contributors in a month is fundamentally different from one that's always had 100. The former signals community traction; the latter is a large org's internal project. We only have point-in-time contributor counts.

**Solution:**
- Monthly contributor count snapshots (already in `github_snapshots` — just need to trend it)
- Compute `contributor_growth_rate` and `contributor_30d_delta`
- From GitHub's stats/contributors API (already used in fallback): compute `bus_factor` (minimum contributors for 50% of commits) and `top_contributor_pct`
- Add to `mv_velocity` or new `mv_contributor_health` MV

**Effort:** Medium (new API calls for bus_factor, MV changes)

---

### 4.2 Maintainer responsiveness

**What it answers:** "If I file a bug, will anyone respond?"

**Problem:** For teams evaluating tools, maintainer responsiveness matters as much as features. We don't track it.

**Solution:**
- Track for curated projects:
  - `median_issue_response_hours`: time to first maintainer comment
  - `issues_closed_30d`: volume of resolved issues
  - `open_issues_ratio`: open / total (staleness indicator)
- Monthly snapshots in `maintainer_health` table
- Use GitHub Issues API with `since` parameter for incremental fetching

**Effort:** Medium-High (API-intensive, needs maintainer vs community comment filtering)

---

## Phase 5: Ecosystem intelligence

Broader signals about the shape of the AI landscape.

### 5.1 Automated candidate promotion pipeline

**What it answers:** "What should we be tracking that we're not?"

**Current state:** The watchlist scorer identifies the top 1,000 interesting repos from `ai_repos` and upserts them into `project_candidates`. Promotion is manual.

**Next step:**
- Domain-weighted scoring: boost `eval`, `orchestration`, `data`, `infra` candidates by 1.3-1.5x (these are commercially relevant but socially quiet)
- Auto-promote when a candidate hits thresholds AND has been in the watchlist for 2+ weeks (stability filter)
- Weekly digest of top 20 candidates with scoring breakdown for manual review
- Track promotion accuracy over time — are auto-promoted projects actually getting used?

**Effort:** Low (scoring weight change, digest query)

---

### 5.2 China and non-English ecosystem coverage

**Problem:** China's AI open-source ecosystem is divergent and growing fast. PaddlePaddle, ModelScope, and many others operate in a parallel ecosystem we partially track but don't contextualize.

**Solution:**
- Add `region` classification to `ai_repos` (GitHub profile location + README language detection)
- Track Gitee mirrors for Chinese projects
- Activate V2EX tracking (table exists, ingest runs)
- Consider ModelScope as HuggingFace equivalent

**Effort:** High (language detection, new data sources, manual curation)

---

### 5.3 Qualitative project intelligence

**Problem:** Raw metrics say *what* is happening but not *why*. An AI-generated intelligence layer would bridge data and narrative.

**Solution:**
- LLM-generated 2-3 sentence project briefs grounded in metrics, README, and release notes
- Comparative positioning: "fastest-growing eval framework" / "losing ground to X in the RAG space"
- Regenerate monthly or on lifecycle stage changes
- Human review for top 50; automated for the long tail

**Effort:** High (LLM pipeline, quality assurance, ongoing cost)

---

## Deprioritized

These items from the original roadmap are deprioritized — either the effort/value ratio is wrong or the signal is less useful than originally thought.

| Item | Reason |
|------|--------|
| **Intra-day velocity / breakout detection** | Stars-per-hour is an attention signal, not an adoption signal. Contradicts the "below the radar" thesis. May revisit for alerting, but not a core metric. |
| **Reddit / Twitter social tracking** | Same issue — social signals measure awareness, not adoption. Reddit stub exists if needed, but dependency velocity is a better use of effort. |
| **MCP subcategory taxonomy** | Already partially done. Low priority relative to stack layer taxonomy which is more broadly useful. |

---

## Execution priority

Ordered by value-to-effort ratio for the "below the radar adoption" thesis:

1. **Dependency velocity** (1.1) — highest signal, lowest effort. Ship first.
2. **Lifecycle transitions** (3.2) — free from existing data, immediately useful.
3. **Fork-to-star ratio** (1.2) — trivial MV change, strong signal.
4. **Stack layer taxonomy** (2.1) — reshapes how everything is queried and understood.
5. **Cross-domain adoption** (1.3) — powerful signal, moderate effort.
6. **Domain alignment** (2.2) — unblocks unified queries.
7. **Contributor trajectory** (4.1) — partially available from existing snapshots.
8. **Candidate scoring weights** (5.1) — quick win for discovery quality.
9. **Dependency substitution** (3.1) — highest value, highest effort. Needs dep history first.
10. **Maintainer responsiveness** (4.2) — valuable but API-heavy.
11. **Qualitative intelligence** (5.3) — LLM pipeline, do last.
12. **China ecosystem** (5.2) — important but separate workstream.
