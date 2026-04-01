# Obsidian/PKM Agents — Research Brief

## Search demand signal

- GSC: "hermes agent obsidian integration" — 2 impressions at position 4.5 on the `obsidian-vault-agents` category page. That category page got **45 total impressions** — the single highest-impression page on the entire site in first 3 days.
- HN: Quiet. Only 82pts for a general "semantically-connected personal knowledge base" post. No Obsidian+AI specific hits. This is a community-search-driven audience, not an HN-hype audience. They search for tools, they don't discuss them on HN.
- Allocation: obsidian-vault-agents is `github-only` confidence — pure supply signal, no demand data yet. The 45 GSC impressions haven't fed into allocation scores yet.

## Landscape structure

The PKM+AI space spans multiple domains and subcategories. Much bigger than just "obsidian agents":

| Domain | Subcategory | Repos | Avg Quality | Max Quality | Total Stars |
|---|---|---|---|---|---|
| rag | personal-knowledge-management | 126 | 21.4 | **79** | 83,908 |
| embeddings | personal-knowledge-management | 140 | 21.0 | 60 | 5,904 |
| llm-tools | content-to-markdown | 113 | 25.2 | 77 | 117,999 |
| llm-tools | obsidian-ai-plugins | 65 | **27.9** | 64 | 65,331 |
| embeddings | mcp-semantic-retrieval | 69 | 23.4 | 52 | 415 |
| agents | markdown-agent-tools | 56 | 23.9 | 60 | 1,258 |
| vector-db | claude-code-knowledge-systems | 45 | — | — | 9,490 |
| llm-tools | ai-note-taking-apps | 35 | 18.1 | 55 | 2,336 |
| agents | obsidian-vault-agents | 33 | 23.2 | 45 | 1,235 |

**Key insight:** The real quality lives in the broader PKM apps (rag/personal-knowledge-management: max 79/100, khoj at 33K stars) and in the content-to-markdown pipeline (markitdown at 90K stars). The Obsidian-specific agent category (33 repos, avg 23.2) is mostly experimental. The article needs to cover the full stack, not just the 33 obsidian-vault-agents repos.

## Three layers of the PKM+AI stack

### Layer 1: Established PKM apps with AI (the real products)

These are production-grade note-taking/knowledge apps with AI features:

- **khoj** (79/100, 33.4K stars, 25 commits/30d) — "Your AI second brain." Self-hostable, works with any LLM. The quality leader.
- **SiYuan** (62/100, 41.8K stars, 406 commits/30d) — Privacy-first, self-hosted PKM. Written in TypeScript+Go. Massive active development.
- **SurfSense** (63/100, 13.2K stars, 894 commits/30d) — NotebookLM alternative for teams. Insane development velocity.
- **note-gen** (63/100, 11K stars, 120 commits/30d) — Cross-platform Markdown AI note-taking.
- **Smart Connections** (54/100, 4.7K stars, 15 commits/30d) — Obsidian plugin for AI chat + semantic links. The most-adopted Obsidian-specific AI integration.
- **Note Companion** (64/100, 809 stars, 23 commits/30d) — AI assistant for Obsidian (prev File Organizer 2000). Goes beyond chat.
- **eclaire** (62/100, 822 stars, 53 commits/30d) — Local-first AI assistant. Unify tasks, notes, docs, photos, bookmarks.
- **Smart2Brain** (61/100, 1K stars, 84 commits/30d) — Privacy-focused AI for Obsidian. RAG over your vault.
- **Lumina-Note** (62/100, 744 stars, 496 commits/30d) — Modern Markdown app with bidirectional links + AI.
- **QOwnNotes** (63/100, 5.6K stars, 204 commits/30d) — Plain-text notepad with Nextcloud integration.

### Layer 2: MCP bridge (connecting Obsidian to AI agents)

MCP servers that give AI agents structured access to Obsidian vaults:

- **mcpvault** (946 stars) — Lightweight, safe vault access. The most adopted.
- **obsidian-mcp-server** (cyanheads, 396 stars) — Comprehensive suite: read, write, search, organize.
- **turbovault** (38 stars, Rust) — Markdown/OFM SDK + MCP server, transforms vault into intelligent knowledge system.
- **vaultforge** (3 stars, 413 downloads/mo) — Local MCP with search, intelligence, canvas tools.
- Multiple smaller MCP servers (smith-and-web, ConnorBritain, Piotr1215, etc.)

### Layer 3: Agent-native Obsidian tools (experimental)

The obsidian-vault-agents category — repos built specifically for AI agents to work with vaults:

- **obsidian-claude-pkm** (1.2K stars) — Starter kit for Obsidian + Claude Code PKM. The standout.
- **iwe** (735 stars, 60/100) — Markdown knowledge management for text editors & AI agents. Rust.
- **obsidian-skill** (gmickel, 2 stars) — Agent skill for Obsidian CLI 1.12+.
- **session2vault** — Transform AI conversations into Obsidian-ready knowledge vaults.
- **aurum-framework** (3 stars) — Cognitive extraction: 40 AI agents, 24 quality gates, Obsidian-native.

Most of these are <1 month old and have <10 stars. This is the frontier.

## Content-to-markdown pipeline (adjacent but critical)

The invisible infrastructure that makes PKM+AI work:

- **markitdown** (Microsoft, 77/100, 90.7K stars) — Convert any file to Markdown. Foundational.
- **doocs/md** (65/100, 12K stars) — WeChat Markdown editor.
- Other content converters that feed the PKM pipeline.

## The local vs cloud decision

Obsidian users are privacy-conscious (it's a core value of the product). The AI tools that work with Obsidian split cleanly:

**Local-first:** khoj (self-hostable), Smart2Brain (privacy-focused), eclaire (local-first), obsidian-sonar (offline), Lumina-Note (local-first), Klee (secure and local)
**Cloud/API:** Note Companion (uses LLM APIs), Smart Connections (supports local or cloud), SurfSense (cloud-focused)
**MCP bridge:** All MCP servers are inherently local (they access local vault files) but the LLM they connect to can be local or cloud

## Featured categories for manifest

- agents:obsidian-vault-agents (33 repos — the GSC demand page)
- llm-tools:obsidian-ai-plugins (65 repos)
- rag:personal-knowledge-management (126 repos)
- embeddings:personal-knowledge-management (140 repos)
- agents:markdown-agent-tools (56 repos)
- mcp:obsidian-mcp-servers (discovered via semantic search)
- embeddings:mcp-semantic-retrieval (69 repos)

## Article structure (derived from data)

1. Opening: you have an Obsidian vault and want AI to work with it. Three paths.
2. **The established apps** — real products with AI features. khoj, SiYuan, Smart Connections, Note Companion. Decision framework: self-hosted vs cloud, Obsidian plugin vs standalone.
3. **The MCP bridge** — connecting vaults to AI agents. mcpvault, obsidian-mcp-server. Why MCP matters for PKM.
4. **The agent-native frontier** — obsidian-claude-pkm, iwe, agent skills. Where it's heading.
5. **The local vs cloud decision** — privacy-first audience, what works offline.
6. Warning: most obsidian AI repos are demos. Quality scores separate real tools from weekend projects.
7. CTA: browse the categories, trending, etc.
