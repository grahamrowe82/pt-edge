# PT-Edge Master Plan

*7 April 2026*

**Implementation:** Coverage expansion is the first operational priority. See [discovery-expansion.md](discovery-expansion.md) for the phased plan to grow from 248K to 500K+ repos.

## What PT-Edge Is

PT-Edge is a structured index of open-source AI tools, MCP servers, and related infrastructure. It currently covers 226,000+ projects across 18 domains.

## The Thesis

The way people discover technology is changing. When someone needs to find, evaluate, or compare AI tools, they increasingly ask an AI assistant rather than searching Google. The assistant retrieves structured information from the web, synthesises an answer, and the user may never visit the source site.

This means the primary audience for a technology reference site is no longer humans browsing web pages. It is AI agents retrieving data to answer questions on behalf of humans. Today those agents are ChatGPT, Claude, Gemini, Perplexity, and Copilot. Tomorrow they will include millions of personal and enterprise agents built on orchestration frameworks, operating autonomously.

PT-Edge is built to be the canonical reference that these agents retrieve from. Not a site optimised for human visitors that also happens to get bot traffic. A structured knowledge base designed to serve AI agents, that also happens to be readable by humans.

## Where We Are

AI chatbots currently handle roughly 2-3% of search-like queries globally. Less than 1% of website traffic originates from AI referrals. Autonomous agents that browse, compare, and transact on behalf of users are in their infancy.

The growth rates are steep. AI referral traffic is growing 130-350% year-over-year. Agentic AI traffic grew nearly 8,000% in 2025, from a small base. ChatGPT's user base doubled in a single year to 900 million weekly active users. The number of AI queries that trigger web retrieval is expanding as search becomes more deeply integrated into every major platform.

PT-Edge is one week old. It receives approximately 2,000 live AI-agent queries per day — retrievals where a bot fetches content to answer a user's question in real time. It receives roughly 500,000 indexing bot hits per day from all major AI labs. Human visitors number 100-200 per day. The ratio of agent usage to visible human usage is approximately 100:1. Tool vendors have already begun contacting us to request inclusion.

## The Flywheel

**1. Comprehensive coverage attracts retrieval traffic.**

The wider the index, the more queries it can answer. Every new domain added — robotics, drug discovery, biomedical, developer tooling — expands the retrieval surface. The goal is to cover the full universe of open-source AI and adjacent infrastructure so that regardless of what an agent is looking for, PT-Edge has a structured answer.

**2. Retrieval traffic generates demand intelligence.**

Every retrieval is a signal. Which categories are agents asking about? Which tools are being compared? What's trending? Where are the gaps? Across thousands of daily retrievals, these signals aggregate into a real-time demand map of the AI ecosystem. This data is proprietary by construction — no one else can observe the retrieval patterns across the full ecosystem from a single vantage point.

**3. Demand intelligence improves the index.**

The signals indicate where coverage is thin, where comparisons are needed, and where new categories are emerging. The index improves where it matters most, which attracts more retrieval traffic, which generates richer signals. The site trains itself on its own usage data.

**4. The demand intelligence becomes a product.**

The aggregated, anonymised demand data is useful to tool developers tracking adoption, investors evaluating categories, enterprises making build-or-buy decisions, and AI platforms seeking ecosystem intelligence. A subset is surfaced freely on the site. The full feed is the commercial product.

## Structural Principles

**Coverage breadth is the moat.** An agent doing comprehensive research uses whichever source covers the most ground in a single sweep. Breadth is the hardest thing to replicate and the thing that makes every other layer work.

**Structural consistency is what agents need.** Every page follows the same schema, the same metadata format, the same comparison structure. Agents can parse any page without adapting to a new format. Predictability is a feature.

**Machine-readable first, human-readable second.** Clean structure, rich metadata, fast response times, no JavaScript-dependent content. Humans can read it. Agents are the primary design target.

**The MCP endpoint is the native agent interface.** As agents shift from HTML scraping to authenticated API and MCP connections, PT-Edge already has the infrastructure. The MCP server is the front door for agents. The website is the lobby for humans. Both channels query the same database — every new domain or repo is immediately available to MCP-connected agents without additional site generation.

**Capture everything, analyse later.** Every retrieval is logged — bot identity, page, timestamp, pattern. Historical demand data cannot be reconstructed after the fact. The archive starts now.

## Revenue Model

The site is one week old. The priority is coverage, retrieval volume, and demand signal accumulation. Revenue follows the data. The likely structure:

**Free public access** to the index and basic demand trends. This is the flywheel engine. Restricting it would reduce retrieval volume and therefore signal quality.

**Enhanced listings** for tool vendors — verified, enriched, maintained entries with retrieval analytics showing how agents are surfacing their project.

**API tiers** for programmatic access at scale.

**Demand intelligence subscriptions** for the full historical and real-time demand feed.

**Free academic tier** providing retrieval analytics to open-source research projects.

## What This Is Not

This is not an SEO play. We are not optimising for Google rankings or human click-through rates.

This is not an advertising platform. We do not alter results based on payment. Enhanced listings provide richer data, not preferential placement.

This is not a walled garden. The free tier is generous by design. Retrieval volume drives signal quality. Restricting access would degrade the product.

## The Bet

AI agents will become the primary mechanism through which technology information is discovered and evaluated. The structured, comprehensive reference that those agents already retrieve from will capture a disproportionate share of that retrieval traffic. We are building that reference now, while the market is 1-2% penetrated, and accumulating the demand signal data that requires time to compound.

---

*PT-Edge is built by [Phase Transitions AI](https://phasetransitions.ai). The index is live at [mcp.phasetransitions.ai](https://mcp.phasetransitions.ai).*
