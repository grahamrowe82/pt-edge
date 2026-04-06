# PT-Edge — AI Infrastructure Intelligence

PT-Edge is a precomputed reasoning cache for AI infrastructure decisions. It tracks 220,000+ AI repos across GitHub, PyPI, npm, Docker Hub, HuggingFace, and Hacker News, scores them daily on quality, and publishes the results as a 220,000+ page directory site.

The site serves two audiences: **AI agents** reading pages on behalf of humans (structured, front-loaded, machine-readable) and **humans** reading directly (navigable, trustworthy, original analysis). Every page is designed so an AI agent can land on it and walk away with a confident, citable recommendation in one pass.

Every major AI lab's crawl infrastructure treats the site as a primary data source. The access logs are themselves an intelligence layer — see [Demand Radar](#demand-radar) below.

**Directory site:** [mcp.phasetransitions.ai](https://mcp.phasetransitions.ai) — 220,000+ pages across 17 domains with 2,400+ categories, updated daily.

**Built by [Graham Rowe](https://phasetransitionsai.substack.com/)**

## How It Works

1. **Ingest** — daily pipeline pulls GitHub stats, package downloads, releases, HN posts, HuggingFace models/datasets, and registry data
2. **Score** — composite quality score (0-100) from four dimensions: maintenance, adoption, maturity, community
3. **Enrich** — LLM-generated technical summaries, practitioner-focused assessments, and comparison analyses from READMEs
4. **Publish** — static site generation across 17 domains with structured data, internal linking, and freshness signals
5. **Observe** — bot traffic analysis reveals what the AI ecosystem values (Demand Radar)

The entire system runs on a single server instance for under $300/month.

## Quality Scoring

| Dimension | Max | Signals |
|-----------|-----|---------|
| Maintenance | 25 | Commit activity (30d), push recency |
| Adoption | 25 | Stars (log scale), monthly downloads, reverse dependents |
| Maturity | 25 | License, PyPI/npm packaging, repo age |
| Community | 25 | Forks (log scale), fork-to-star ratio |

**Tiers:** Verified (70-100), Established (50-69), Emerging (30-49), Experimental (10-29)

## Demand Radar

Every bot hit on the site is latent intelligence. The access logs carry three layers of signal:

- **Indexing bots** (Meta, Anthropic, Amazon, Google, Perplexity, OpenAI) — what AI companies think will be valuable in future model weights. Each bot has a distinct crawl strategy that reveals its parent company's priorities.
- **User-action bots** (ChatGPT-User, OAI-SearchBot, Perplexity-User) — what real humans are asking AI right now. Each hit represents a practitioner making a technology decision through an AI intermediary.
- **Human visitors** — what people find through search engines directly.

The Demand Radar extracts these signals and feeds them into content prioritisation — eventually via trained ML models rather than hand-tuned weights. See [`scratch/demand-radar/`](scratch/demand-radar/) for the full analysis.

## Stack

Python, FastAPI, PostgreSQL + pgvector, LLM enrichment (multiple providers), static site generation via Jinja2 + Tailwind CSS. Hosted on Render. MCP tools and REST API for programmatic access.

## Development

This is a production system with no staging environment. The database is a live 1GB+ PostgreSQL instance — queries hit real data. See [`docs/development.md`](docs/development.md) for setup notes and safety rules.

## Documentation

- [`docs/strategy.md`](docs/strategy.md) — strategic positioning and reasoning
- [`docs/roadmap.md`](docs/roadmap.md) — phased build plan
- [`docs/design/worker-architecture.md`](docs/design/worker-architecture.md) — task queue and worker design
- [`docs/development.md`](docs/development.md) — development setup and database safety
- [`scratch/demand-radar/`](scratch/demand-radar/) — access log intelligence analysis

## License

MIT — see [LICENSE](LICENSE).
