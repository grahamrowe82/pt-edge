# PT-Edge — AI Project Intelligence

PT-Edge is an MCP server that makes AI assistants less wrong about the current state of AI development. It tracks 300+ open-source AI projects across major labs, collecting real-time signals from GitHub, PyPI, npm, HuggingFace, Docker Hub, and Hacker News.

**Built by [Phase Transitions](https://phasetransitions.ai)** — a newsletter covering the engineering side of AI.

<a href="https://glama.ai/mcp/servers/grahamrowe82/pt-edge">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/grahamrowe82/pt-edge/badge" alt="PT-Edge MCP server" />
</a>

## What It Does

- **Daily ingests** pull GitHub stats, package downloads, releases, HN posts, V2EX discussions, and newsletter coverage
- **Materialized views** compute derived metrics: momentum, hype ratio, tiers, lifecycle stage
- **LLM-powered enrichment** — Claude Haiku summarises releases and newsletter topics; OpenAI embeds everything for semantic search
- **30+ MCP tools** let you query this data naturally in conversation
- **Community feedback system** — corrections, article pitches, and lab event tracking

## Available Tools

| Category | Tools |
|----------|-------|
| **Discovery** | `about`, `whats_new`, `trending`, `lifecycle_map`, `hype_landscape` |
| **Deep Dives** | `project_pulse`, `lab_pulse`, `hype_check` |
| **Comparison** | `compare`, `movers`, `related`, `market_map` |
| **Project Discovery** | `radar`, `scout`, `deep_dive`, `sniff_projects`, `accept_candidate`, `topic`, `hn_pulse` |
| **Community** | `submit_feedback`, `upvote_feedback`, `list_feedback`, `amend_feedback`, `propose_article`, `list_pitches`, `upvote_pitch`, `amend_pitch` |
| **Lab Intelligence** | `submit_lab_event`, `list_lab_events`, `lab_models` |
| **Methodology** | `explain` |
| **Power User** | `describe_schema`, `query`, `set_tier` |

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
- **Embeddings:** OpenAI text-embedding-3-large (1536 dimensions)
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