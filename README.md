# PT-Edge — AI Project Intelligence

PT-Edge is an MCP server that gives AI assistants live, structured knowledge about the AI ecosystem. It indexes open-source projects, HuggingFace models and datasets, public APIs, and community discourse — then exposes 47 MCP tools, 3 resources, 3 resource templates, and 4 prompts for discovery, comparison, and trend analysis.

**Built by [Phase Transitions](https://phasetransitionsai.substack.com/)** — a weekly newsletter on building with AI, from architecture decisions to production patterns.

<a href="https://glama.ai/mcp/servers/grahamrowe82/pt-edge">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/grahamrowe82/pt-edge/badge" alt="PT-Edge MCP server" />
</a>

## What It Does

- **Daily ingests** pull GitHub stats, package downloads, releases, HN posts, V2EX discussions, newsletter coverage, HuggingFace models/datasets, public API specs, and npm registry MCP servers
- **Discovery indexes** — 11K+ AI repos, 18K+ HuggingFace models, 42K+ datasets, 2,500+ public APIs, all with 256d semantic embeddings, hybrid search, name-match boosting, staleness signals, and pagination
- **Materialized views** compute derived metrics: momentum, hype ratio, tiers, lifecycle stage
- **LLM-powered enrichment** — Claude Haiku summarises releases and newsletter topics; OpenAI embeds everything for semantic search
- **47 MCP tools** let you query this data naturally in conversation
- **MCP resources & prompts** — 3 static resources (methodology, categories, coverage), 3 parameterised resource templates (project, lab, category), and 4 compound query prompts (evaluate-technology, build-something, due-diligence, weekly-briefing)
- **Community feedback system** — corrections, article pitches, and lab event tracking

## Available Tools

| Category | Tools |
|----------|-------|
| **Discovery** | `about`, `whats_new`, `trending`, `lifecycle_map`, `hype_landscape` |
| **Deep Dives** | `project_pulse`, `lab_pulse`, `hype_check` |
| **Comparison** | `compare`, `movers`, `related`, `market_map` |
| **Project Discovery** | `radar`, `scout`, `deep_dive`, `sniff_projects`, `accept_candidate`, `topic`, `hn_pulse` |
| **AI Ecosystem Search** | `find_ai_tool`, `find_mcp_server`, `find_public_api`, `find_dataset`, `find_model` (all support `offset` for pagination) |
| **API Intelligence** | `get_api_spec`, `get_api_endpoints`, `get_dependencies`, `find_dependents` |
| **Community** | `submit_feedback`, `upvote_feedback`, `list_feedback`, `amend_feedback`, `propose_article`, `list_pitches`, `upvote_pitch`, `amend_pitch` |
| **Lab Intelligence** | `submit_lab_event`, `list_lab_events`, `lab_models` |
| **Methodology** | `explain` |
| **Power User** | `describe_schema`, `query`, `set_tier` |

### MCP Resources & Prompts

| Type | Items |
|------|-------|
| **Resources** | `methodology`, `categories`, `coverage` |
| **Resource Templates** | `project/{slug}`, `lab/{slug}`, `category/{category}` |
| **Prompts** | `evaluate-technology`, `build-something`, `due-diligence`, `weekly-briefing` |

## Key Concepts

- **Hype Ratio** — stars / monthly downloads. High = GitHub tourism. Low = invisible infrastructure.
- **Tiers** — T1 Foundational (>10M downloads), T2 Major (>100K), T3 Notable (>10K), T4 Emerging
- **Lifecycle** — emerging → launching → growing → established → fading → dormant
- **Momentum** — star and download deltas over 7-day and 30-day windows

## Connecting

PT-Edge uses the MCP Streamable HTTP transport. Connect via:

```
https://mcp.phasetransitions.ai/mcp?token=YOUR_TOKEN
```

Works with Claude Desktop, Claude.ai (web connector), and any MCP-compatible client.

## Stack

- **Runtime:** Python 3.11, FastAPI, FastMCP
- **Database:** PostgreSQL 16 with pgvector
- **Embeddings:** OpenAI text-embedding-3-large (256d Matryoshka for discovery indexes, 1536d for project/methodology)
- **LLM:** Claude Haiku 4.5 (release + newsletter summarisation)
- **Hosting:** Render (web service + cron + managed Postgres)

## Development

```bash
# Clone and set up
git clone https://github.com/grahamrowe82/pt-edge.git
cd pt-edge
cp .env.example .env  # Add your API keys

# Start database
docker compose up -d

# Run migrations
python -m app.migrations.run

# Start server
uvicorn app.main:app --reload

# Run daily ingest
python scripts/ingest_all.py
```

## License

MIT — see [LICENSE](LICENSE).