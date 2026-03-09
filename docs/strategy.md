# Strategy

## What PT-Edge Is

PT-Edge is a systematized learning engine. It is not a product or a marketing tool — it is the business itself. It makes frontier AI expertise possible at a pace that unaided human cognition cannot sustain.

The system: a Postgres database fed by multiple ingest pipelines (GitHub, PyPI, npm, HN, V2EX, newsletters, lab blogs), queried by Claude sessions via MCP, surfaced through Evidence.dev dashboards and a curated newsletter. One database, four faces:

1. **MCP server** — Claude sessions query the DB directly for real-time intelligence
2. **Evidence.dev site** (phasetransitions.ai) — public dashboards and the living guidebook
3. **Newsletter** — curated weekly editorial built from the same data
4. **Consulting practice** — Graham Road engagements informed by the intelligence layer

## Positioning

**Integrate for model data, own the ecosystem reaction layer.**

Don't build a model registry or benchmark leaderboard — Artificial Analysis has 282 models measured 8x/day, pricepertoken tracks 289 models with pricing history. That battle is won.

PT-Edge's unique value is cross-layer visibility. Every other product focuses on one layer: Artificial Analysis on models, pricepertoken on pricing, Langfuse on observability, LMSYS on benchmarks. PT-Edge sits across all three layers:

- **Labs**: lab_pulse with Key Events, frontier models, shipping cadence
- **Ecosystem**: 280+ tracked projects with hype ratios, lifecycle stages, download trends
- **Meta-layer**: community projects tracked alongside the tools they augment

The cross-layer queries are where the unique value lives. Nobody else can chain: "Anthropic shipped Import Memory -> topic('memory layer') shows Mem0 at 49K stars -> competitive collision detected -> claude-mem (33K stars) is the community's response."

### What to build vs integrate

| Capability | Build or Integrate | Rationale |
|---|---|---|
| Model registry/benchmarks | Integrate (Artificial Analysis) | Already solved, 282 models |
| Model pricing history | Integrate (pricepertoken) | Already solved, 289 models |
| Cross-lab shipping velocity | Build | Nobody tracks this as a time series |
| Ecosystem response time | Build | Data exists in PT-Edge, just needs the join |
| Competitive collision detection | Build | Semantic embeddings can detect this |
| Hype-vs-adoption for tools | Build | Star/download ratio is PT-Edge's signature metric |

## Competitive Landscape

What exists:
- **Artificial Analysis**: benchmark leader, 282 models, independently measured 8x/day, intelligence index, pricing, speed
- **pricepertoken.com**: 289 models with pricing history and weekly pricing newsletter
- **Epoch AI**: academic-grade benchmarks
- **reconnAI**: LLM changelogs for SEO/brand-visibility, not builders

What nobody has:
- Cross-lab product shipping velocity as a time series
- Ecosystem response time after lab events
- Hype-vs-adoption for tools (not models)
- Competitive collision detection between lab features and open-source projects

## Coverage Boundary

PT-Edge tracks "AI for AI" (tooling, infrastructure, frameworks, models) — not "AI for X" (domain applications). This is a deliberate scope choice that keeps the tool focused.

The exception is the "boring AI" layer: business platform intelligence (Xero, HubSpot, Salesforce etc.) is covered because the consulting practice serves SME clients who use these platforms. This coverage comes primarily through editorial newsletter feeds (Ethan Mollick, Ben Evans) rather than direct platform tracking.

## Endgame Vision

When all generic AI tooling is automated (one-click connectors, auto-schema, native cross-system synthesis), the only thing worth paying a consultant for is a bespoke learning engine — a system tuned to one business's specific data sources, decision patterns, and competitive context. PT-Edge is the prototype of this service offering: a learning engine built for the AI ecosystem itself.

---

*Sourced from feedback items #36, #37, #38, #41, #44, #53, #62, #66, #69, #70. Resolved from active feedback on 2026-03-09.*
