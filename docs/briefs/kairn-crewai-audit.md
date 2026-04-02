# crewAI Dependency Audit — Full Research

## Audit methodology

1. Extracted 47 direct dependencies from `package_deps` for `crewAIInc/crewAI`
2. Resolved PyPI package names to GitHub repos via PyPI JSON API (Direction A)
3. Matched resolved repos against `ai_repos` for quality scoring
4. Computed category rank, category size, top alternative, and reverse dependency counts

## Resolution results

| Category | Count |
|---|---|
| Total dependencies | 47 |
| Resolved to GitHub via PyPI | 30 |
| No GitHub URL in PyPI | 17 |
| Tracked in PT-Edge with quality score | 8 |
| Resolved but not tracked | 22 |

## The 8 scored AI dependencies

| Dependency | Repo | Score | Category Rank | Category Size | Commits/30d | Top Alternative |
|---|---|---|---|---|---|---|
| litellm | BerriAI/litellm | **98/100** | **#1** of 285 | llm-api-gateways | 2,399 | free-coding-models (79) |
| chromadb | chroma-core/chroma | **94/100** | **#1** of 27 | chroma-database-tools | 139 | chroma-go (52) |
| lancedb | lancedb/lancedb | **94/100** | **#1** of 36 | vector-db-benchmarking | 69 | VectorDBBench (64) |
| tokenizers | huggingface/tokenizers | **90/100** | **#1** of 26 | tokenizer-libraries | 28 | ginza-transformers (48) |
| qdrant-client | qdrant/qdrant-client | **86/100** | #2 of 51 | qdrant-vector-search | 6 | qdrant (94) — the server, not a competitor |
| json-repair | mangiucugna/json_repair | **75/100** | **#1** of 54 | llm-json-streaming | 18 | shiki-stream (56) |
| mem0ai | mem0ai/mem0 | **72/100** | **#6** of 977 | agent-memory-systems | 146 | cognee (90) |
| crewai itself | crewAIInc/crewAI | **97/100** | #1 of its category | crewai-multi-agent-systems | 145 | — |

## Reverse dependency exposure (ecosystem importance)

How many tracked AI repos depend on each package:

| Package | Dependent Repos | Tracked? |
|---|---|---|
| pydantic | **1,029** | NOT tracked |
| openai | **866** | NOT tracked |
| httpx | **579** | NOT tracked |
| mcp | **421** | NOT tracked |
| anthropic | **229** | NOT tracked |
| litellm | 155 | Tracked (98/100) |
| chromadb | 126 | Tracked (94/100) |
| tokenizers | 119 | Tracked (90/100) |
| qdrant-client | 84 | Tracked (86/100) |
| json-repair | 31 | Tracked (75/100) |
| lancedb | 30 | Tracked (94/100) |
| instructor | 21 | NOT tracked |
| mem0ai | 15 | Tracked (72/100) |

The five most depended-on packages in crewAI's stack are all untracked. pydantic alone is a dependency of 1,029 AI projects in our index.

## Delta from baseline — what the data reveals that general knowledge can't

### Surprise 1: crewAI's dependency quality is exceptionally high

The baseline said "crewAI uses well-known libraries, LiteLLM is a good choice." The data says something much stronger: **6 of 7 scored deps are #1 in their category.** litellm is #1 of 285. chroma is #1 of 27. lancedb is #1 of 36. tokenizers is #1 of 26. json_repair is #1 of 54. This isn't just "good choices" — it's best-in-class across the board. Someone made very deliberate decisions here.

### Surprise 2: mem0 is the weak link, and the alternative is much stronger

The baseline mentioned memory capabilities vaguely ("some vector store, maybe ChromaDB"). The data reveals mem0 is the only dependency that's *not* a category leader — it's **#6 of 977** in agent-memory-systems with a 72/100 score. The category leader is cognee (90/100, 13.2K stars). Three other alternatives score higher: OpenViking (83), Memori (83), and several others in the 63-68 range. If you're building on crewAI and using mem0 for memory, the data suggests evaluating cognee.

### Surprise 3: crewAI chose LanceDB, not Chroma, as its primary vector store

The baseline guessed "probably ChromaDB or FAISS." The data shows crewAI has *both* chromadb (core dep) and lancedb (core dep), plus qdrant-client (dev dep). But lancedb is the one in the core dependencies, not just dev. Both score 94/100 and are #1 in their respective subcategories, but they're in different subcategories — chroma in "chroma-database-tools" and lancedb in "vector-db-benchmarking." This subcategory classification is questionable (Finding 5 below) but the dependency choice is interesting: LanceDB is embedded/local-first, Chroma requires a server. crewAI chose the embedded option as default.

### Surprise 4: LiteLLM's development velocity is extraordinary

The baseline said "well-maintained." The data says 2,399 commits in the last 30 days — by far the highest of any dependency. That's ~80 commits per day. This is not "well-maintained," it's running at a pace that suggests rapid evolution. For a production dependency, extreme velocity is a double-edged sword: you get fast bug fixes but also frequent breaking changes. This is the kind of nuance a quality score alone doesn't capture.

### Surprise 5: The subcategory classification limits the usefulness of "top alternative"

The "top alternative" for chroma is chroma-go (a Go client for Chroma — not a real alternative). The "top alternative" for lancedb is VectorDBBench (a benchmarking tool — not a database). The "top alternative" for qdrant-client is qdrant itself (the server, not a client). These are subcategory classification artefacts, not genuine strategic alternatives.

For a kairn report to recommend real alternatives, it needs to compare across subcategories within a domain (all vector DBs, not just "chroma ecosystem" or "qdrant ecosystem"). This is the same cross-category comparison problem flagged in the roadmap for the directory itself.

### Surprise 6: json_repair is a hidden gem

The baseline didn't mention json_repair at all. It's a library for fixing broken JSON from LLM outputs — a practical problem every LLM application hits. It's #1 of 54 in llm-json-streaming at 75/100 with 4.6K stars. 31 tracked repos depend on it. It's exactly the kind of dependency that nobody discusses but that quietly solves a real problem. A kairn report should surface these — the "you probably don't know about this, but it's solid" findings.

## Process findings (updating kairn plan)

### Finding 5: Subcategory classification makes "top alternative" unreliable

The "top alternative" field requires comparing like-for-like within a subcategory. But the subcategory classifier creates narrow silos: "chroma-database-tools" (27 repos) vs "qdrant-vector-search" (51 repos) vs "vector-db-benchmarking" (36 repos). A real alternative to Chroma is Qdrant or LanceDB, not chroma-go.

For kairn to recommend genuine alternatives, it needs to compare at the domain level (all vector-db repos) or use embedding similarity to find functionally equivalent repos, not just subcategory peers.

### Finding 6: Reverse dependency count is the most novel metric

No existing tool provides "how many AI projects depend on this?" The fact that pydantic is depended on by 1,029 tracked AI repos, and litellm by 155, is strategic intelligence that doesn't exist anywhere else. This should be a headline metric in kairn reports — it tells you how systemically important a dependency is, not just how good it is individually.
