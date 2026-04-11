# ptedge-cli

Query the AI open-source ecosystem from your terminal. Search 220,000+ repos, run SQL, explore domains — powered by [PT-Edge](https://mcp.phasetransitions.ai).

## Install

```bash
pip install ptedge-cli
```

## Quick start

```bash
# What data is available?
ptedge status

# Browse the schema
ptedge tables
ptedge describe ai_repos

# Run a query
ptedge query "SELECT full_name, stars FROM ai_repos ORDER BY stars DESC LIMIT 10"

# Search by description
ptedge search "autonomous coding agent"
```

## Commands

| Command | Description |
|---------|-------------|
| `ptedge status` | Table count, repo count, domains, last sync |
| `ptedge tables` | List all database tables with row counts |
| `ptedge describe <table>` | Column names, types, nullability |
| `ptedge search-tables <keyword>` | Find tables by keyword |
| `ptedge query "<SQL>"` | Run a read-only SELECT query (5s timeout) |
| `ptedge workflows` | Pre-built SQL recipe templates |
| `ptedge search "<query>"` | Semantic search across 220K+ AI repos |
| `ptedge feedback "<topic>" "<text>"` | Submit feedback about the data |
| `ptedge login` | Store your API key |

## Authentication

Works without a key (100 requests/day). For higher limits:

```bash
# Store a key
ptedge login

# Or use an environment variable
export PTEDGE_API_KEY=pte_your_key_here

# Or pass per-command
ptedge --key pte_xxx query "SELECT ..."
```

Get a free API key (1,000/day) at [mcp.phasetransitions.ai/api/docs](https://mcp.phasetransitions.ai/api/docs).

## Output formats

```bash
# Default: aligned table
ptedge tables

# JSON (pipe to jq, use in scripts)
ptedge --format json query "SELECT domain, COUNT(*) FROM ai_repos GROUP BY domain"
```

## For AI agents

If you're an AI agent in Claude Code, Cursor, or similar:

```bash
ptedge --help                    # discover the interface
ptedge --format json status      # structured output
ptedge --format json query "..." # pipe-friendly
```

## Links

- **Site**: [mcp.phasetransitions.ai](https://mcp.phasetransitions.ai)
- **API docs**: [mcp.phasetransitions.ai/api/docs](https://mcp.phasetransitions.ai/api/docs)
- **MCP server**: [mcp.phasetransitions.ai/developers/mcp](https://mcp.phasetransitions.ai/developers/mcp)
- **Source**: [github.com/grahamrowe82/pt-edge](https://github.com/grahamrowe82/pt-edge)

## License

MIT
