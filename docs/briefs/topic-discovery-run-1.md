# Topic Discovery Run 1 — April 3, 2026

## Methodology Used

Five-step nucleation pipeline run by hand:
1. **Nucleation scan** — `mv_nucleation_category` for `creation_without_buzz` subcategories
2. **Audience size filter** — `mv_ai_repo_ecosystem` for repo counts, downloads, star distribution
3. **Fragmentation score** — top project concentration, quality tier distribution
4. **Narrative gap confirmation** — `newsletter_mentions` coverage + HN debate ratios
5. **Editorial framing test** — "can I write 'Your ___' in the title?"

## What the nucleation scan surfaced

30 subcategories with `creation_without_buzz = true` and >= 2 new repos/7d. Top categories by creation velocity:
- perception/scraper (233 new/7d)
- mcp/regulatory-intelligence-mcp (109)
- perception/browser-automation (107)
- data-engineering/sql-query-adapters (101)
- agents/sovereign-edge-agents (100)

Many more in the 35-65 range, heavily concentrated in the `agents` domain.

## What got filtered out (and why)

| Candidate | Reason for dropping |
|-----------|-------------------|
| **perception/scraper** | Already covered in browser automation piece |
| **perception/browser-automation** | Already covered |
| **mcp/agent-memory-systems** | Already covered (amnesia piece) |
| **agents/agentic-workflow-skills** | Already covered (skills piece) |
| **data-engineering/sql-query-adapters** | Only 106 repos, 1 with 100+ stars, 0 downloads — too small |
| **agents/sovereign-edge-agents** | 110 repos, 0 with 100+ stars — no real traction |
| **ml-frameworks/customer-churn-prediction** | 308 repos but 0 downloads — ML homework, not real tools |
| **mcp/regulatory-intelligence-mcp** | 223 repos, 1 with 100+ stars, 0 downloads — niche |
| **rag/local-rag-frameworks** | llama_index is a 100x dominant leader (47K stars vs <600 for #2) — no confusion to resolve |
| **llm-tools/llm-api-gateways** | LiteLLM is a 3.5x dominant leader (38.9K stars, 95.8M downloads) — market decided |
| **agents/personal-ai-operating-systems** | 204 newsletter mentions across 7 feeds in 90 days — narrative already crystallised |
| **agents/claude-code-team-systems** | Overlaps with existing Claude Code piece; 0 downloads (GitHub-only) |

## Recommended Topics

### TIER 1 — Strongest nucleation signal

#### 1. LLM Evaluation ("You're shipping AI you can't measure")

**Signal profile:**
- 166 repos, 8 with 1K+ stars, 1.2M monthly downloads
- **Fragmented leadership:** RAGAS (12.9K stars, 1.2M downloads) leads but Giskard (5.2K), VLMEvalKit (3.9K), lmms-eval (3.9K) are all viable. No 10x leader.
- **Low newsletter coverage:** 5 mentions in 90 days across 3 feeds
- **HN debate ratio:** 0.45 (moderately contentious)
- **Universal pain:** Every team shipping AI products needs to measure quality. Nobody agrees on how.

**Why it matches the amnesia pattern:**
- High activity, low narrative crystallisation
- The problem is one developers feel personally ("my AI app is in production and I have no idea if it's getting better or worse")
- PT-Edge data can resolve the confusion: quality scores on competing tools, clear recommendations
- Large audience: anyone building with LLMs (not just agent developers)

**"You" framing options:**
- "You're shipping AI you can't measure"
- "Your AI product has no tests"
- "Your LLM evals are probably wrong"

---

#### 2. LLM Inference/Cost Optimization ("Your LLM inference costs too much")

**Signal profile:**
- 155 repos in `llm-inference-engines`, 22 with 1K+ stars, 35.8M monthly downloads
- Plus 88 repos in `model-compression-optimization` (7 with 1K+ stars, 741K downloads)
- **Actively contested:** vLLM (73K stars) vs SGLang (24.4K) is the main battle, but 10+ others have 5K+ stars: TensorZero (11.1K), nano-vllm (12.2K), Petals (10K), Xinference (9.1K)
- **HN debate ratio on ai-cost:** 0.71 (high contention)
- **Newsletter coverage:** 15 mentions on cost, but across a broad topic — no definitive "which inference engine" piece

**Why it works:**
- Cost is universal pain across ALL LLM users, not just agent developers
- The landscape genuinely shifts monthly (SGLang just overtook vLLM in downloads: 27.8M vs 7.7M)
- Developers face a real, urgent decision: self-host vs API, which engine, which quantization
- PT-Edge has daily tracking on all these tools

**"You" framing options:**
- "Your LLM inference costs too much and the fix keeps changing"
- "You're paying 10x for inference because nobody told you about these"
- "The inference engine you picked last month is already wrong"

---

### TIER 2 — Strong signal, narrower audience

#### 3. Rust Agent Frameworks ("The Rust rewrite is coming for your Python agents")

**Signal profile:**
- 262 repos, 2 with 1K+ stars, 20.6K monthly downloads
- **Highest HN debate ratio of any topic:** 0.95 (7 posts, 881 points, 440 comments)
- **Newsletter coverage:** 13 mentions across 4 feeds (moderate)
- **Explosive newcomer:** OpenFang — 14K stars in 5 weeks (born Feb 24, 2026), 287 commits/30d
- 37 new repos/7d with HN traction (only candidate with both creation AND buzz)

**Why it works:**
- "Rewrite it in Rust" is a meme with genuine substance in the AI space
- Performance/safety narrative resonates: agents running arbitrary code need memory safety
- Very contentious (0.95 debate ratio) = strong opinions, no consensus
- Narrower audience (Rust + AI) but highly engaged

**Risk:** 13 newsletter mentions means coverage is building. This window may be closing.

---

#### 4. Agent Runtime/Execution Gap ("Your agent orchestrator isn't an execution engine")

**Signal profile:**
- 258 repos in `agent-runtime-engines`, 7 with 1K+ stars, 2.2M downloads
- Agno (38.7K stars, 1.7M downloads) leads but not dominant: AgentScope (18K), iflytek/astron-agent (10.1K)
- Docker `compose-for-agents` (870 stars) represents a new paradigm
- 35 new repos/7d with `creation_without_buzz = true`

**Why it works:**
- Names a gap developers feel: "I set up LangChain/CrewAI but my agent can't actually DO anything in production"
- The distinction between orchestration (LangGraph) and runtime (Docker, E2B, Agno) is poorly articulated
- Multiple competing approaches with no consensus

**Risk:** Agno is fairly well-known. The "orchestration vs runtime" distinction may be too abstract for a Substack title.

---

## Signals That Proved Most Useful

1. **`creation_without_buzz` flag** — excellent starting point, but produces many false positives (lots of low-quality subcategories with high repo counts)
2. **Leader concentration** — checking if top project has 10x stars of #2 was the strongest single filter for "is there confusion to resolve?"
3. **Newsletter coverage count** — directly measures narrative crystallisation. 5 mentions = gap. 200 mentions = covered.
4. **HN debate ratio** (comments/points) — measures contentiousness. >0.5 = unresolved, <0.3 = consensus
5. **Monthly downloads** — essential for separating real tools from tutorials/homework

## Signals That Need Improvement

1. **Audience size estimation** — repo count is a weak proxy. Reverse dependency count would be better but the query is slow.
2. **False positive rate in nucleation scan** — many subcategories with high new_repos_7d are just poorly-classified tutorial repos or ML homework projects. The nucleation scan needs a quality floor.
3. **Newsletter topic matching** — ILIKE queries are noisy. The 204 "personal-ai-os" matches likely include false positives from "iOS" or "macOS". Embedding-based semantic search on newsletter_mentions would be more reliable.
4. **Cross-subcategory aggregation** — "inference cost" spans multiple subcategories (llm-inference-engines, model-compression-optimization, llm-inference-serving). The pipeline works per-subcategory but some of the best topics are cross-cutting themes.

## Next Steps

1. Write the eval piece first — strongest signal, largest audience, clearest gap
2. Write the inference cost piece second — cross-cuts multiple subcategories, universal pain
3. Monitor Rust agents — the window is closing as newsletter coverage builds
4. Consider automating Steps 1-4 as a weekly "topic scanner" that outputs a ranked shortlist
