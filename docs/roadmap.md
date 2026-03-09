# Roadmap

## Business Platform Intelligence

A third entity type alongside labs and open-source projects: the proprietary SaaS platforms that SME clients actually use day-to-day. When a consulting client says "we use Xero and Monday.com," the consultant should already know what AI features exist, what's in beta, what MCP servers are available, and what's in the recent changelog.

### Proposed platforms (curated for SA SME consulting relevance)

| Tier | Platforms |
|---|---|
| Accounting | Xero, QuickBooks/Intuit, Sage |
| CRM | HubSpot, Salesforce |
| Project management | Monday.com, Asana, ClickUp |
| Workforce | Deputy, Gusto |
| Communication | Slack, Microsoft Teams |
| Productivity | Microsoft 365 (Copilot), Google Workspace (Gemini) |
| Commerce | Shopify |
| Payroll/HR (SA-specific) | PaySpace, SimplePay |

### Per-platform tracking

For each platform: (a) AI features currently available, (b) beta/preview features, (c) developer API and tools, (d) MCP servers (official and third-party), (e) recent changelog entries related to AI, (f) user/developer discourse.

### Signal sources

Primary (subscribe/ingest directly):
- Xero: developer.xero.com blog, changelog, AI toolkit page, Xero blog, media releases. Has official MCP server, OpenAI Agents SDK integration, LangChain examples, prompt library.
- QuickBooks/Intuit: product updates, developer blog, Intuit Assist announcements. Currently shipping 6+ AI agents.
- Sage: press releases, Sage Intacct release notes, developer resources. Copilot in 6 products, 40K UK customers.
- HubSpot: developers.hubspot.com/changelog, product updates blog, MCP server activity.
- Salesforce: developer blog, release notes, Agentforce announcements.
- Monday.com: developer changelog, API updates.
- Microsoft 365: developer.microsoft.com/blog (ships 10+ MCP servers), Copilot announcements.
- Google Workspace: workspace.google.com/blog, Gemini integration updates.
- Slack: api.slack.com/changelog.

Secondary (arrive via existing newsletter/podcast pipelines):
- Ethan Mollick, Latent Space, Simon Willison will naturally mention platform AI launches.
- The platforms' own product marketing emails.

### Integration

Same pipeline architecture. Developer blog/changelog RSS feeds use the same ingest pattern as lab blog monitoring. Each platform gets a Key Events log like labs do. MCP server availability tracked explicitly — this is the most actionable consulting data.

---

## Podcast-to-Insights Pipeline

Extend the newsletter ingest concept to high-signal podcasts, starting with YC's Light Cone.

Pipeline: (1) Monitor YouTube channel RSS for new episodes. (2) Pull transcript via YouTube auto-captions. (3) Run through LLM extraction — same topic/summary/sentiment/mentions pattern as newsletters. (4) Store as rows in a similar table, embed for semantic search.

Light Cone is a leading indicator — they discuss companies and patterns 2-4 weeks before they hit mainstream newsletter coverage.

---

## AI Adoption Gates

A significance model for scoring signals. Encode a structured map of 8 adoption gates that must open sequentially for AI to reach mainstream business use. Each gate maps to observable signals PT-Edge already tracks.

The gates create a framework for the living guidebook and the newsletter: instead of "here's what happened this week," the narrative becomes "here's what moved through the gates this week."

---

## Tool Layer Intelligence

PT-Edge needs Cursor, Claude Code, and Windsurf as first-class entities. These are the three most-used AI developer tools and PT-Edge currently has zero data on any of them (all closed-source). The workaround: track their shadow via the meta-ecosystem. Claude Code can't be measured directly, but its community extensions (273K+ stars) can.

---

## Vertical Domain Pages

Dedicated pages on phasetransitions.ai for each major business domain — AI in Accounting, AI in CRM, AI in Project Management. Each page pulls from the same database but filters to domain-relevant signals. These are the SEO-discoverable entry points for the consulting funnel.

---

## Distribution Channels

Three channels serving three user types:

1. **The site** (phasetransitions.ai) — vertical domain pages for browsing. SEO-discoverable.
2. **The newsletter** — curated weekly editorial for subscribers. Relationship-building.
3. **MCP access** — direct database queries for power users and Claude sessions. The self-maintaining channel.

---

*Sourced from feedback items #46, #58, #59, #60, #64, #65, #67, #68. Resolved from active feedback on 2026-03-09.*
