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
                VALUES (:slug, :domain, :title, :summary, :detail, CAST(:evidence AS jsonb), :source_article, NOW(), NOW())
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
