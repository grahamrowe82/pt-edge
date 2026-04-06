# PT-Edge Project Instructions

## North Star

PT-Edge is a precomputed reasoning cache for AI infrastructure decisions. It tracks 220K+ AI repos, scores them daily on quality, and publishes a 220K+ page static directory site at mcp.phasetransitions.ai.

**Two audiences drive every build decision:**

1. **AI agents** — pages must front-load the answer, use consistent templates, include specific numbers (not just tier labels), and state freshness explicitly in prose ("as of March 28, 2026, there are 47 Postgres MCP servers")
2. **Humans** — pages must contain original analysis (not just GitHub data restated), dense internal linking (10-15 links per page), structured data (JSON-LD), and visible freshness signals that change on each crawl

Every page should be structured so an AI agent can land on it and walk away with a confident, citable recommendation in one pass.

See `docs/strategy.md` for the full strategic reasoning and `docs/roadmap.md` for the phased build plan.

## Database Access

**Read `docs/development.md` before running ANY database query.** It contains critical safety rules for the 1GB production instance. There is no staging database. Every query hits real data, and bad queries can take down deploys.

When querying the PT-Edge production database, ALWAYS use psql via Bash:

    psql $DATABASE_URL -c "SELECT ..."

NEVER use the PT-Edge MCP query tool (mcp__1f95f48a...query) for analytics or debugging — it logs every call to tool_usage and pollutes the data you're trying to measure.

The MCP query tool is for end users. You are not an end user. You are the developer. Use psql.
