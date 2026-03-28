# PT-Edge — AI Infrastructure Intelligence

PT-Edge tracks 220,000+ AI repos across GitHub, PyPI, npm, Docker Hub, and HuggingFace, scores them daily on quality, and publishes the results as a directory site and via MCP tools and REST API.

**Directory site:** [mcp.phasetransitions.ai](https://mcp.phasetransitions.ai) — 59,000+ pages across 9 domains, updated daily.

**Built by [Phase Transitions](https://phasetransitionsai.substack.com/)**

## Directory Domains

| Domain | Pages | Path |
|--------|-------|------|
| MCP Servers | 11,400 | `/` |
| AI Agents | 16,300 | `/agents/` |
| RAG Tools | 7,800 | `/rag/` |
| AI Coding Tools | 3,400 | `/ai-coding/` |
| Voice AI | 6,500 | `/voice-ai/` |
| Diffusion Models | 3,900 | `/diffusion/` |
| Vector Databases | 2,700 | `/vector-db/` |
| Embedding Tools | 3,700 | `/embeddings/` |
| Prompt Engineering | 3,600 | `/prompt-engineering/` |

Every project page includes a composite quality score (0-100) computed from four dimensions — maintenance, adoption, maturity, community — plus AI-generated technical summaries, live metrics paragraphs, risk flags, and structured data for search engines.

## How It Works

- **Daily ingest pipeline** pulls GitHub stats, package downloads, releases, HN posts, HuggingFace models/datasets, public API specs, and npm registry data
- **Quality scoring** via materialized views: composite 0-100 score from maintenance (commits, push recency), adoption (stars, downloads, reverse deps), maturity (license, packaging, age), and community (forks, fork/star ratio)
- **AI summaries** from READMEs via Claude Haiku — 2-3 sentences of technical depth beyond the GitHub description
- **Daily metric snapshots** for all 220K repos — stars, forks, downloads, commits tracked over time
- **Static site generation** via Jinja2 templates + Tailwind CSS, served from FastAPI alongside the MCP server and REST API
- **47 MCP tools** for programmatic access via Claude Desktop, Claude.ai, and any MCP client
- **REST API** with keyed access for B2B integrations

## Quality Scoring

| Dimension | Max | Signals |
|-----------|-----|---------|
| Maintenance | 25 | Commit activity (30d), push recency |
| Adoption | 25 | Stars (log scale), monthly downloads, reverse dependents |
| Maturity | 25 | License, PyPI/npm packaging, repo age |
| Community | 25 | Forks (log scale), fork-to-star ratio |

**Tiers:** Verified (70-100), Established (50-69), Emerging (30-49), Experimental (10-29)

## Stack

- **Runtime:** Python 3.11, FastAPI, FastMCP
- **Database:** PostgreSQL 16 with pgvector
- **Embeddings:** OpenAI text-embedding-3-large (256d)
- **LLM:** Claude Haiku 4.5 (summaries, classification, enrichment)
- **Site:** Jinja2 + Tailwind CSS (static, generated at startup)
- **Hosting:** Render (web service + cron + managed Postgres)

## Development

```bash
git clone https://github.com/grahamrowe82/pt-edge.git
cd pt-edge
cp .env.example .env  # Add your API keys
docker compose up -d  # Start database
alembic upgrade head  # Run migrations
uvicorn app.main:app --reload  # Start server
python scripts/ingest_all.py   # Run daily ingest
python scripts/generate_site.py --domain mcp --output-dir site  # Generate directory
```

## Documentation

- [`docs/strategy.md`](docs/strategy.md) — strategic positioning and reasoning
- [`docs/roadmap.md`](docs/roadmap.md) — phased build plan

## License

MIT — see [LICENSE](LICENSE).
