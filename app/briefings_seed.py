"""Seed the briefings table with curated ecosystem intelligence.

Run with: python -m app.briefings_seed

Each briefing is a distilled finding — one claim, its evidence, and its
interpretation. Not article dumps. The full articles live in publishing/.

Briefings are what users get when they call briefing('mcp-gateway-fragmentation')
instead of having to re-derive the conclusion from raw data.
"""
import json
from sqlalchemy import text
from app.db import engine

ENTRIES = [
    # -----------------------------------------------------------------------
    # MCP ECOSYSTEM — MACRO
    # -----------------------------------------------------------------------
    {
        "slug": "mcp-ecosystem-macro",
        "domain": "mcp",
        "title": "MCP ecosystem: 10,623 repos, 77M monthly downloads, 75% with <10 stars",
        "summary": (
            "Three quarters of MCP repos are experiments. The real infrastructure is in ~200 repos "
            "between 1K-30K stars. Platforms with 700K+ combined stars have adopted MCP. "
            "The protocol has crossed from 'Anthropic's protocol' to 'the industry's protocol.'"
        ),
        "detail": """## MCP Macro Picture

10,623 GitHub repos carry the 'mcp' topic as of March 2026. But the headline number is misleading.

**Star distribution:**
- 75.4% have <10 stars (experiments, tutorials, weekend projects)
- 0.4% have >10K stars — but ~35 of those 45 are large platforms (n8n, Dify, LobeHub) that tagged themselves 'mcp' after adding support
- The real MCP-native infrastructure has a ceiling around 23K stars (FastMCP) and drops fast

**The signal is in the middle:** ~200 repos between 1K-30K stars where MCP-native infrastructure is forming. This is where frameworks, gateways, security tools, and observability projects live.

**Downloads tell the real story:** 77.7M monthly downloads across 771 repos with package managers. FastMCP alone is 48.6M (62%). This is real production adoption, not GitHub tourism.

**Platform adoption is the lock-in signal:** n8n (178K stars), Dify (132K stars), Open WebUI (126K stars), LobeHub (73K stars), LocalAI (43K stars), LibreChat (34K stars), Composio (27K stars), Mastra (21K stars), Activepieces (21K stars) — combined 700K+ stars. When this many platforms adopt your protocol, it is not going away.""",
        "evidence": [
            {"type": "query", "sql": "SELECT COUNT(*) FROM ai_repos WHERE 'mcp' = ANY(topics)", "value": 10623, "as_of": "2026-03-14"},
            {"type": "stat", "label": "MCP repos with <10 stars", "value": "75.4%", "as_of": "2026-03-14"},
            {"type": "stat", "label": "Total MCP monthly downloads", "value": 77700000, "as_of": "2026-03-14"},
            {"type": "stat", "label": "MCP repos active in last 30d", "value": 5453, "as_of": "2026-03-14"},
        ],
        "source_article": "07-the-8-layers-of-the-mcp-ecosystem",
    },
    # -----------------------------------------------------------------------
    # MCP — TRANSPORT
    # -----------------------------------------------------------------------
    {
        "slug": "mcp-transport-settled",
        "domain": "mcp",
        "title": "Transport layer is thin and settled — mcp-proxy is the standard adapter",
        "summary": (
            "MCP uses JSON-RPC 2.0 over stdio (local) and HTTP/SSE (remote). The spec added "
            "streamable HTTP transport. mcp-proxy (2,338 stars, 208K dl/mo) is the dominant "
            "transport converter. The layer is thin by design — simplicity over performance."
        ),
        "detail": """## Transport Layer

The protocol chose JSON-RPC over gRPC, prioritising simplicity over performance. This has downstream consequences: easy to implement, hard to observe, and the ecosystem had to build its own auth/routing/multiplexing.

**mcp-proxy** (sparfenyuk, 2,338 stars, 208K downloads/month) is the standard tool for converting between stdio and SSE/streamable HTTP transports. It has been the dominant transport adapter for most of the protocol's lifetime.

The recent addition of streamable HTTP transport replaces the older SSE approach. The transport layer is mostly settled — the official MCP SDK handles it for most implementations.""",
        "evidence": [
            {"type": "project", "slug": "mcp-proxy", "metric": "stars", "value": 2338, "as_of": "2026-03-14"},
            {"type": "project", "slug": "mcp-proxy", "metric": "downloads_monthly", "value": 207899, "as_of": "2026-03-14"},
        ],
        "source_article": "07-the-8-layers-of-the-mcp-ecosystem",
    },
    # -----------------------------------------------------------------------
    # MCP — FRAMEWORKS
    # -----------------------------------------------------------------------
    {
        "slug": "mcp-framework-dominance",
        "domain": "mcp",
        "title": "FastMCP dominates the MCP framework layer with 62% of all downloads",
        "summary": (
            "FastMCP has 48.6M monthly downloads — 62% of all MCP-related package downloads. "
            "The next framework, fastapi_mcp (20.6M), serves a complementary role bridging existing "
            "FastAPI apps. Python owns the framework layer."
        ),
        "detail": """## FastMCP Dominance

FastMCP (23,593 stars, 48.6M downloads/month) is the React of MCP — the framework that most new servers are built on. Its decorator API makes shipping an MCP server trivial.

fastapi_mcp (11,644 stars, 20.6M downloads/month) complements rather than competes — it bridges existing FastAPI applications to MCP.

The framework layer is Python-dominant. TypeScript has the official SDK and strong server representation, but Python frameworks account for >90% of framework downloads.

**Alternative approaches worth watching:**
- hyper-mcp (870 stars, Rust) — WASM plugin model instead of Python decorators
- wassette (856 stars, Rust) — security-oriented WASM runtime for MCP

Two independent projects converging on WASM-based MCP is a signal. If security concerns drive adoption of sandboxed execution, WASM-based MCP could become the enterprise default.

**Bridge pattern:** langchain-mcp-adapters (3,411 stars) lets developers use MCP servers as LangChain tools and vice versa. MCP does not need to replace existing agent frameworks — it can plug into them.""",
        "evidence": [
            {"type": "project", "slug": "fastmcp", "metric": "downloads_monthly", "value": 48591647, "as_of": "2026-03-14"},
            {"type": "project", "slug": "fastmcp", "metric": "stars", "value": 23593, "as_of": "2026-03-14"},
            {"type": "project", "slug": "fastapi-mcp", "metric": "downloads_monthly", "value": 20646900, "as_of": "2026-03-14"},
            {"type": "stat", "label": "FastMCP share of MCP downloads", "value": "62%", "as_of": "2026-03-14"},
        ],
        "source_article": "07-the-8-layers-of-the-mcp-ecosystem",
    },
    # -----------------------------------------------------------------------
    # MCP — GATEWAYS
    # -----------------------------------------------------------------------
    {
        "slug": "mcp-gateway-fragmentation",
        "domain": "mcp",
        "title": "The MCP gateway layer is fragmented — 9+ competing projects, none over 4,100 stars",
        "summary": (
            "Gateway/routing is the most contested MCP layer. 9+ projects compete across "
            "aggregators (metamcp, mcphub), proxies (mcp-proxy, mcpo), routers (mcp-router), "
            "and multi-protocol gateways (mcp-context-forge). No FastMCP-style winner yet."
        ),
        "detail": """## Gateway Fragmentation

The gateway layer solves the "N servers" problem but has no dominant solution. This mirrors the period before nginx consolidated the reverse proxy space.

**Top projects by stars:**
- mcpo (4,041) — MCP-to-OpenAPI proxy, bridges existing API infrastructure
- mcp-context-forge (3,393) — multi-protocol gateway (MCP + A2A + REST)
- mcp-proxy (2,338, 208K dl/mo) — transport conversion, stdio↔SSE
- metamcp (2,100) — Docker aggregator with web UI
- mcphub (1,866) — Go-based hub with plugin system
- mcp-router (1,837) — request routing and load balancing

**Five competing approaches:**
1. Aggregators (metamcp, mcphub) — combine servers behind one endpoint
2. Proxies (mcp-proxy, mcpo) — transport conversion or protocol bridging
3. Routers (mcp-router) — route by tool name or capability
4. Multi-protocol gateways (mcp-context-forge) — unify MCP + A2A + REST
5. Managed platforms (aci.dev at 4,729 stars) — hosted tool-calling platforms

Most likely to produce a consolidation event in the next 6-12 months. Watch for mcphub (Go, plugins, growing fast) or a registry-first gateway (mcp-gateway-registry) to break away.""",
        "evidence": [
            {"type": "project", "slug": "mcpo", "metric": "stars", "value": 4041, "as_of": "2026-03-14"},
            {"type": "project", "slug": "mcp-context-forge", "metric": "stars", "value": 3393, "as_of": "2026-03-14"},
            {"type": "project", "slug": "metamcp", "metric": "stars", "value": 2100, "as_of": "2026-03-14"},
            {"type": "project", "slug": "mcphub", "metric": "stars", "value": 1866, "as_of": "2026-03-14"},
            {"type": "project", "slug": "mcp-router", "metric": "stars", "value": 1837, "as_of": "2026-03-14"},
        ],
        "source_article": "07-the-8-layers-of-the-mcp-ecosystem",
    },
    # -----------------------------------------------------------------------
    # MCP — SECURITY
    # -----------------------------------------------------------------------
    {
        "slug": "mcp-security-gap",
        "domain": "mcp",
        "title": "MCP security is being exploited faster than it's being built",
        "summary": (
            "Two production incidents in one month (Cline prompt injection, ClawHub malware at 11.9%). "
            "ToolHive (1,651 stars) provides container isolation. Auth tooling essentially non-existent — "
            "the most popular MCP OAuth server has 3 stars."
        ),
        "detail": """## Security Gap

The protocol has no built-in authentication, authorisation, or sandboxing. Everything is delegated to server implementations.

**Key projects:**
- AI-Infra-Guard (3,206 stars) — prompt injection and jailbreak detection
- ToolHive (1,651 stars, by Stacklok) — container-per-server isolation
- nono (980 stars) — kernel-enforced sandbox with cryptographic audit (Rust)
- awesome-mcp-security (663 stars) — curated resource list

**Real attacks are happening:**
- Cline prompt injection (March 2026) — cache poisoning compromised production release secrets
- ClawHub malware (March 2026) — 11.9% of marketplace skills stealing credentials and SSH keys

**Auth is the worst sub-gap:** The MCP spec added OAuth 2.1 support, but the most popular MCP OAuth server has 3 stars. The only secrets management tool (55 stars) hasn't been updated in 10 months. For comparison, web services had mature OAuth libraries within two years. MCP is 18 months in with essentially nothing.

The MSSS standard (67 stars) attempts to define baseline security properties. Early but important.""",
        "evidence": [
            {"type": "project", "slug": "AI-Infra-Guard", "metric": "stars", "value": 3206, "as_of": "2026-03-14"},
            {"type": "project", "slug": "ToolHive", "metric": "stars", "value": 1651, "as_of": "2026-03-14"},
            {"type": "stat", "label": "ClawHub malicious skills rate", "value": "11.9%", "as_of": "2026-03-14"},
            {"type": "stat", "label": "Top MCP OAuth server stars", "value": 3, "as_of": "2026-03-14"},
        ],
        "source_article": "07-the-8-layers-of-the-mcp-ecosystem",
    },
    # -----------------------------------------------------------------------
    # MCP — OBSERVABILITY
    # -----------------------------------------------------------------------
    {
        "slug": "mcp-observability-gap",
        "domain": "mcp",
        "title": "Observability is the biggest gap — after inspector, <300 stars combined",
        "summary": (
            "The official inspector (1,798 stars) is for development, not production. "
            "The OpenTelemetry integration has 3 stars and 24 downloads/month. "
            "No standard way to measure latency, error rates, or usage patterns."
        ),
        "detail": """## The Observability Gap

The thinnest layer in the entire MCP stack. Compare to web services where Prometheus, Grafana, Datadog, and OpenTelemetry provide comprehensive observability from day one.

**What exists:**
- inspector (1,798 stars) — official debugging tool, web UI. Essential for development, not production.
- mcp-reticle (116 stars) — JSON-RPC traffic interceptor (Rust)
- mcp-monitor (80 stars) — system metrics via MCP
- MCPtrace (64 stars) — distributed tracing attempt
- otel-mcp (3 stars, 24 dl/mo) — the OpenTelemetry integration

After inspector, the drop-off is dramatic. No standard metrics format. No distributed tracing. No error rate dashboards.

**Testing is equally barren:** mcp-jest and hoot both have 16 stars. Apify's tester-mcp-client (77 stars) tests client capabilities, not server behaviour. No protocol-level test framework exists.

These gaps feed each other: you cannot build confidence in a server you cannot observe, and you cannot test behaviour you cannot measure.""",
        "evidence": [
            {"type": "project", "slug": "inspector", "metric": "stars", "value": 1798, "as_of": "2026-03-14"},
            {"type": "project", "slug": "mcp-reticle", "metric": "stars", "value": 116, "as_of": "2026-03-14"},
            {"type": "stat", "label": "otel-mcp downloads/month", "value": 24, "as_of": "2026-03-14"},
            {"type": "stat", "label": "Top MCP test framework stars", "value": 16, "as_of": "2026-03-14"},
        ],
        "source_article": "07-the-8-layers-of-the-mcp-ecosystem",
    },
    # -----------------------------------------------------------------------
    # MCP — VENDOR INVESTMENT
    # -----------------------------------------------------------------------
    {
        "slug": "mcp-vendor-investment",
        "domain": "mcp",
        "title": "Google, AWS, GitHub, and Microsoft are all investing in MCP infrastructure",
        "summary": (
            "Google ships genai-toolbox (13.4K stars) plus 4 more MCP servers. AWS ships an official "
            "collection (8.4K stars, 112 commits/month). GitHub's MCP server has 27.8K stars. "
            "Microsoft maintains MCP docs (1.4K stars). The protocol has crossed the point of no return."
        ),
        "detail": """## Vendor Investment

When the three largest cloud platforms plus dozens of companies are all building on MCP, the protocol is locked in.

**Google** — the deepest investment:
- genai-toolbox (13,403 stars) — MCP Toolbox for Databases (Go)
- Google Workspace MCP (1,771 stars)
- Google Sheets MCP (731 stars, 13,727 dl/mo)
- Cloud Run MCP (556 stars)
- Google Ads MCP (125 stars)
- Also ships the A2A protocol (22.5K stars)

**AWS** — official MCP server collection (8,451 stars, 112 commits in the last month). Actively growing.

**GitHub** — official MCP server (27,776 stars). The most-starred MCP-native project.

**Microsoft** — official MCP documentation (1,434 stars).

**Platform companies building on MCP:**
- Composio (27,355 stars, 554 commits/month) — toolkit platform around MCP
- Mastra (21,938 stars, 891K dl/mo) — from the Gatsby team, uses MCP for tool integration""",
        "evidence": [
            {"type": "project", "slug": "genai-toolbox", "metric": "stars", "value": 13403, "as_of": "2026-03-14"},
            {"type": "project", "slug": "github-mcp-server", "metric": "stars", "value": 27776, "as_of": "2026-03-14"},
            {"type": "project", "slug": "mcp", "metric": "stars", "value": 8451, "as_of": "2026-03-14"},
        ],
        "source_article": "07-the-8-layers-of-the-mcp-ecosystem",
    },
    # -----------------------------------------------------------------------
    # MCP — DISCOVERY
    # -----------------------------------------------------------------------
    {
        "slug": "mcp-discovery-fragmented",
        "domain": "mcp",
        "title": "MCP discovery is split across curated lists, client registries, and early protocols",
        "summary": (
            "No standard discovery mechanism exists. Curated 'awesome' lists, client-embedded registries, "
            "package managers (mcpm.sh, 906 stars), and a protocol-level proposal (mcp-discovery, 81 stars) "
            "all compete. Each client maintains its own server list."
        ),
        "detail": """## Discovery Fragmentation

How does an AI client find the right MCP server? Four competing approaches:

1. **Curated registries** — Glama, Smithery, MCP.so, and 4+ competing 'awesome' lists on GitHub. Works but doesn't scale.

2. **Client-embedded discovery** — Cursor, LobeHub, and others build their own registries into the client. Standalone clients emerging: openmcp-client (736 stars), mcp-client-cli (669 stars). But a server in Cursor's marketplace isn't automatically available in Claude Desktop.

3. **Protocol-level discovery** — mcp-discovery (81 stars) proposes DNS-SD-like capability advertisement. Most interesting but least developed.

4. **Package management** — mcpm.sh (906 stars) is the closest to npm-for-MCP: CLI package manager and registry that works across platforms and clients.

The problem is harder than web APIs because MCP servers can be local processes, remote services, or containers, with different tools depending on configuration and different auth requirements.""",
        "evidence": [
            {"type": "project", "slug": "mcpm.sh", "metric": "stars", "value": 906, "as_of": "2026-03-14"},
            {"type": "project", "slug": "openmcp-client", "metric": "stars", "value": 736, "as_of": "2026-03-14"},
            {"type": "project", "slug": "mcp-client-cli", "metric": "stars", "value": 669, "as_of": "2026-03-14"},
            {"type": "project", "slug": "mcp-discovery", "metric": "stars", "value": 81, "as_of": "2026-03-14"},
        ],
        "source_article": "07-the-8-layers-of-the-mcp-ecosystem",
    },
    # -----------------------------------------------------------------------
    # MCP — A2A CONVERGENCE
    # -----------------------------------------------------------------------
    {
        "slug": "mcp-a2a-convergence",
        "domain": "mcp",
        "title": "A2A (22.5K stars) complements MCP — tools vs agents, converging at the gateway layer",
        "summary": (
            "MCP handles AI↔Tools. A2A handles Agent↔Agent. Google-originated, now under Linux Foundation, "
            "v1.0.0 shipped March 12, 2026. The convergence point is the gateway layer — "
            "projects handling both protocols will have an architectural advantage."
        ),
        "detail": """## MCP + A2A

Two complementary protocols, not competitors:
- **MCP**: AI ↔ Tools (how agents use external capabilities)
- **A2A**: Agent ↔ Agent (how agents talk to each other)

A2A (22,507 stars, v1.0.0, March 12, 2026) — originally Google, now Linux Foundation. Its own ecosystem is developing:
- adk-go (7,150 stars) — Agent Development Kit in Go
- a2a-python (1,729 stars) — official Python SDK
- archestra (3,548 stars) — agent orchestration
- solace-agent-mesh (2,256 stars) — event-driven agent mesh

**Convergence point:** The gateway layer. mcp-gateway-registry (481 stars) already supports both MCP and A2A. mcp-context-forge (3,393 stars) unifies MCP + A2A + REST behind one endpoint. This is likely the future: gateways that handle both tool calling and agent communication.""",
        "evidence": [
            {"type": "project", "slug": "a2a", "metric": "stars", "value": 22507, "as_of": "2026-03-14"},
            {"type": "project", "slug": "adk-go", "metric": "stars", "value": 7150, "as_of": "2026-03-14"},
            {"type": "project", "slug": "mcp-context-forge", "metric": "stars", "value": 3393, "as_of": "2026-03-14"},
        ],
        "source_article": "07-the-8-layers-of-the-mcp-ecosystem",
    },
    # -----------------------------------------------------------------------
    # MCP — SKILLS MARKETPLACE
    # -----------------------------------------------------------------------
    {
        "slug": "mcp-skills-marketplace",
        "domain": "mcp",
        "title": "The skills layer has 150K+ combined stars and concentrates security risk",
        "summary": (
            "Pre-packaged AI capabilities ('skills') sit on top of MCP. everything-claude-code (74K stars), "
            "awesome-claude-skills (43K stars), antigravity-awesome-skills (23K stars). Combined stars "
            "dwarf the infrastructure beneath them. Also where the ClawHub malware incident happened."
        ),
        "detail": """## Skills Marketplace

Sitting above MCP infrastructure is a rapidly growing layer of pre-packaged AI capabilities called 'skills.' Not MCP servers — higher-level abstractions that use MCP as their integration mechanism.

**Top projects:**
- everything-claude-code (74,013 stars) — agent harness performance system
- awesome-claude-skills (43,585 stars) — curated skills collection
- antigravity-awesome-skills (23,847 stars) — 1,000+ skills for Claude Code/Cursor
- Skill_Seekers (10,678 stars, 35K dl/mo) — converts docs/repos into skills

Combined star counts dwarf the MCP infrastructure beneath them. This is where end users interact with MCP, and also where security risks concentrate — the ClawHub malware incident (11.9% of skills malicious) happened exactly in this layer.""",
        "evidence": [
            {"type": "project", "slug": "everything-claude-code", "metric": "stars", "value": 74013, "as_of": "2026-03-14"},
            {"type": "project", "slug": "awesome-claude-skills", "metric": "stars", "value": 43585, "as_of": "2026-03-14"},
            {"type": "project", "slug": "antigravity-awesome-skills", "metric": "stars", "value": 23847, "as_of": "2026-03-14"},
        ],
        "source_article": "07-the-8-layers-of-the-mcp-ecosystem",
    },
    # -----------------------------------------------------------------------
    # MCP — AGENT MEMORY
    # -----------------------------------------------------------------------
    {
        "slug": "mcp-agent-memory",
        "domain": "mcp",
        "title": "Agent memory servers have 14K+ combined stars — AI remembering its own past",
        "summary": (
            "A category that barely existed six months ago. cipher (3,578 stars), SimpleMem (3,182), "
            "basic-memory (2,631), EverMemOS (2,570). Inverts the typical MCP pattern: instead of "
            "connecting AI to external tools, these connect AI to its own past."
        ),
        "detail": """## Agent Memory

MCP servers that give AI agents persistent memory across sessions — architecturally interesting because they invert the typical MCP pattern. Most servers connect AI to external tools. Memory servers connect AI to its own past.

**Top projects:**
- cipher (3,578 stars) — memory layer for coding agents, 11+ IDEs
- SimpleMem (3,182 stars) — lifelong memory for LLM agents
- basic-memory (2,631 stars) — conversations that remember
- EverMemOS (2,570 stars) — long-term memory across LLMs
- mcp-memory-service (1,504 stars) — knowledge graph + REST API

The interface is the same — tools, resources, prompts — but the purpose is internal rather than external. Growing fast because every agent developer encounters the same problem: AI forgets everything between sessions.""",
        "evidence": [
            {"type": "project", "slug": "cipher", "metric": "stars", "value": 3578, "as_of": "2026-03-14"},
            {"type": "project", "slug": "SimpleMem", "metric": "stars", "value": 3182, "as_of": "2026-03-14"},
            {"type": "project", "slug": "basic-memory", "metric": "stars", "value": 2631, "as_of": "2026-03-14"},
        ],
        "source_article": "07-the-8-layers-of-the-mcp-ecosystem",
    },
    # -----------------------------------------------------------------------
    # MCP — LANGUAGE DISTRIBUTION
    # -----------------------------------------------------------------------
    {
        "slug": "mcp-language-distribution",
        "domain": "mcp",
        "title": "Python and TypeScript are co-primary MCP languages, Go is emerging third",
        "summary": (
            "Python leads on repo count (854 repos with 10+ stars). TypeScript leads on total stars "
            "(917K across 776 repos). They serve different roles: Python dominates frameworks and "
            "data servers, TypeScript dominates the SDK and browser-facing tools. Go is emerging "
            "for gateways and infrastructure."
        ),
        "detail": """## Language Distribution

Among MCP repos with 10+ stars:

| Language | Repos | Total Stars | Avg Stars | Max Stars |
|----------|-------|-------------|-----------|-----------|
| Python | 854 | 801K | 938 | 127K |
| TypeScript | 776 | 918K | 1,183 | 179K |
| JavaScript | 212 | 192K | 904 | 74K |
| Go | 179 | 174K | 973 | 44K |
| Rust | 122 | 34K | 280 | 14K |
| Java | 54 | 80K | 1,479 | 45K |
| C# | 44 | 21K | 473 | 7K |
| Swift | 15 | 6K | 427 | 4K |

Python and TypeScript serve different roles: Python dominates frameworks (FastMCP) and data-oriented servers. TypeScript dominates the official SDK, browser tools, and configuration tooling. Go is emerging as the third language, particularly for gateways (mcphub, genai-toolbox, centralmind/gateway) and infrastructure. Rust is used for security-oriented projects (hyper-mcp, wassette, nono) where sandboxing and performance matter.""",
        "evidence": [
            {"type": "stat", "label": "Python MCP repos (10+ stars)", "value": 854, "as_of": "2026-03-14"},
            {"type": "stat", "label": "TypeScript MCP repos (10+ stars)", "value": 776, "as_of": "2026-03-14"},
            {"type": "stat", "label": "Go MCP repos (10+ stars)", "value": 179, "as_of": "2026-03-14"},
            {"type": "stat", "label": "Rust MCP repos (10+ stars)", "value": 122, "as_of": "2026-03-14"},
        ],
        "source_article": "07-the-8-layers-of-the-mcp-ecosystem",
    },
    # -----------------------------------------------------------------------
    # MCP — BILLING PREDICTION
    # -----------------------------------------------------------------------
    {
        "slug": "mcp-billing-gap",
        "domain": "mcp",
        "title": "MCP billing and monetization: literally 0 stars — a billion-dollar gap",
        "summary": (
            "If MCP servers are going to be run as services, someone needs to solve metering and payment. "
            "Today this layer does not exist. No Stripe equivalent for MCP. The closest analogue is "
            "a2a-x402 (472 stars), which adds crypto payments to A2A. The gap is wide open."
        ),
        "detail": """## The Billing Gap

The MCP ecosystem has no billing or monetization infrastructure. Zero. The most popular MCP billing project has no stars.

This matters because it determines whether MCP servers can be commercially viable as standalone products. The REST API world has Stripe's billing infrastructure. The MCP world has nothing.

**Closest analogues:**
- a2a-x402 (472 stars) — adds cryptocurrency payments to the A2A protocol, reviving HTTP 402 "Payment Required" for agents
- No MCP-native billing, metering, or usage tracking for commercial server operators

If the cloud infrastructure analogy holds, this is a significant opportunity. Someone will build "Stripe for MCP" — usage metering, billing, and payment for tool calls. The question is whether it comes from the MCP community, an existing billing platform, or a gateway that adds monetization as a feature.""",
        "evidence": [
            {"type": "stat", "label": "Top MCP billing project stars", "value": 0, "as_of": "2026-03-14"},
            {"type": "project", "slug": "a2a-x402", "metric": "stars", "value": 472, "as_of": "2026-03-14"},
        ],
        "source_article": "07-the-8-layers-of-the-mcp-ecosystem",
    },
    # -----------------------------------------------------------------------
    # MCP — SERVER CONCENTRATION
    # -----------------------------------------------------------------------
    {
        "slug": "mcp-server-concentration",
        "domain": "mcp",
        "title": "MCP server downloads follow extreme concentration — top 7 servers have 95% of traffic",
        "summary": (
            "chrome-devtools-mcp (1.8M dl/mo), mongodb-mcp (571K), trigger.dev (557K) dominate. "
            "dbhub (58K dl/mo) is the universal database gateway pattern — one server for all databases. "
            "Major vendor servers (Google, AWS, GitHub) signal first-party commitment."
        ),
        "detail": """## Server Layer Concentration

The thickest layer with thousands of servers, but downloads are extremely concentrated:

| Server | Downloads/month | What it does |
|--------|----------------|--------------|
| chrome-devtools-mcp | 1,797,045 | Browser automation |
| mongodb-mcp-server | 571,038 | MongoDB access |
| trigger.dev | 556,905 | Background jobs |
| n8n-mcp | 184,166 | Workflow automation |
| mcp-use | 89,158 | MCP app framework |
| dbt-mcp | 70,826 | dbt data transformation |
| dbhub | 58,740 | Universal database gateway |

**dbhub** (2,287 stars) is architecturally significant — one server for all databases instead of separate Postgres, MySQL, MongoDB, SQLite servers. This consolidation-under-one-interface pattern repeats at higher layers.

The server layer is also where the most waste occurs — dozens of nearly identical Postgres MCP servers, each with minor variations. The higher layers (gateways, discovery) exist partly to manage this proliferation.""",
        "evidence": [
            {"type": "project", "slug": "chrome-devtools-mcp", "metric": "downloads_monthly", "value": 1797045, "as_of": "2026-03-14"},
            {"type": "project", "slug": "dbhub", "metric": "stars", "value": 2287, "as_of": "2026-03-14"},
            {"type": "project", "slug": "dbhub", "metric": "downloads_monthly", "value": 58740, "as_of": "2026-03-14"},
        ],
        "source_article": "07-the-8-layers-of-the-mcp-ecosystem",
    },
    # -----------------------------------------------------------------------
    # AGENTS — FRAMEWORK RACE
    # -----------------------------------------------------------------------
    {
        "slug": "agents-framework-race",
        "domain": "agents",
        "title": "crewAI (5.5M dl/mo) and browser-use (3.9M) lead the agent framework race — most contenders have zero downloads",
        "summary": (
            "The agent framework space has massive star inflation. Of the top 20 repos by stars, "
            "12 have zero monthly downloads. Only 9 repos across the entire domain exceed 100K dl/mo. "
            "crewAI and browser-use are the only frameworks with both high stars and high adoption."
        ),
        "detail": """## Agent Framework Race

The agents domain (15,132 repos, 2M total stars) is the most hype-inflated domain in the AI ecosystem. Stars are abundant, downloads are scarce.

**The real contenders (by downloads/month):**
- crewAI (45,936 stars, 5.5M dl/mo) — multi-agent orchestration, the LangChain of agents
- browser-use (80,598 stars, 3.9M dl/mo) — browser automation for AI agents
- E2B (11,263 stars, 2.7M dl/mo) — sandboxed code execution environments
- composio (27,355 stars, 523K dl/mo) — tool integration platform
- ag2 (4,256 stars, 557K dl/mo) — AutoGen successor, quiet but growing

**The hype layer (high stars, zero downloads):**
MetaGPT (65K stars), daytona (64K), agno (39K), deer-flow (30K), CopilotKit (29K) — these have massive GitHub attention but no package manager presence. They're either pre-release, self-hosted only, or solving problems people star but don't use.

**The signal:** Production agent adoption is narrower than the star counts suggest. The gap between 'interesting' and 'deployed' is wider in agents than any other domain.""",
        "evidence": [
            {"type": "project", "slug": "crewAI", "metric": "downloads_monthly", "value": 5498708, "as_of": "2026-03-14"},
            {"type": "project", "slug": "crewAI", "metric": "stars", "value": 45936, "as_of": "2026-03-14"},
            {"type": "project", "slug": "browser-use", "metric": "downloads_monthly", "value": 3883828, "as_of": "2026-03-14"},
            {"type": "project", "slug": "browser-use", "metric": "stars", "value": 80598, "as_of": "2026-03-14"},
            {"type": "project", "slug": "composio", "metric": "downloads_monthly", "value": 522750, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    # -----------------------------------------------------------------------
    # RAG — LANGCHAIN DOMINANCE
    # -----------------------------------------------------------------------
    {
        "slug": "rag-langchain-monopoly",
        "domain": "rag",
        "title": "LangChain has 223M downloads/month — 82% of all RAG domain downloads",
        "summary": (
            "The RAG ecosystem is effectively a LangChain monopoly by adoption. LangGraph (39M dl/mo) "
            "extends it. The next independent project, trafilatura (4.4M), does document extraction, "
            "not orchestration. Dify (133K stars) and Open WebUI (127K stars) have massive stars but "
            "zero tracked downloads — they're self-hosted platforms, not libraries."
        ),
        "detail": """## LangChain's RAG Monopoly

The RAG domain has 10,351 repos and 272M monthly downloads. But LangChain alone accounts for 223M (82%).

**The LangChain stack:**
- langchain (129,354 stars, 223M dl/mo) — the orchestration layer
- langgraph (26,286 stars, 39M dl/mo) — stateful agent graphs built on LangChain

Together: 262M dl/mo, 96% of domain downloads.

**Independent RAG tools with real adoption:**
- trafilatura (5,481 stars, 4.4M dl/mo) — web scraping/text extraction
- PaddleOCR (72,167 stars, 1.5M dl/mo) — document OCR
- bm25s (1,560 stars, 1.2M dl/mo) — fast BM25 search
- chonkie (3,829 stars, 482K dl/mo) — text chunking
- promptfoo (14,219 stars, 473K dl/mo) — evaluation framework

**The self-hosted giants (zero tracked downloads):**
Dify (132,613 stars), Open WebUI (126,989 stars), ragflow (74,911 stars), Flowise (50,686 stars) — these are deployed as applications, not installed as packages. Their real adoption is invisible to package manager metrics.

**Implication:** Anyone building RAG tooling is either extending LangChain or competing against it. There is no middle ground.""",
        "evidence": [
            {"type": "project", "slug": "langchain", "metric": "downloads_monthly", "value": 223185230, "as_of": "2026-03-14"},
            {"type": "project", "slug": "langchain", "metric": "stars", "value": 129354, "as_of": "2026-03-14"},
            {"type": "project", "slug": "langgraph", "metric": "downloads_monthly", "value": 39407938, "as_of": "2026-03-14"},
            {"type": "project", "slug": "dify", "metric": "stars", "value": 132613, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    # -----------------------------------------------------------------------
    # VECTOR DB — THE CLIENT LIBRARY PATTERN
    # -----------------------------------------------------------------------
    {
        "slug": "vector-db-client-dominance",
        "domain": "vector-db",
        "title": "Vector DB adoption is measured in client libraries — pymilvus (18M dl/mo) and qdrant-client (15M) dwarf the databases themselves",
        "summary": (
            "The vector DB repos themselves show zero downloads (they're deployed as services). "
            "Adoption signal comes from client libraries: pymilvus 18M, qdrant-client 15M, "
            "llama_index 10M. The actual race is Milvus vs Qdrant vs Chroma, and the client "
            "download numbers tell you who's winning."
        ),
        "detail": """## Vector DB: Follow the Clients

Vector databases are deployed as services, not installed as packages. So their GitHub repos show zero PyPI/npm downloads. The real adoption signal is in their client libraries.

**Client library downloads (monthly):**
- pymilvus (18.2M) — Milvus Python client
- qdrant-client (15.0M) — Qdrant Python client
- llama_index (10.0M) — not a DB, but the dominant integration layer
- genkit (942K) — Google's AI toolkit with vector DB integrations
- deeplake (218K) — Activeloop's deep learning data lake
- FlashRank (216K) — lightweight reranker

**Stars vs adoption disconnect:**
- meilisearch (56K stars, 0 dl) — full-text search, not vector-first
- anything-llm (56K stars, 0 dl) — self-hosted RAG platform
- milvus (43K stars, 0 dl) — but pymilvus has 18M dl/mo
- qdrant (30K stars, 0 dl) — but qdrant-client has 15M dl/mo
- chroma (27K stars, 0 dl) — rewritten in Rust, client tracking unclear

**The takeaway:** Milvus leads on raw client adoption. Qdrant is close behind and growing. The race is tighter than star counts suggest.""",
        "evidence": [
            {"type": "project", "slug": "pymilvus", "metric": "downloads_monthly", "value": 18151557, "as_of": "2026-03-14"},
            {"type": "project", "slug": "qdrant-client", "metric": "downloads_monthly", "value": 14966287, "as_of": "2026-03-14"},
            {"type": "project", "slug": "llama_index", "metric": "downloads_monthly", "value": 9983619, "as_of": "2026-03-14"},
            {"type": "project", "slug": "milvus", "metric": "stars", "value": 43332, "as_of": "2026-03-14"},
            {"type": "project", "slug": "qdrant", "metric": "stars", "value": 29544, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    # -----------------------------------------------------------------------
    # LLM TOOLS — THE MIDDLEWARE STACK
    # -----------------------------------------------------------------------
    {
        "slug": "llm-tools-middleware-stack",
        "domain": "llm-tools",
        "title": "Transformers (112M dl/mo) and litellm (94M) are the load-bearing middleware of the AI stack",
        "summary": (
            "The LLM tools domain has the highest total downloads (436M/mo) across 31K repos. "
            "Two projects carry the stack: HuggingFace transformers (112M) and litellm (94M). "
            "Together they account for 47% of domain downloads. The next tier — pydantic-ai (15M), "
            "openai-agents (17M) — shows where new middleware is solidifying."
        ),
        "detail": """## LLM Middleware Stack

The llm-tools domain (31,873 repos, 436M monthly downloads) is the plumbing layer of the AI ecosystem. These are the libraries that sit between models and applications.

**Tier 1 — load-bearing infrastructure (>50M dl/mo):**
- transformers (157,811 stars, 112M dl/mo) — the universal model interface
- litellm (38,910 stars, 94M dl/mo) — universal LLM API proxy (100+ providers)
- datasets (21,273 stars, 61M dl/mo) — HuggingFace data loading
- ray (41,767 stars, 59M dl/mo) — distributed compute

**Tier 2 — solidifying middleware (5-40M dl/mo):**
- ai (22,583 stars, 37M dl/mo) — Vercel AI SDK (TypeScript)
- openai-agents-python (19,951 stars, 17M dl/mo) — OpenAI's agent framework
- json_repair (4,585 stars, 15M dl/mo) — fix malformed LLM JSON output
- pydantic-ai (15,437 stars, 15M dl/mo) — type-safe AI agents

**Tier 3 — emerging (1-5M dl/mo):**
- langchain-mcp-adapters (3,411 stars, 5.3M dl/mo) — MCP↔LangChain bridge
- bitsandbytes (8,033 stars, 5.3M dl/mo) — model quantization
- markitdown (90,677 stars, 2.9M dl/mo) — document-to-markdown conversion

**The pattern:** Tier 1 is settled infrastructure. Tier 2 is where the action is — pydantic-ai and openai-agents are competing to be the next standard agent framework. json_repair at 15M dl/mo shows how much production AI work is just cleaning up LLM output.""",
        "evidence": [
            {"type": "project", "slug": "transformers", "metric": "downloads_monthly", "value": 112431126, "as_of": "2026-03-14"},
            {"type": "project", "slug": "litellm", "metric": "downloads_monthly", "value": 93642606, "as_of": "2026-03-14"},
            {"type": "project", "slug": "pydantic-ai", "metric": "downloads_monthly", "value": 14915046, "as_of": "2026-03-14"},
            {"type": "project", "slug": "openai-agents-python", "metric": "downloads_monthly", "value": 16742955, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    # -----------------------------------------------------------------------
    # CROSS-DOMAIN — HYPE VS ADOPTION
    # -----------------------------------------------------------------------
    {
        "slug": "cross-domain-hype-gap",
        "domain": "agents",
        "title": "20 repos with 20K+ stars have zero downloads — the AI hype-adoption gap is wider than any other tech sector",
        "summary": (
            "AutoGPT (182K stars, 0 dl), Ollama (165K, 0 dl), stable-diffusion-webui (162K, 0 dl), "
            "Dify (133K, 0 dl), Open WebUI (127K, 0 dl). Some are self-hosted (invisible adoption). "
            "Others are genuinely all hype. The AI ecosystem's star-to-download ratio is the worst "
            "in open source history."
        ),
        "detail": """## The AI Hype-Adoption Gap

Across the AI ecosystem, 20 repos with >20K stars have literally zero tracked monthly downloads. This gap between attention (stars) and adoption (downloads) is unprecedented in open source.

**Three categories of zero-download repos:**

**1. Self-hosted applications (real users, invisible metrics):**
Ollama (165K stars), Dify (133K), Open WebUI (127K), stable-diffusion-webui (162K) — deployed as Docker containers or standalone apps. Millions of real users, but no PyPI/npm trace.

**2. Educational content (stars ≠ usage):**
generative-ai-for-beginners (108K stars), awesome-llm-apps (102K), LLMs-from-scratch (88K), ML-For-Beginners (84K) — these are learning resources starred by students. High stars, zero code adoption.

**3. Genuinely stalled projects:**
AutoGPT (182K stars) — peaked in early 2024, now largely inactive. prompts.chat (152K) — a prompt collection with no software to download.

**Why this matters:** Star counts are unreliable as an AI project health metric. The gap between stars and downloads is 10-100x larger in AI than in traditional open source (web frameworks, databases, DevOps tools). Any analysis based purely on star counts will systematically overweight hype and underweight adoption.""",
        "evidence": [
            {"type": "project", "slug": "AutoGPT", "metric": "stars", "value": 182435, "as_of": "2026-03-14"},
            {"type": "project", "slug": "ollama", "metric": "stars", "value": 164987, "as_of": "2026-03-14"},
            {"type": "project", "slug": "dify", "metric": "stars", "value": 132613, "as_of": "2026-03-14"},
            {"type": "stat", "label": "Repos with 20K+ stars and 0 downloads", "value": 20, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    # -----------------------------------------------------------------------
    # EMBEDDINGS — PRODUCTION INFRASTRUCTURE
    # -----------------------------------------------------------------------
    {
        "slug": "embeddings-production-stack",
        "domain": "embeddings",
        "title": "Embedding infrastructure is quietly massive — pytorch-metric-learning (3.7M dl/mo) and fastembed (2.9M) power the search layer",
        "summary": (
            "The embeddings domain gets less attention than agents or RAG but carries heavy production "
            "traffic. pytorch-metric-learning and fastembed together have 6.6M monthly downloads. "
            "FlagEmbedding (11K stars, 452K dl/mo) is Beijing's entry. The domain is Python-only."
        ),
        "detail": """## Embedding Infrastructure

The embeddings domain (4,880 repos, 11M monthly downloads) is quieter than agents or RAG but arguably more foundational — every vector search, every RAG pipeline, every semantic tool starts with an embedding.

**Production adoption leaders:**
- pytorch-metric-learning (6,312 stars, 3.7M dl/mo) — metric learning + embedding training
- fastembed (2,771 stars, 2.9M dl/mo) — Qdrant's fast embedding library
- mteb (3,159 stars, 1.5M dl/mo) — Massive Text Embedding Benchmark (from HuggingFace)
- Daft (5,301 stars, 568K dl/mo) — distributed DataFrame engine (Rust-backed Python)
- model2vec (2,008 stars, 511K dl/mo) — distilled static embeddings, 500x faster
- GPTCache (7,963 stars, 466K dl/mo) — semantic caching layer
- FlagEmbedding (11,395 stars, 452K dl/mo) — BAAI's embedding models (Beijing)

**Key patterns:**
1. **Python-only** — no TypeScript, no Go, no Rust frontends. Embedding work is deeply scientific Python.
2. **Research-to-production pipeline** — mteb benchmarks drive model selection, fastembed/model2vec provide fast inference, FlagEmbedding provides Chinese-language alternatives.
3. **Qdrant's ecosystem play** — fastembed (2.9M dl/mo) is published by Qdrant. They're building the full stack: embeddings → vector DB → client library.""",
        "evidence": [
            {"type": "project", "slug": "pytorch-metric-learning", "metric": "downloads_monthly", "value": 3724155, "as_of": "2026-03-14"},
            {"type": "project", "slug": "fastembed", "metric": "downloads_monthly", "value": 2867732, "as_of": "2026-03-14"},
            {"type": "project", "slug": "FlagEmbedding", "metric": "downloads_monthly", "value": 451945, "as_of": "2026-03-14"},
            {"type": "project", "slug": "FlagEmbedding", "metric": "stars", "value": 11395, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    # -----------------------------------------------------------------------
    # ML-FRAMEWORKS
    # -----------------------------------------------------------------------
    {
        "slug": "ml-frameworks-scikit-learn-dominance",
        "domain": "ml-frameworks",
        "title": "scikit-learn's 181M downloads/month dwarf deep learning frameworks — most production ML is still tabular",
        "summary": (
            "scikit-learn pulls 180.6M downloads/month vs TensorFlow's 21.6M and PyTorch Lightning's 10.8M. "
            "An 8:1 ratio that reveals the gap between AI media narratives and actual production workloads."
        ),
        "detail": """## The Invisible Majority

scikit-learn downloads 180.6M packages per month. TensorFlow manages 21.6M. PyTorch Lightning lands at 10.8M. That's an 8:1 ratio between classical ML and the most-hyped deep learning framework, and 17:1 against the PyTorch ecosystem's high-level wrapper.

This isn't a legacy tail. scikit-learn is at T1 Foundational tier with a "stable" lifecycle. It's the quiet engine room of production AI.

The gap tells a structural story: most real-world ML is tabular data — fraud detection, churn prediction, pricing models, recommendation features. These problems don't need transformers. They need gradient boosting, random forests, and logistic regression, all served by scikit-learn and its ecosystem (imbalanced-learn alone does 13.1M dl/mo).

The AI narrative fixates on foundation models, but the download ledger says production runs on `.fit()` and `.predict()`.""",
        "evidence": [
            {"type": "project", "slug": "scikit-learn", "metric": "downloads_monthly", "value": 180627438, "as_of": "2026-03-14"},
            {"type": "project", "slug": "tensorflow", "metric": "downloads_monthly", "value": 21576092, "as_of": "2026-03-14"},
            {"type": "project", "slug": "pytorch-lightning", "metric": "downloads_monthly", "value": 10810164, "as_of": "2026-03-14"},
            {"type": "project", "slug": "scikit-learn", "metric": "stars", "value": 65422, "as_of": "2026-03-14"},
            {"type": "project", "slug": "imbalanced-learn", "metric": "downloads_monthly", "value": 13088643, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    {
        "slug": "ml-frameworks-deep-learning-tiers",
        "domain": "ml-frameworks",
        "title": "TensorFlow+Keras (38.5M dl/mo) vs PyTorch Lightning (10.8M) — the framework wrapper pattern reveals adoption tiers",
        "summary": (
            "TensorFlow at 21.6M plus Keras at 16.9M yields 38.5M combined downloads/month, "
            "3.6x PyTorch Lightning's 10.8M. Deep learning has a clear two-tier structure in production usage."
        ),
        "detail": """## Two Tiers of Deep Learning

The deep learning framework race looks different through download counts than through Twitter sentiment. TensorFlow pulls 21.6M downloads/month. Its high-level API Keras adds another 16.9M. Combined, the TensorFlow stack reaches 38.5M — 3.6x the 10.8M that PyTorch Lightning manages.

This contradicts the popular narrative that PyTorch has "won." In research papers and new model releases, PyTorch dominates. But in production CI/CD pipelines — the systems that generate download counts — TensorFlow's installed base is enormous and persistent. With 194K GitHub stars (the most of any AI project tracked), its gravitational pull on enterprise ML infrastructure is hard to reverse.

The wrapper pattern itself is telling. Keras exists because TensorFlow's raw API is too complex for most practitioners. PyTorch Lightning exists for the same reason over PyTorch. Both wrappers confirm that deep learning frameworks are infrastructure, not interfaces — and most teams need an abstraction layer to use them productively.

But zoom out further: the entire deep learning download total (38.5M + 10.8M = 49.3M) is barely a quarter of scikit-learn's 180.6M. Deep learning is the loudest quarter of the ML market, not the largest.""",
        "evidence": [
            {"type": "project", "slug": "tensorflow", "metric": "downloads_monthly", "value": 21576092, "as_of": "2026-03-14"},
            {"type": "project", "slug": "keras", "metric": "downloads_monthly", "value": 16918062, "as_of": "2026-03-14"},
            {"type": "project", "slug": "pytorch-lightning", "metric": "downloads_monthly", "value": 10810164, "as_of": "2026-03-14"},
            {"type": "project", "slug": "tensorflow", "metric": "stars", "value": 194185, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    {
        "slug": "ml-frameworks-ui-layer-emergence",
        "domain": "ml-frameworks",
        "title": "Streamlit + Gradio hit 43.8M downloads/month — the ML UI layer is now bigger than the deep learning frameworks it serves",
        "summary": (
            "Streamlit (31.3M dl/mo) and Gradio (12.5M dl/mo) combine to 43.8M — exceeding TensorFlow+Keras (38.5M). "
            "The demo-ification of ML has created a UI layer larger than the modeling layer beneath it."
        ),
        "detail": """## The UI Layer Ate the Stack

Streamlit downloads 31.3M packages per month. Gradio adds 12.5M. Together, the two dominant ML UI frameworks reach 43.8M downloads/month — more than TensorFlow and Keras combined (38.5M), and more than four times PyTorch Lightning (10.8M).

This inversion is significant. The presentation layer of ML now outweighs the computation layer in deployment frequency. Streamlit has become the de facto way to turn a Python script into a shareable app. Gradio owns the model-demo niche — especially inside the HuggingFace ecosystem where Spaces runs on Gradio by default.

Add Weights & Biases (wandb) at 22.9M dl/mo and Ultralytics at 7.5M, and the broader "ML experience" layer — UIs, experiment tracking, and application wrappers — sums to 74.2M dl/mo. That's the real infrastructure investment: not training models, but making them accessible.

The pattern mirrors web development history. Frameworks like React didn't just serve backend APIs; they became the product surface. Streamlit and Gradio are doing the same for ML: turning models into applications, and shifting the center of gravity from `model.fit()` to `st.write()`.""",
        "evidence": [
            {"type": "project", "slug": "streamlit", "metric": "downloads_monthly", "value": 31254880, "as_of": "2026-03-14"},
            {"type": "project", "slug": "gradio", "metric": "downloads_monthly", "value": 12526189, "as_of": "2026-03-14"},
            {"type": "project", "slug": "wandb", "metric": "downloads_monthly", "value": 22850828, "as_of": "2026-03-14"},
            {"type": "project", "slug": "ultralytics", "metric": "downloads_monthly", "value": 7492604, "as_of": "2026-03-14"},
            {"type": "project", "slug": "tensorflow", "metric": "downloads_monthly", "value": 21576092, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    # -----------------------------------------------------------------------
    # TRANSFORMERS
    # -----------------------------------------------------------------------
    {
        "slug": "transformers-serving-race",
        "domain": "transformers",
        "title": "SGLang, PEFT, and vLLM each top 6M downloads/month — three layers of the LLM stack growing in lockstep",
        "summary": (
            "SGLang (9M dl/mo), PEFT (8.9M), and vLLM (6.4M) dominate transformer downloads — but they solve completely "
            "different problems. The serving stack is specializing, not consolidating."
        ),
        "detail": """## Three Layers, Three Winners

The top three transformers projects by monthly downloads aren't competing — they're stacking. SGLang (9.0M dl/mo, 24K stars) handles structured generation and high-performance serving. PEFT (8.9M dl/mo, 20.8K stars) provides parameter-efficient fine-tuning via LoRA and adapters. vLLM (6.4M dl/mo, 73K stars) delivers raw inference throughput.

Together they represent the maturation of the LLM deployment stack into distinct, composable layers. A team might use PEFT to create a LoRA adapter, serve it with vLLM for throughput, or route through SGLang for structured output guarantees.

What's notable is the download inversion: SGLang has the fewest stars (24K) but the most downloads (9M). vLLM has the most stars (73K) but the fewest downloads of the three (6.4M). SGLang's quiet adoption signals heavy CI/CD and infrastructure usage — exactly what you'd expect from a serving framework embedded in production pipelines.

All three projects are actively maintained with high commit velocity. This is infrastructure-grade development.""",
        "evidence": [
            {"type": "project", "slug": "sglang", "metric": "downloads_monthly", "value": 9003903, "as_of": "2026-03-14"},
            {"type": "project", "slug": "peft", "metric": "downloads_monthly", "value": 8917719, "as_of": "2026-03-14"},
            {"type": "project", "slug": "vllm", "metric": "downloads_monthly", "value": 6413855, "as_of": "2026-03-14"},
            {"type": "project", "slug": "sglang", "metric": "stars", "value": 24410, "as_of": "2026-03-14"},
            {"type": "project", "slug": "vllm", "metric": "stars", "value": 73007, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    {
        "slug": "transformers-local-inference-dominance",
        "domain": "transformers",
        "title": "6 of the top 10 transformers projects by stars have zero tracked downloads — local inference lives outside PyPI",
        "summary": (
            "Ollama leads transformers with 165K stars yet shows zero PyPI downloads. "
            "The local inference revolution runs on containers, not package managers."
        ),
        "detail": """## The Invisible Download Economy

Sort transformers projects by GitHub stars and a pattern emerges: 6 of the top 10 have zero tracked package downloads. Ollama (165K stars), LLMs-from-scratch (88K), LlamaFactory (68K), LocalAI (44K), and others — none register a single PyPI install.

But zero doesn't mean unused. Ollama alone pulls tens of millions of Docker images per month, making it one of the most-deployed AI projects in existence. It simply doesn't exist in the Python package index. LocalAI follows the same container-native pattern. LlamaFactory installs via git clone and pip from source.

This creates a measurement blind spot. Any analysis that equates "downloads" with "adoption" will systematically undercount the local inference ecosystem. The projects reshaping how developers run models on their own hardware are invisible to the metrics that matter most in traditional open-source tracking.

The hype ratio confirms it: Ollama's near-zero ratio (stars vs. tracked downloads) would normally signal a hype-driven project. Instead, it's one of the most practically adopted tools in AI — just distributed through Docker Hub, not PyPI.""",
        "evidence": [
            {"type": "project", "slug": "ollama", "metric": "stars", "value": 164987, "as_of": "2026-03-14"},
            {"type": "project", "slug": "ollama", "metric": "downloads_monthly", "value": 0, "as_of": "2026-03-14"},
            {"type": "project", "slug": "LLMs-from-scratch", "metric": "stars", "value": 87892, "as_of": "2026-03-14"},
            {"type": "project", "slug": "LocalAI", "metric": "stars", "value": 43530, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    {
        "slug": "transformers-fine-tuning-stack",
        "domain": "transformers",
        "title": "LlamaFactory (68K stars) + Unsloth (54K stars, 1.5M dl/mo) are making fine-tuning a CLI command, not a research project",
        "summary": (
            "LlamaFactory provides the training UI, Unsloth provides 2x speed with 70% less VRAM, PEFT provides the underlying "
            "LoRA technique. Together they've collapsed fine-tuning from PhD-level to pip-install-level."
        ),
        "detail": """## The Democratization Stack

Fine-tuning a large language model used to require a research team, multi-GPU clusters, and deep expertise in distributed training. In 2026, it takes three pip installs and a YAML file.

LlamaFactory (68K stars) provides a unified interface for fine-tuning 100+ LLMs and VLMs. With zero PyPI downloads (it installs from source via git), its 68K stars represent pure organic developer interest.

Unsloth (54K stars, 1.5M dl/mo) sits one layer down, delivering memory-efficient training kernels. Its pitch — "2x faster with 70% less VRAM" — means a model that needed an A100 can now train on a consumer RTX 4090. At 1.5M monthly downloads, it's past experimentation and into production fine-tuning workflows.

PEFT (20.8K stars, 8.9M dl/mo) provides the foundational LoRA and adapter techniques that both tools build on. As a Hugging Face project, it's the connective tissue linking the fine-tuning stack to the broader transformers ecosystem.

The combined signal: LlamaFactory for the interface, Unsloth for the efficiency, PEFT for the technique. Each solves a different barrier to entry. The result is that model customization has become accessible to any team with a single GPU.""",
        "evidence": [
            {"type": "project", "slug": "LlamaFactory", "metric": "stars", "value": 68347, "as_of": "2026-03-14"},
            {"type": "project", "slug": "unsloth", "metric": "stars", "value": 53879, "as_of": "2026-03-14"},
            {"type": "project", "slug": "unsloth", "metric": "downloads_monthly", "value": 1527951, "as_of": "2026-03-14"},
            {"type": "project", "slug": "peft", "metric": "downloads_monthly", "value": 8917719, "as_of": "2026-03-14"},
            {"type": "project", "slug": "peft", "metric": "stars", "value": 20777, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    # -----------------------------------------------------------------------
    # PROMPT-ENGINEERING
    # -----------------------------------------------------------------------
    {
        "slug": "prompt-eng-mlflow-monopoly",
        "domain": "prompt-engineering",
        "title": "mlflow owns 79% of prompt-engineering downloads — an ML experiment tracker became the prompt standard",
        "summary": (
            "mlflow pulls 32.5M downloads/month in a domain totalling 41.2M. "
            "Built for ML experiment tracking in 2018, it now dominates LLM evaluation infrastructure. "
            "The next project (opik) has barely 10% of its volume."
        ),
        "detail": """## An Experiment Tracker Ate Prompt Engineering

The "prompt-engineering" domain on GitHub sounds like it should be about writing better prompts. Instead, 79% of its downloads go to mlflow — a tool Databricks built in 2018 for tracking ML experiments.

mlflow pulls 32.5M downloads/month against a domain total of 41.2M. The next three projects combined (opik at 3.4M, langfuse at 3.3M, outlines at 1.4M) account for just 19.5%. Everything else in the domain — 4,616 repos including prompt libraries, template engines, and optimization frameworks — splits 612K downloads.

This isn't a naming accident. When teams operationalize prompts, they need versioning, A/B comparisons, and evaluation pipelines — exactly what experiment trackers provide. mlflow added LLM-specific features (prompt tracking, model evaluation) on top of infrastructure that was already battle-tested at scale. The result: "prompt engineering" as a practice is dominated by a tool that never set out to be a prompt tool.""",
        "evidence": [
            {"type": "project", "slug": "mlflow", "metric": "downloads_monthly", "value": 32507093, "as_of": "2026-03-14"},
            {"type": "project", "slug": "opik", "metric": "downloads_monthly", "value": 3417440, "as_of": "2026-03-14"},
            {"type": "project", "slug": "langfuse", "metric": "downloads_monthly", "value": 3251140, "as_of": "2026-03-14"},
            {"type": "project", "slug": "mlflow", "metric": "stars", "value": 24762, "as_of": "2026-03-14"},
            {"type": "stat", "label": "mlflow share of prompt-engineering downloads", "value": "79%", "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    {
        "slug": "prompt-eng-eval-observability",
        "domain": "prompt-engineering",
        "title": "opik and langfuse are neck-and-neck at ~3.4M downloads/month, but solve different problems",
        "summary": (
            "opik (3.4M dl/mo) and langfuse (3.3M dl/mo) are the two LLM-native evaluation tools "
            "in prompt-engineering. outlines (1.4M dl/mo) solves constrained generation instead. "
            "The domain is really three sub-domains: experiment tracking, eval/observability, and structured output."
        ),
        "detail": """## Three Sub-Domains Wearing One Label

Strip out mlflow's 32.5M downloads and the prompt-engineering domain reveals three distinct tool categories competing for the remaining 8.7M downloads/month.

**Eval and observability (6.7M combined):** opik (3.4M dl/mo, 18,211 stars) and langfuse (3.3M dl/mo, 23,106 stars) are nearly tied but take different approaches. opik focuses on prompt testing and evaluation — scoring outputs before they reach production. langfuse provides production tracing and observability — understanding what happened after deployment. langfuse has more stars (23K vs 18K) suggesting broader community awareness, but opik's slightly higher download count signals stronger CI/CD integration.

**Constrained generation (1.4M):** outlines (1.4M dl/mo, 13,552 stars) isn't an evaluation tool at all. It enforces structured output from LLMs — ensuring JSON schema compliance, regex patterns, and grammar constraints. It solves a fundamentally different problem: making LLM outputs machine-readable.

**Everything else (612K):** The remaining projects with downloads include llm-guard, promptflow, and a long tail of niche tools. The "prompt-engineering" label masks at least three distinct infrastructure needs.""",
        "evidence": [
            {"type": "project", "slug": "opik", "metric": "downloads_monthly", "value": 3417440, "as_of": "2026-03-14"},
            {"type": "project", "slug": "langfuse", "metric": "downloads_monthly", "value": 3251140, "as_of": "2026-03-14"},
            {"type": "project", "slug": "outlines", "metric": "downloads_monthly", "value": 1372483, "as_of": "2026-03-14"},
            {"type": "project", "slug": "opik", "metric": "stars", "value": 18211, "as_of": "2026-03-14"},
            {"type": "project", "slug": "langfuse", "metric": "stars", "value": 23106, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    # -----------------------------------------------------------------------
    # GENERATIVE-AI
    # -----------------------------------------------------------------------
    {
        "slug": "generative-ai-hype-desert",
        "domain": "generative-ai",
        "title": "generative-ai has 7,812 repos but only 774K total downloads/month — a domain of tutorials, not infrastructure",
        "summary": (
            "The generative-ai GitHub topic contains 7,812 repos but only 14 have any downloads at all, "
            "totalling 774K/month. Average downloads per repo: 99. "
            "Real generative AI work is tagged under specific domains like transformers or ml-frameworks."
        ),
        "detail": """## The Hype Desert

The "generative-ai" GitHub topic is the largest graveyard in AI open source. Of 7,812 repos carrying the tag, 7,798 have zero package downloads. The 14 with any downloads at all total just 774K/month — less than a single mid-tier Python utility library.

The average downloads per repo across the domain is 99/month. For context, the prompt-engineering domain (4,616 repos) generates 41.2M downloads/month, roughly 53x the volume from 59% fewer repos.

This isn't because generative AI tools don't exist. It's because working tools don't use this tag. Hugging Face transformers, diffusers, and stable-diffusion-webui are tagged under their specific domains. "Generative-ai" became a GitHub discovery tag — used by tutorial authors, course projects, and demo repos to attract visitors. The tag signals educational intent, not production software.

The result is a domain where star counts (many repos have 500+) dramatically overstate real adoption. It's a textbook hype desert: high visibility, near-zero usage.""",
        "evidence": [
            {"type": "query", "sql": "SELECT COUNT(*) FROM ai_repos WHERE domain = 'generative-ai'", "value": 7812, "as_of": "2026-03-14"},
            {"type": "query", "sql": "SELECT SUM(downloads_monthly) FROM ai_repos WHERE domain = 'generative-ai'", "value": 774366, "as_of": "2026-03-14"},
            {"type": "query", "sql": "SELECT COUNT(*) FROM ai_repos WHERE domain = 'generative-ai' AND downloads_monthly > 0", "value": 14, "as_of": "2026-03-14"},
            {"type": "stat", "label": "Average downloads per generative-ai repo", "value": 99, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    {
        "slug": "generative-ai-real-projects",
        "domain": "generative-ai",
        "title": "Only 3 projects have real adoption in generative-ai — prompty, SDV, jupyter-ai — and they have nothing in common",
        "summary": (
            "prompty (488K dl/mo), SDV (146K dl/mo), and jupyter-ai (127K dl/mo) account for 98.3% "
            "of generative-ai domain downloads. They serve completely unrelated purposes: "
            "prompt templating, synthetic data, and notebook AI assistants. There is no coherent category here."
        ),
        "detail": """## Three Strangers Sharing a Tag

The generative-ai domain's 774K monthly downloads are concentrated in three projects that account for 98.3% of the total. They have almost nothing in common.

**prompty (488K dl/mo, 1,170 stars)** is a Microsoft prompt templating format — a way to define LLM prompts as structured files with metadata, model configuration, and input variables. It's infrastructure for prompt management, not generative AI per se.

**SDV (146K dl/mo, 3,439 stars)** is the Synthetic Data Vault — a library for generating synthetic tabular data using statistical and deep learning models. It predates the current AI boom and serves data science teams doing privacy-preserving analytics.

**jupyter-ai (127K dl/mo, 4,150 stars)** adds AI chat and code generation to Jupyter notebooks. It's an IDE extension, not a framework.

These three projects serve prompt engineers, data scientists, and notebook users respectively. The only reason they share a domain label is that GitHub's "generative-ai" topic is broad enough to catch anything tangentially related to AI content generation. The "generative-ai" label is a GitHub tag, not an ecosystem.""",
        "evidence": [
            {"type": "project", "slug": "prompty", "metric": "downloads_monthly", "value": 488289, "as_of": "2026-03-14"},
            {"type": "project", "slug": "SDV", "metric": "downloads_monthly", "value": 146466, "as_of": "2026-03-14"},
            {"type": "project", "slug": "jupyter-ai", "metric": "downloads_monthly", "value": 126611, "as_of": "2026-03-14"},
            {"type": "stat", "label": "Top 3 share of generative-ai downloads", "value": "98.3%", "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    # -----------------------------------------------------------------------
    # AGENTS (new additions)
    # -----------------------------------------------------------------------
    {
        "slug": "agents-browser-vs-code",
        "domain": "agents",
        "title": "browser-use (80K stars, 3.9M dl/mo) vs firecrawl (92K stars, 55K dl/mo) — two agent paradigms with opposite adoption signatures",
        "summary": (
            "Browser-use leads in package downloads 70:1 despite having fewer stars. Firecrawl's 92K stars "
            "but 55K monthly downloads reveal a self-hosted, API-first model invisible to package managers. "
            "The agent space is splitting into interactive browser agents and headless data extraction tools."
        ),
        "detail": """## Two Paradigms, Two Adoption Patterns

The agent ecosystem's browser layer has split into two distinct paradigms with radically different adoption signatures.

**browser-use** (80,598 stars, 3,883,828 downloads/month) is the interactive browser agent — it automates real browsing sessions, filling forms, clicking buttons, navigating pages. Its 3.9M monthly downloads indicate production integration as a Python library.

**firecrawl** (92,265 stars, 55,113 downloads/month) takes the opposite approach — headless web data extraction, turning websites into LLM-ready markdown. Despite having 15% more stars than browser-use, it has 70x fewer package downloads. This isn't a failure; it is a different deployment model. Firecrawl is primarily self-hosted or used via API, making its PyPI footprint a poor proxy for real usage.

**The ratio tells the story:**
- browser-use: 1 download per 20.8 stars (library pattern)
- firecrawl: 1 download per 1,674 stars (self-hosted/API pattern)

Neither GitHub stars nor PyPI downloads alone capture the full picture. You need both signals to understand adoption in the agent space. In the agents domain, crewAI leads downloads at 5.5M/month, followed by browser-use at 3.9M and E2B at 2.7M. Firecrawl ranks 11th by downloads but 1st by stars — the most extreme hype ratio inversion in the domain.""",
        "evidence": [
            {"type": "project", "slug": "browser-use", "metric": "stars", "value": 80598, "as_of": "2026-03-14"},
            {"type": "project", "slug": "browser-use", "metric": "downloads_monthly", "value": 3883828, "as_of": "2026-03-14"},
            {"type": "project", "slug": "firecrawl", "metric": "stars", "value": 92265, "as_of": "2026-03-14"},
            {"type": "project", "slug": "firecrawl", "metric": "downloads_monthly", "value": 55113, "as_of": "2026-03-14"},
            {"type": "project", "slug": "crewAI", "metric": "downloads_monthly", "value": 5498708, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    {
        "slug": "agents-orchestration-consolidation",
        "domain": "agents",
        "title": "CrewAI dominates agent orchestration at 5.5M dl/mo — E2B (2.7M) carves out sandboxed execution as a separate race",
        "summary": (
            "CrewAI's 5.5M monthly downloads are 2x E2B's 2.7M and 10x composio's 523K. "
            "General-purpose orchestration is consolidating around one framework, while E2B owns "
            "the sandboxed code execution niche. The 'CrewAI or nothing' dynamic mirrors LangChain's RAG dominance."
        ),
        "detail": """## Orchestration Has a Default

The agents domain top 5 by downloads tells a clear consolidation story:

1. **crewAI** — 5,498,708 dl/mo (general orchestration)
2. **browser-use** — 3,883,828 dl/mo (browser automation)
3. **E2B** — 2,730,588 dl/mo (sandboxed execution)
4. **composio** — 522,750 dl/mo (tool/API integrations)
5. **agentscope** — 262,279 dl/mo (Alibaba's entry)

CrewAI has achieved what LangChain did for RAG — it is the default answer to "how do I orchestrate multiple agents." With 45,936 stars and a "growing" lifecycle, it is still accelerating.

**E2B occupies a different niche entirely.** At 2,730,588 downloads/month, it is not competing with CrewAI — it is the infrastructure that orchestration frameworks call when agents need to run code safely. E2B provides sandboxed environments, not agent coordination.

**What this means:** If you are building a multi-agent system today, the decision tree is short. CrewAI for orchestration, E2B if you need sandboxed execution, composio if you need third-party tool integrations. The "framework wars" phase is ending; the integration phase has begun.""",
        "evidence": [
            {"type": "project", "slug": "crewAI", "metric": "downloads_monthly", "value": 5498708, "as_of": "2026-03-14"},
            {"type": "project", "slug": "crewAI", "metric": "stars", "value": 45936, "as_of": "2026-03-14"},
            {"type": "project", "slug": "E2B", "metric": "downloads_monthly", "value": 2730588, "as_of": "2026-03-14"},
            {"type": "project", "slug": "composio", "metric": "downloads_monthly", "value": 522750, "as_of": "2026-03-14"},
            {"type": "project", "slug": "agentscope", "metric": "downloads_monthly", "value": 262279, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    # -----------------------------------------------------------------------
    # RAG (new addition)
    # -----------------------------------------------------------------------
    {
        "slug": "rag-self-hosted-platforms",
        "domain": "rag",
        "title": "Dify (133K stars) + Open WebUI (127K) + ragflow (75K) = 335K stars, zero PyPI downloads — RAG's invisible Docker ecosystem",
        "summary": (
            "The three largest RAG platforms by stars are Docker-deployed and invisible to PyPI. "
            "LangChain's 223M monthly downloads dominate the library ecosystem. RAG has two worlds "
            "that cannot see each other's adoption metrics."
        ),
        "detail": """## RAG's Two Worlds

The RAG domain has a measurement problem. Its two largest ecosystems use fundamentally different distribution models, making cross-comparison nearly impossible.

**The self-hosted platform world:**
- **dify** — 132,613 stars, 0 PyPI downloads (Docker-deployed)
- **open-webui** — 126,989 stars, 0 PyPI downloads (Docker-deployed)
- **ragflow** — 74,911 stars, 0 PyPI downloads (Docker-deployed)

Combined: 334,513 GitHub stars. Combined PyPI downloads: zero.

**The library world:**
- **langchain** — 129,354 stars, 223,185,230 PyPI downloads/month

LangChain alone has 223M monthly downloads — more than the entire MCP ecosystem. But Dify alone has more GitHub stars than LangChain. These are not competing products; they are different layers that happen to solve overlapping problems.

**The implication for ecosystem intelligence:** Any analysis that uses only PyPI downloads will conclude LangChain is the entire RAG story. Any analysis that uses only GitHub stars will miss LangChain's production dominance. You need both lenses.

Flowise (50,686 stars), mem0 (49,646 stars), and quivr (38,997 stars) represent a middle tier of RAG platforms — substantial star counts, minimal package downloads. The pattern is consistent: RAG platforms are deployed as containers, not installed as libraries.""",
        "evidence": [
            {"type": "project", "slug": "dify", "metric": "stars", "value": 132613, "as_of": "2026-03-14"},
            {"type": "project", "slug": "open-webui", "metric": "stars", "value": 126989, "as_of": "2026-03-14"},
            {"type": "project", "slug": "ragflow", "metric": "stars", "value": 74911, "as_of": "2026-03-14"},
            {"type": "project", "slug": "langchain", "metric": "downloads_monthly", "value": 223185230, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    # -----------------------------------------------------------------------
    # EMBEDDINGS (new addition)
    # -----------------------------------------------------------------------
    {
        "slug": "embeddings-qdrant-vertical-play",
        "domain": "embeddings",
        "title": "Qdrant owns fastembed (2.9M dl/mo) + qdrant-client (15M dl/mo) — the only vector DB company controlling the embedding layer",
        "summary": (
            "Qdrant's fastembed is the #2 embeddings library at 2.9M downloads/month. No other vector DB "
            "company owns an embedding tool. This vertical integration creates a pipeline: use fastembed, "
            "and Qdrant is the natural next step."
        ),
        "detail": """## Vertical Integration in Embeddings

The embeddings domain top 5 by downloads reveals an unexpected player:

1. **pytorch-metric-learning** — 3,724,155 dl/mo (general-purpose)
2. **fastembed** — 2,867,732 dl/mo (Qdrant-owned)
3. **mteb** — 1,541,068 dl/mo (benchmark suite)
4. **model2vec** — 511,106 dl/mo (lightweight embeddings)
5. **FlagEmbedding** — 451,945 dl/mo (BAAI's embedding models)

**fastembed is Qdrant's strategic play.** It is a lightweight, fast embedding library that runs locally without GPU dependencies. At 2,867,732 downloads/month, it is the second most-downloaded embeddings library — and it is owned by the same company that runs qdrant-client (14,966,287 downloads/month in the vector-db domain).

**No other vector database company has this.** Milvus does not own an embedding library. Chroma does not own one. Pinecone does not own one. Qdrant is the only company that controls both the embedding generation and the vector storage layer.

**The funnel effect:** A developer who starts with `pip install fastembed` for quick local embeddings discovers that Qdrant integration is zero-friction. Combined Qdrant ecosystem downloads: fastembed (2.9M) + qdrant-client (15.0M) = 17.9M monthly downloads across two domains. The qdrant server itself has 29,544 stars.""",
        "evidence": [
            {"type": "project", "slug": "fastembed", "metric": "downloads_monthly", "value": 2867732, "as_of": "2026-03-14"},
            {"type": "project", "slug": "fastembed", "metric": "stars", "value": 2771, "as_of": "2026-03-14"},
            {"type": "project", "slug": "qdrant-client", "metric": "downloads_monthly", "value": 14966287, "as_of": "2026-03-14"},
            {"type": "project", "slug": "qdrant", "metric": "stars", "value": 29544, "as_of": "2026-03-14"},
            {"type": "stat", "label": "pytorch-metric-learning dl/mo (embeddings #1)", "value": 3724155, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    # -----------------------------------------------------------------------
    # VECTOR-DB (new addition)
    # -----------------------------------------------------------------------
    {
        "slug": "vector-db-competitive-landscape",
        "domain": "vector-db",
        "title": "pymilvus (18.2M dl/mo) leads qdrant-client (15.0M) by 21% — llama_index (10.0M) sits between them as a kingmaker",
        "summary": (
            "The vector DB client race is closer than it looks: pymilvus leads qdrant-client by only 3.2M downloads. "
            "llama_index (10M dl/mo) makes this a three-way contest. "
            "Server stars tell a different story: Milvus 43K, Qdrant 30K, Chroma 27K."
        ),
        "detail": """## The Three-Way Vector DB Race

The vector-db domain downloads paint a competitive picture far tighter than the narrative suggests:

1. **pymilvus** — 18,151,557 dl/mo (Milvus client)
2. **qdrant-client** — 14,966,287 dl/mo (Qdrant client)
3. **llama_index** — 9,983,619 dl/mo (integration framework)

**The gap is narrower than expected.** pymilvus leads qdrant-client by 21% (3.2M downloads), not the 2-3x gap you might assume from Milvus's enterprise positioning.

**Server-side stars tell the infrastructure story:**
- milvus — 43,332 stars (enterprise-grade, CNCF graduated)
- qdrant — 29,544 stars (Rust-native, Apache-2.0)
- chroma — 26,607 stars (developer-friendly, Apache-2.0)

**llama_index is the kingmaker.** At 9,983,619 downloads/month, it is the integration layer that connects LLM applications to vector databases. Which vector DB llama_index defaults to or promotes in its docs has an outsized effect on adoption.

**The three races happening simultaneously:**
1. **Client adoption:** pymilvus vs qdrant-client (within 21% of each other)
2. **Framework integration:** llama_index vs LangChain as the layer that chooses vector DBs for developers
3. **Developer experience:** Chroma's simplicity vs Qdrant's performance vs Milvus's scale

In most infrastructure categories, one player has 3-5x the next. Vector databases have two clients within 21% of each other. This race is not settled.""",
        "evidence": [
            {"type": "project", "slug": "pymilvus", "metric": "downloads_monthly", "value": 18151557, "as_of": "2026-03-14"},
            {"type": "project", "slug": "qdrant-client", "metric": "downloads_monthly", "value": 14966287, "as_of": "2026-03-14"},
            {"type": "project", "slug": "llama_index", "metric": "downloads_monthly", "value": 9983619, "as_of": "2026-03-14"},
            {"type": "project", "slug": "milvus", "metric": "stars", "value": 43332, "as_of": "2026-03-14"},
            {"type": "project", "slug": "chroma", "metric": "stars", "value": 26607, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    # -----------------------------------------------------------------------
    # CROSS-DOMAIN
    # -----------------------------------------------------------------------
    {
        "slug": "cross-domain-download-hierarchy",
        "domain": "ml-frameworks",
        "title": "The AI download hierarchy: LangChain (223M) > scikit-learn (181M) > transformers (112M) — orchestration and classical ML dwarf model hype",
        "summary": (
            "The top 20 most-downloaded AI projects reveal a surprising order: LangChain leads at 223M dl/mo, "
            "scikit-learn follows at 181M, huggingface_hub at 179M. LLM model code (transformers) ranks 4th."
        ),
        "detail": """## The Real Download Hierarchy

The top 10 AI projects by monthly downloads reveal an industry that looks nothing like the narrative:

1. **LangChain** — 223.2M (orchestration)
2. **scikit-learn** — 180.6M (classical ML)
3. **huggingface_hub** — 179.2M (model distribution)
4. **transformers** — 112.4M (model definitions)
5. **litellm** — 93.6M (LLM routing)
6. **datasets** — 60.6M (data loading)
7. **ray** — 58.6M (distributed compute)
8. **nltk** — 55.4M (text processing)
9. **fastmcp** — 48.6M (MCP protocol)
10. **langgraph** — 39.4M (agent orchestration)

Three observations stand out. First, LangChain at #1 means the orchestration layer — the code that *calls* models — is downloaded more than any model framework. The glue is bigger than the engine. Second, scikit-learn at #2 confirms that classical ML isn't declining; it's the second most-installed AI library in the world. Third, litellm at 93.6M shows that production teams don't commit to a single LLM provider — they route across them.

The split: roughly 40% is LLM-adjacent (LangChain, transformers, litellm, datasets, langgraph), 35% is classical ML and infrastructure (scikit-learn, ray, nltk), and 25% is tooling glue (huggingface_hub, fastmcp).""",
        "evidence": [
            {"type": "project", "slug": "langchain", "metric": "downloads_monthly", "value": 223185230, "as_of": "2026-03-14"},
            {"type": "project", "slug": "scikit-learn", "metric": "downloads_monthly", "value": 180627438, "as_of": "2026-03-14"},
            {"type": "project", "slug": "huggingface_hub", "metric": "downloads_monthly", "value": 179223656, "as_of": "2026-03-14"},
            {"type": "project", "slug": "transformers", "metric": "downloads_monthly", "value": 112431126, "as_of": "2026-03-14"},
            {"type": "project", "slug": "litellm", "metric": "downloads_monthly", "value": 93642606, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    {
        "slug": "cross-domain-huggingface-gravity",
        "domain": "ml-frameworks",
        "title": "HuggingFace owns 4 of the top 6 most-downloaded AI projects — 361M+ combined monthly downloads make it the npm of machine learning",
        "summary": (
            "huggingface_hub (179M), transformers (112M), datasets (60.6M), and peft (8.9M) sum to 361M downloads/month. "
            "No other lab has this kind of cross-stack gravitational pull on the AI ecosystem."
        ),
        "detail": """## The npm of AI

HuggingFace projects occupy 4 of the top 6 positions in AI downloads: huggingface_hub at 179.2M/month, transformers at 112.4M, datasets at 60.6M, and peft at 8.9M. That's 361.2M combined monthly downloads.

This is platform gravity in its purest form. huggingface_hub is the distribution layer — the pip install that pulls model weights. transformers is the model definition layer. datasets is the data loading layer. peft handles fine-tuning. Each library serves a different stage of the ML pipeline, and together they create an integrated stack that's hard to leave.

The pattern mirrors npm's dominance in JavaScript: not one killer package, but a constellation of interdependent utilities that become the default import path. When your hub, your model library, your data loader, and your fine-tuning toolkit all share the same `from huggingface` prefix, switching costs compound at every layer.

At T1 Foundational tier, transformers alone has 157.8K GitHub stars. peft, a T2 Major project, is "established." This isn't a portfolio play — it's an operating system for AI development, and the download numbers say the industry has already adopted it.""",
        "evidence": [
            {"type": "project", "slug": "huggingface_hub", "metric": "downloads_monthly", "value": 179223656, "as_of": "2026-03-14"},
            {"type": "project", "slug": "transformers", "metric": "downloads_monthly", "value": 112431126, "as_of": "2026-03-14"},
            {"type": "project", "slug": "datasets", "metric": "downloads_monthly", "value": 60596468, "as_of": "2026-03-14"},
            {"type": "project", "slug": "peft", "metric": "downloads_monthly", "value": 8917719, "as_of": "2026-03-14"},
            {"type": "project", "slug": "transformers", "metric": "stars", "value": 157811, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
    {
        "slug": "cross-domain-experiment-tracking",
        "domain": "ml-frameworks",
        "title": "wandb (22.9M) + mlflow (32.5M) + langfuse (3.3M) = 58.6M dl/mo — experiment tracking is bigger than agent frameworks",
        "summary": (
            "The 'boring' MLOps observability layer generates 58.6M monthly downloads across three projects "
            "spanning two PT-Edge domains. This is 10x CrewAI's 5.5M and exceeds the entire agents domain. "
            "Production ML infrastructure dwarfs the flashy framework layer."
        ),
        "detail": """## The Boring Infrastructure That Runs Everything

Three experiment tracking and observability projects span two PT-Edge domains (ml-frameworks, prompt-engineering) and collectively generate more production traffic than the entire agents domain:

1. **mlflow** — 32,507,093 dl/mo (prompt-engineering domain)
2. **wandb** — 22,850,828 dl/mo (ml-frameworks domain)
3. **langfuse** — 3,251,140 dl/mo (prompt-engineering domain)

**Combined: 58,609,061 monthly downloads.** For comparison, the entire agents domain top 5 combined totals ~14.6M downloads/month. Experiment tracking alone is 4x that.

**Each serves a different era of ML:**
- **mlflow** (32.5M dl/mo) — the incumbent. Databricks-backed, covers the full ML lifecycle.
- **wandb** (22.9M dl/mo) — the developer favorite. At 10,897 stars, it has the lowest star-to-download ratio, indicating deep production adoption with minimal GitHub tourism.
- **langfuse** (3.3M dl/mo) — the LLM-native entrant. At 23,106 stars, langfuse has more GitHub stars than mlflow despite 10x fewer downloads.

**The domain-split problem:** These three projects do essentially the same thing (track experiments, log metrics, enable reproducibility) but PT-Edge classifies them across two domains. This fragmentation makes the category's true size invisible unless you look cross-domain.

When AI discourse focuses on agent frameworks and prompt engineering tools, it misses that the infrastructure layer is where the actual production volume lives. The boring stuff is bigger than the exciting stuff. It always is.""",
        "evidence": [
            {"type": "project", "slug": "mlflow", "metric": "downloads_monthly", "value": 32507093, "as_of": "2026-03-14"},
            {"type": "project", "slug": "wandb", "metric": "downloads_monthly", "value": 22850828, "as_of": "2026-03-14"},
            {"type": "project", "slug": "langfuse", "metric": "downloads_monthly", "value": 3251140, "as_of": "2026-03-14"},
            {"type": "project", "slug": "crewAI", "metric": "downloads_monthly", "value": 5498708, "as_of": "2026-03-14"},
            {"type": "stat", "label": "Combined experiment tracking dl/mo", "value": 58609061, "as_of": "2026-03-14"},
        ],
        "source_article": None,
    },
]


def seed():
    """Insert or update all briefing entries."""
    with engine.connect() as conn:
        for entry in ENTRIES:
            # Serialize evidence to JSON string for the JSONB column
            params = dict(entry)
            if params.get("evidence"):
                params["evidence"] = json.dumps(params["evidence"])
            conn.execute(text("""
                INSERT INTO briefings (slug, domain, title, summary, detail, evidence, source_article, verified_at, updated_at)
                VALUES (:slug, :domain, :title, :summary, :detail, :evidence::jsonb, :source_article, NOW(), NOW())
                ON CONFLICT (slug)
                DO UPDATE SET
                    domain = EXCLUDED.domain,
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    detail = EXCLUDED.detail,
                    evidence = EXCLUDED.evidence,
                    source_article = EXCLUDED.source_article,
                    verified_at = NOW(),
                    updated_at = NOW()
            """), params)
        conn.commit()
    print(f"Seeded {len(ENTRIES)} briefing entries")


async def seed_with_embeddings():
    """Seed briefing entries and generate embeddings if API key is set."""
    seed()

    from app.embeddings import is_enabled
    if not is_enabled():
        print("OPENAI_API_KEY not set — skipping embedding generation.")
        return

    from app.backfill_embeddings import backfill_briefings
    count = await backfill_briefings(force=True)
    print(f"Generated embeddings for {count} briefing entries.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(seed_with_embeddings())
