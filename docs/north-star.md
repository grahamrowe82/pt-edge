# North Star: The Discovery Engine

## Where We Are

PT-Edge has five discovery indexes, each following the same pattern: ingest → embed → search → reason.

| Index | Source | Coverage | Search tool |
|-------|--------|----------|-------------|
| AI repos | GitHub API + adaptive sharding | ~11K repos, growing to 100K | `find_ai_tool()` |
| MCP servers | Same index, domain filter | Subset of ai_repos with `mcp` topic | `find_mcp_server()` |
| Public APIs | APIs.guru catalog | ~2,500 REST APIs with OpenAPI specs | `find_public_api()` |
| HF Datasets | HuggingFace Hub API | ~42K datasets (>100 downloads) | `find_dataset()` |
| HF Models | HuggingFace Hub API | ~18K models (>1,000 downloads) | `find_model()` |

Each index uses 256d Matryoshka embeddings (text-embedding-3-large), HNSW indexes, and hybrid semantic+keyword search. Package download data from PyPI/npm enriches the repo index as a ranking signal.

Two capability upgrades sit on top of the indexes:
- **Spec-to-scaffold bridge** (PR #42) — `fetch_api_spec()` and `scaffold_api_client()` fetch live OpenAPI specs and generate working client code
- **Dependency graph** (PR #42) — `api_deps()` resolves package dependency trees from PyPI/npm for impact analysis

The pattern is proven. One engineer, one cron job, one Postgres instance. The question is: what else deserves an index?

## The Compound Query Vision

The real value isn't any single index — it's the cross-index query. Today a user asks Claude:

> "I need to build a Slack bot that monitors GitHub releases and posts summaries."

Claude could hit all three indexes in parallel:
- **Repos**: bot frameworks (slack-bolt, slackbot), GitHub webhook libraries
- **APIs**: Slack Web API spec, GitHub REST API spec
- **MCP servers**: notification tools, release monitoring

Then synthesize: "Here's a working architecture using slack-bolt (48K stars, 2.1M downloads/mo) with the Slack API (OpenAPI 3.0, spec URL here) and GitHub's release webhook. Here's the MCP server that already does release monitoring if you want to skip building it."

No single index produces that answer. The compound query does. Every new index multiplies the value of every existing one.

## Candidate Indexes

Ranked by signal quality × ingestion ease × builder value.

### Tier 1: High value, clean data, proven pattern

**~~Datasets (HuggingFace Hub)~~ — Shipped (PR #43)**
- 42K datasets indexed with >100 downloads filter
- Search: `find_dataset(query, task, language, min_downloads)`
- Hybrid semantic + keyword search with download-weighted ranking

**Docker Images (Docker Hub)**
- Source: Docker Hub API (`GET /v2/search/repositories`)
- Coverage: ~100K official + verified publisher images
- Why it matters: The deployment piece. "I built a FastAPI app, what's the best base image?" or "Is there a pre-built container for Ollama with CUDA?" Docker Hub already has pull counts (popularity signal) and verified publisher badges (trust signal).
- Embedding: image name + description + categories, 256d
- Search: `find_docker_image(query, category, official_only)`
- Effort: Moderate. Docker Hub search API is basic — may need to supplement with library/official catalog scraping.

**~~Model Cards (HuggingFace Hub)~~ — Shipped (PR #43)**
- 18K models indexed with >1,000 downloads filter
- Search: `find_model(query, task, library, min_downloads)`
- Shared ingestion framework with datasets via `hf_common.py`

### Tier 2: High value, moderate complexity

**Prompt Templates / System Prompts**
- Source: GitHub search for `system_prompt` / `PROMPT_TEMPLATE` files, awesome-prompts repos, LangChain Hub
- Coverage: Thousands of curated prompts across tasks
- Why it matters: "How should I prompt Claude for X?" is the meta-question. Having a searchable index of working prompts — extraction, classification, code review, summarization — turns Claude into a prompt engineer with a reference library.
- Embedding: prompt text (truncated) + description + task tags, 256d
- Search: `find_prompt(query, task, model_family)`
- Effort: Messy. No single clean API. Multiple sources, heterogeneous formats. Needs extraction logic.

**Code Snippets / Cookbook Recipes**
- Source: Official SDKs' `examples/` and `cookbook/` directories (anthropic-cookbook, openai-cookbook, langchain examples, etc.)
- Coverage: ~500-1,000 curated examples across major frameworks
- Why it matters: The gap between "I found a library" and "I have working code" is where most projects stall. A searchable index of tested, official examples — with the actual code — closes that gap.
- Embedding: example title + description + code summary, 256d
- Search: `find_example(query, framework, language)`
- Effort: Moderate. GitHub API to list files, fetch content, extract metadata from frontmatter or docstrings. Needs per-repo parsing rules.

### Tier 3: Speculative / research-grade

**arXiv Papers**
- Source: arXiv API (OAI-PMH) or Semantic Scholar API
- Coverage: ~50K AI/ML papers per year
- Why it matters: Leading indicator. Papers precede implementations by 3-12 months. "What architectures are being explored for long-context?" needs this.
- Effort: High. Abstracts are clean but the volume is large and relevance filtering is hard. Better as a curated subset (cs.AI, cs.CL, cs.LG) with citation count as ranking signal.

**Terraform / Infrastructure Modules**
- Source: Terraform Registry API
- Coverage: ~15K modules
- Why it matters: "Deploy this on AWS/GCP/Azure" is the last mile. But niche — only relevant for infrastructure-heavy builds.
- Effort: Low (clean API), but narrow audience.

**Browser Extensions / VS Code Extensions**
- Source: Chrome Web Store (scraping required), VS Code Marketplace API
- Coverage: ~5K AI-related extensions
- Why it matters: Tool-layer intelligence. "What VS Code extensions work with Claude?" is a consulting question.
- Effort: Chrome Web Store has no public API. VS Code Marketplace API exists but is undocumented. Fragile.

## The Spec-to-Scaffold Bridge (Shipped — PR #42)

APIs.guru gives us spec URLs for ~2,500 APIs. The bridge combines the APIs index with live spec fetching:

1. Search → `find_public_api("send SMS")` → Twilio
2. Fetch → `fetch_api_spec("twilio")` pulls the live OpenAPI spec
3. Generate → `scaffold_api_client("twilio", "python")` produces a working client

Two MCP tools: `fetch_api_spec()` fetches and caches specs in `spec_json`, `scaffold_api_client()` generates typed client code from the cached spec.

## Dependency Graph Intelligence (Shipped — PR #42)

The `package_deps` table stores dependency relationships for repos in `ai_repos`. The `api_deps()` MCP tool resolves full dependency trees from PyPI/npm registries.

Use cases now live:
- "What's the lightest framework for building MCP servers?" → compare total dependency weight
- "Which repos depend on langchain?" → reverse dependency lookup
- "If anthropic-sdk releases a breaking change, what breaks?" → impact analysis

## Implementation Principles

Everything built so far follows these rules. Future indexes should too.

1. **One GET, one table.** If the data source requires pagination gymnastics, OAuth flows, or scraping — it's probably not worth it yet. The best indexes come from clean public APIs with a single endpoint that returns the full catalog (APIs.guru) or a well-paginated list (GitHub, HuggingFace).

2. **Embed everything at 256d.** Matryoshka embeddings at 256d are the sweet spot for this corpus size. Cheaper to store, faster to index, and quality is indistinguishable from 1536d for top-5 retrieval on collections under 1M rows.

3. **Hybrid search always.** Pure semantic misses exact-name queries. Pure keyword misses conceptual queries. Every search tool does both and merges.

4. **Popularity signals where they exist.** Stars, downloads, pull counts, citations — any proxy for "people actually use this" gets incorporated into ranking. Where no signal exists (APIs.guru), pure semantic similarity is fine for small corpora.

5. **Weekly refresh is fine.** The AI ecosystem moves fast, but metadata moves slowly. A repo's star count doesn't change meaningfully in 24 hours. Weekly ingest, daily for HN/V2EX discourse.

6. **The ingest should be boring.** If building an ingestion pipeline feels exciting, it's probably too complex. The excitement should come from the queries, not the plumbing.

## Sequencing

Order that maximizes compound query value:

1. ~~**HuggingFace Datasets**~~ — done (PR #43, 42K datasets indexed)
2. ~~**HuggingFace Models**~~ — done (PR #43, 18K models indexed)
3. **Docker Images** — next up. Completes the deployment chain: code → deps → container → ship
4. **Code Snippets** — bridges "I found the tool" to "I have working code"
5. **Prompts** — the meta-layer for the meta-layer

The spec-to-scaffold bridge and dependency graph are capability upgrades, not new indexes. Both shipped in PR #42.

## What Success Looks Like

A single Claude session where someone says:

> "I need to build a sentiment analysis API that processes customer reviews in real time, containerized, deployed on AWS."

And Claude, querying PT-Edge, returns:

- **Model**: `distilbert-base-uncased-finetuned-sst-2-english` (HuggingFace, 5M downloads, 95% accuracy on SST-2)
- **Dataset**: `amazon_polarity` (HuggingFace, 4M reviews, English, ready for fine-tuning)
- **Framework**: `fastapi` + `transformers` (ai_repos, 78K stars, 12M downloads/mo)
- **API pattern**: Stripe-style REST with webhook callbacks (public_apis spec reference)
- **Container**: `python:3.12-slim` base + `nvidia/cuda:12.1` for GPU inference (Docker Hub)
- **Example**: anthropic-cookbook's "deploy ML model as API" recipe
- **MCP server**: existing sentiment-analysis MCP server for testing

Seven indexes, one answer, zero tab-switching. That's the north star.
