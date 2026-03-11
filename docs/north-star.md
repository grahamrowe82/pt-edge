# North Star: The Discovery Engine

## Where We Are

PT-Edge has three discovery indexes, each following the same pattern: ingest → embed → search → reason.

| Index | Source | Coverage | Search tool |
|-------|--------|----------|-------------|
| AI repos | GitHub API + adaptive sharding | ~11K repos, growing to 100K | `find_ai_tool()` |
| MCP servers | Same index, domain filter | Subset of ai_repos with `mcp` topic | `find_mcp_server()` |
| Public APIs | APIs.guru catalog | ~2,500 REST APIs with OpenAPI specs | `find_public_api()` |

Each index uses 256d Matryoshka embeddings (text-embedding-3-large), HNSW indexes, and hybrid semantic+keyword search. Package download data from PyPI/npm enriches the repo index as a ranking signal.

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

**Datasets (HuggingFace Hub)**
- Source: HuggingFace Hub API (`GET /api/datasets`)
- Coverage: ~300K datasets, filterable by task, language, size
- Why it matters: "I need training data for X" is a question Claude gets constantly. The Hub API is clean, paginated, well-documented. Downloads are a ranking signal. Tags map to tasks (text-classification, translation, summarization).
- Embedding: dataset name + description + tags, 256d
- Search: `find_dataset(query, task, language, min_downloads)`
- Effort: Same as ai_repos. One API, one table, one embedding pass.

**Docker Images (Docker Hub)**
- Source: Docker Hub API (`GET /v2/search/repositories`)
- Coverage: ~100K official + verified publisher images
- Why it matters: The deployment piece. "I built a FastAPI app, what's the best base image?" or "Is there a pre-built container for Ollama with CUDA?" Docker Hub already has pull counts (popularity signal) and verified publisher badges (trust signal).
- Embedding: image name + description + categories, 256d
- Search: `find_docker_image(query, category, official_only)`
- Effort: Moderate. Docker Hub search API is basic — may need to supplement with library/official catalog scraping.

**Model Cards (HuggingFace Hub)**
- Source: HuggingFace Hub API (`GET /api/models`)
- Coverage: ~800K models, filterable by task, framework, library
- Why it matters: PT-Edge already tracks frontier models from OpenRouter, but the long tail of fine-tuned, quantized, and task-specific models lives on HuggingFace. "What's the best 7B model for code completion?" needs this data.
- Embedding: model name + description + tags + pipeline_tag, 256d
- Search: `find_model(query, task, framework, min_downloads)`
- Effort: Same as datasets. Same API, same pattern. Could share the ingestion framework.
- Caveat: 800K is a lot. May need to filter to models with >100 downloads initially, or shard by task.

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

## The Spec-to-Scaffold Bridge

The most exciting capability isn't another index — it's what happens when you combine the APIs index with live spec fetching.

APIs.guru gives us spec URLs for ~2,500 APIs. Each URL points to an OpenAPI/Swagger JSON or YAML file. If Claude can:

1. Search → find the right API (`find_public_api("send SMS")` → Twilio)
2. Fetch → pull the actual OpenAPI spec from the spec URL
3. Parse → extract endpoints, request/response schemas, auth requirements
4. Generate → produce a working client in the user's language

...then the tool goes from "here's a link" to "here's working code." The spec URL is already in the database. The bridge is just a `webfetch` + JSON parse + code generation step — no new ingest pipeline needed. It's a tool-layer capability, not a data-layer one.

## Dependency Graph Intelligence

Every repo in `ai_repos` has a `requirements.txt` or `package.json`. Every package in PyPI/npm has a dependency tree. If we index the dependency relationships:

- "What's the lightest framework for building MCP servers?" → compare total dependency weight
- "Which repos depend on langchain?" → reverse dependency lookup
- "If anthropic-sdk releases a breaking change, what breaks?" → impact analysis

This is a graph problem, not a vector search problem. It might warrant a different storage approach (adjacency list in Postgres, or a lightweight graph layer). But the data is already sitting in registries waiting to be crawled.

## Implementation Principles

Everything built so far follows these rules. Future indexes should too.

1. **One GET, one table.** If the data source requires pagination gymnastics, OAuth flows, or scraping — it's probably not worth it yet. The best indexes come from clean public APIs with a single endpoint that returns the full catalog (APIs.guru) or a well-paginated list (GitHub, HuggingFace).

2. **Embed everything at 256d.** Matryoshka embeddings at 256d are the sweet spot for this corpus size. Cheaper to store, faster to index, and quality is indistinguishable from 1536d for top-5 retrieval on collections under 1M rows.

3. **Hybrid search always.** Pure semantic misses exact-name queries. Pure keyword misses conceptual queries. Every search tool does both and merges.

4. **Popularity signals where they exist.** Stars, downloads, pull counts, citations — any proxy for "people actually use this" gets incorporated into ranking. Where no signal exists (APIs.guru), pure semantic similarity is fine for small corpora.

5. **Weekly refresh is fine.** The AI ecosystem moves fast, but metadata moves slowly. A repo's star count doesn't change meaningfully in 24 hours. Weekly ingest, daily for HN/V2EX discourse.

6. **The ingest should be boring.** If building an ingestion pipeline feels exciting, it's probably too complex. The excitement should come from the queries, not the plumbing.

## Sequencing

If building these, the order that maximizes compound query value:

1. **HuggingFace Datasets** — highest builder value, cleanest API, completes the "data" leg
2. **HuggingFace Models** — same API, same pattern, adjacent table, covers the long-tail model question
3. **Docker Images** — completes the deployment chain: code → deps → container → ship
4. **Code Snippets** — bridges "I found the tool" to "I have working code"
5. **Prompts** — the meta-layer for the meta-layer

The spec-to-scaffold bridge and dependency graph are capability upgrades to existing indexes, not new ones. They can happen any time.

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
