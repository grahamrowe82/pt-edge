# PT-Edge Product Roadmap

**Last revised:** 2026-03-18

PT-Edge detects phase transitions in the AI open-source ecosystem — shifts in adoption, tooling, and infrastructure that aren't yet visible in newsletters or social media. The value proposition is not "what's trending" but "what's actually being adopted by teams shipping AI products."

This roadmap is organized around that mission. We track what matters to expert builders, not spectators.

---

## What's shipped

All original phases are complete. The system now tracks 440 curated projects, 166K+ ai_repos, 55K+ dependency edges, 1,500+ project candidates, and 38 hand-curated briefings. A B2B data API with key-based auth and usage tracking is live.

| Area | Items shipped | Key outcomes |
|------|-------------|--------------|
| **Data integrity** | Commits snapshot fix, contributor count fix, retention policy | Trustworthy baseline data |
| **Coverage** | VS Code Marketplace, Docker Hub, npm MCP, Python deps, reverse-lookup, repo classification, commercial projects, HuggingFace datasets + models | Multi-platform adoption signals across 6 registries |
| **Data sources** | Academic papers (Semantic Scholar), Reddit (stub), methodology docs, V2EX (Chinese tech forum) | Citation tracking, transparency, non-English signals |
| **Velocity index** | `mv_velocity` MV, commit deltas, `/api/v1/velocity` endpoint, GraphQL commits for 2.7K ai_repos, candidate watchlist with domain-weighted scoring | Development pace classification, automated discovery of 1,500+ high-potential repos |
| **Taxonomy** | 17 domains, MCP subcategories, content_type classification, 7-layer stack taxonomy | Structured ecosystem view queryable by layer and domain |
| **Project expansion** | 54 new curated projects promoted via velocity-driven discovery | Coverage of eval/observability, ML infra, edge deployment |
| **Adoption signals** | Dependency velocity snapshots (`dep_velocity_snapshots`), fork-to-star ratio in `mv_velocity`, cross-domain adoption (`domain_spread` on dependency endpoints) | Adoption-over-attention measurement — the core differentiator |
| **Stack layer taxonomy** | `stack_layer` column on projects, LLM-assisted classification of 440 projects, `stack_layer` filter on all API endpoints | Builders can query by where tools sit in the stack |
| **Domain alignment** | `domain` column on projects, backfilled from linked ai_repos, unified queries | Single taxonomy across curated projects and ai_repos index |
| **Lifecycle transitions** | `lifecycle_history` table, `/api/v1/transitions` endpoint, transitions included in `/whats-new` | Stage changes surfaced automatically (growing->established, stable->fading) |
| **Contributor trajectory** | `contributors_30d_delta` in `mv_momentum` and `mv_project_summary`, `/api/v1/contributors/trending` endpoint | Community formation signals — who's attracting new contributors |
| **Candidate scoring** | Domain-weighted scoring (eval, orchestration, data, infra boosted), velocity-driven watchlist refresh, 1,500+ candidates tracked | Systematic discovery of commercially relevant projects |
| **Qualitative intelligence** | `project_briefs` and `domain_briefs` tables, Haiku 4.5 LLM generation with staleness detection via `generation_hash`, evidence validation, 3 new API endpoints, integrated into `project_pulse()` MCP output | Automated narrative layer grounded in real metrics (~$0.42 backfill, ~$1/month ongoing) |
| **B2B data API** | API key auth, per-key usage tracking, usage analytics views, 20+ REST endpoints | Revenue-ready API for AI consultancies and tool companies |

---

## The core problem with what we have now

The attention-vs-adoption problem from the original roadmap is largely solved — we now have dependency velocity, fork-to-star ratios, cross-domain adoption, and contributor trajectory as adoption signals.

**The remaining gaps are:**
- "Is this replacing something I'm already using?" — we can't yet detect tool substitutions
- "Will this project be maintained?" — we don't track maintainer responsiveness
- "What's happening in China's AI ecosystem?" — partial coverage only (V2EX runs, some Chinese labs tracked, but no systematic region classification)

---

## What's next

### 1. Dependency substitution tracking

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

**Value:** Highest remaining signal — this is the "what's actually shifting" detection that no one else provides.

---

### 2. Maintainer responsiveness

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

### 3. China and non-English ecosystem coverage

**Current state:** V2EX ingest runs daily, Chinese labs (DeepSeek, Alibaba, etc.) are tracked, V2EX posts are linked to labs. But no systematic region classification of the 166K ai_repos.

**Remaining work:**
- Add `region` classification to `ai_repos` (GitHub profile location + README language detection)
- Track Gitee mirrors for Chinese projects
- Consider ModelScope as HuggingFace equivalent

**Effort:** High (language detection, new data sources, manual curation)

---

### 4. Candidate auto-promotion

**Current state:** Domain-weighted scoring is in place and 1,500+ candidates are tracked. Promotion to curated projects is manual.

**Remaining work:**
- Auto-promote when a candidate hits thresholds AND has been in the watchlist for 2+ weeks (stability filter)
- Weekly digest of top 20 candidates with scoring breakdown for manual review
- Track promotion accuracy over time — are auto-promoted projects actually getting used?

**Effort:** Low (query logic, digest formatting)

---

### 5. Contributor health deepening

**Current state:** `contributors_30d_delta` tracks community growth. No bus factor or top-contributor concentration.

**Remaining work:**
- From GitHub's stats/contributors API: compute `bus_factor` (minimum contributors for 50% of commits) and `top_contributor_pct`
- Add to `mv_velocity` or new `mv_contributor_health` MV

**Effort:** Medium (new API calls, MV changes)

---

## Deprioritized

| Item | Reason |
|------|--------|
| **Intra-day velocity / breakout detection** | Stars-per-hour is an attention signal, not an adoption signal. Contradicts the "below the radar" thesis. May revisit for alerting, but not a core metric. |
| **Reddit / Twitter social tracking** | Same issue — social signals measure awareness, not adoption. Reddit stub exists if needed, but dependency velocity is a better use of effort. |
| **MCP subcategory taxonomy** | Shipped. Low priority relative to stack layer taxonomy which proved more broadly useful. |

---

## Execution priority

Ordered by value-to-effort ratio for the remaining work:

1. **Candidate auto-promotion** (4) — lowest effort, immediate discovery quality improvement
2. **Dependency substitution** (1) — highest remaining value, highest effort. The killer signal.
3. **Contributor health deepening** (5) — moderate effort, enriches existing velocity data
4. **Maintainer responsiveness** (2) — valuable for tool evaluators, API-heavy
5. **China ecosystem** (3) — important but separate workstream, high effort
