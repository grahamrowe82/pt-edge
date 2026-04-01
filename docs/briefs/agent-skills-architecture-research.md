# Agent Skills Architecture — Research Brief

## Search demand signal

- GSC: "evoskills" (5 impressions, pos 9.5), "guanyang/antigravity-skills" (3 impressions, pos 5.7), "agent skills architecture" (1 impression, pos 75). Early signals from informed searchers.
- HN: **Huge signal.** "Agent Skills" (544pts, 261 comments), "SkillsBench" (364pts), "Agent Skills Leaderboard" (135pts), multiple OpenClaw discussions (138pts for Klaus, 121pts for "real users?" thread, 110pts for security critique). This is an active, contentious HN topic.
- OpenClaw acquisition by OpenAI generated discussion (62pts, 25pts for separate posts). The space is commercially significant.

## Landscape structure

Massive space — 2,700+ repos across 15 subcategories:

| Subcategory | Repos | Avg Quality | Max Quality | Total Stars |
|---|---|---|---|---|
| agentic-workflow-skills | 327 | 23.6 | 68 | 40,947 |
| agent-skill-registry | 292 | 22.9 | 64 | 7,876 |
| lightweight-agent-frameworks | 271 | 24.5 | **87** | 24,367 |
| openclaw-skill-marketplace | 271 | 22.6 | 64 | 5,939 |
| agent-orchestration-platforms | 259 | 22.0 | 67 | 9,940 |
| agent-runtime-engines | 258 | 24.2 | 83 | **81,796** |
| openclaw-skill-integrations | 230 | **14.8** | 37 | 145 |
| claude-code-configuration | 223 | 25.0 | 68 | 39,354 |
| typescript-agent-frameworks | 212 | 23.9 | 87 | 39,921 |
| agent-communication-standards | 165 | 22.7 | 63 | 3,287 |
| agent-skill-security | 64 | 23.8 | 49 | 267 |
| agent-registry-infrastructure | 63 | 21.0 | 61 | 5,556 |
| agent-specification-frameworks | 47 | 24.6 | 53 | 444 |
| openclaw-resource-curation | 47 | 24.4 | 64 | 2,809 |
| agentic-commerce-protocols | 33 | 22.7 | 47 | 86 |

**Key insights:**
- openclaw-skill-integrations has the lowest quality (14.8 avg) — lots of trivial wrappers
- The real quality is in runtime engines (83 max, agno at 38.7K stars) and frameworks (87 max, Composio at 27.4K stars)
- Skills collections are massively popular: antigravity-awesome-skills (23.8K stars), awesome-agent-skills (11K stars)
- The registry/marketplace layer is fragmented: 292 registry repos, 271 marketplace repos, mostly experimental

## Tier 1: The established platforms

### Tool/skill orchestration (the infrastructure layer)
- **Composio** (87/100, 27.4K stars, 624 commits/30d) — 1000+ toolkits, tool search, auth, sandboxed workbench. The dominant tool platform.
- **agno** (66/100, 38.7K stars, 120 commits/30d) — Build, run, manage agentic software at scale. Massive adoption.
- **AgentScope** (83/100, 18K stars) — Build agents you can see, understand and trust.
- **AWS agent-squad** (67/100, 7.5K stars) — Multi-agent orchestration from AWS.

### Skill collections (the catalogue layer)
- **antigravity-awesome-skills** (68/100, 23.8K stars, 609 commits/30d) — 1000+ skills for Claude Code/Antigravity/Cursor
- **awesome-agent-skills** (VoltAgent, 64/100, 11K stars) — 500+ skills from official dev teams + community
- **openclaw-master-skills** (64/100, 1.5K stars) — 339+ curated OpenClaw skills

### Skill registries & discovery
- **Acontext** (64/100, 3.2K stars, 188 commits/30d) — "Agent Skills as a Memory Layer"
- **hashgraph registry-broker-skills** (113 stars) — 72K+ agents across 14 protocols
- **skillport** (59/100, 338 stars) — Universal skill installer for coding agents
- **flins** (60/100, 34 stars) — Universal skill installer

### Agent communication & standards
- **agent-capability-standard** (synaptiai, 3 stars) — Open spec: 36 atomic capabilities across 9 cognitive layers
- **AgentsMesh** (63/100, 1.1K stars, 277 commits/30d) — Agent fleet command center
- **better-agents** (langwatch, 63/100, 1.5K stars) — Standards for building agents
- **A2A agent registry** (AWS, 19 stars) — Agent discovery via A2A protocol

## The OpenClaw ecosystem

OpenClaw is the most visible skills ecosystem, with its own subcategories:
- openclaw-skill-marketplace: 271 repos (curated collections, marketplaces)
- openclaw-skill-integrations: 230 repos (individual skills for specific tools)
- openclaw-resource-curation: 47 repos

HN is both enthusiastic and critical:
- "Agent Skills" (544pts) — the original concept
- "OpenClaw is basically a cascade of LLMs in prime position to mess stuff up" (110pts) — the security critique
- OpenClaw acquired by OpenAI (62pts + 25pts)
- "Ask HN: Any real OpenClaw users?" (121pts, 189 comments) — the adoption reality check

The security angle (skill-security subcategory, 64 repos) is relevant here — skills are code that agents execute, and the trust model is immature.

## HN narrative arc

The HN community is in a "cautious enthusiasm" phase:
1. **Agent Skills concept** is accepted and exciting (544pts)
2. **Benchmarking** is emerging (SkillsBench 364pts, leaderboard 135pts)
3. **Security concerns** are real (skills getting full system access, supply chain risks)
4. **OpenClaw/Antigravity** ecosystem is the most discussed specific implementation
5. **"Real users?"** thread (121pts, 189 comments) suggests adoption is still questioned

## Article structure (derived from data)

1. Opening: "agent skills" is the new vocabulary. What it means vs tools/functions/MCP.
2. **The skill platforms** — Composio, agno, AgentScope. Where skills run.
3. **The skill collections** — antigravity-awesome-skills, awesome-agent-skills. Where skills are found.
4. **The registry problem** — 292 registry repos, most experimental. Discovery and trust are unsolved.
5. **The OpenClaw ecosystem** — the most visible implementation, HN loves and fears it.
6. **Skills vs MCP vs function calling** — how these concepts relate and differ.
7. **The security question** — skills are code agents execute. Trust model is immature.
8. Warning: openclaw-skill-integrations avg quality 14.8/100. Most individual skills are trivial wrappers.
9. CTA: browse categories, trending.

## Featured categories for manifest

- agents:agentic-workflow-skills (327 repos)
- agents:agent-skill-registry (292 repos)
- agents:openclaw-skill-marketplace (271 repos)
- agents:agent-runtime-engines (258 repos)
- agents:typescript-agent-frameworks (212 repos)
- agents:agent-communication-standards (165 repos)
- agents:agent-skill-security (64 repos)
