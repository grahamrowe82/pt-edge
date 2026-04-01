# Agent Governance Landscape — Research Brief

## Search demand signal

- GSC: "agent governance toolkit" — 4 impressions, 1 click, position 9.8 (page 1). The only governance-related query with a click.
- Allocation engine: all governance subcategories show `confidence_level = github-only` (no GSC/Umami demand signal yet). ES scores 28-49. This is a supply-led market — tools are being built, search demand hasn't caught up yet.
- HN: Agent sandboxing dominates the conversation — "Agent Safehouse" (492pts), "Matchlock sandbox" (148pts), "Amla Sandbox WASM" (146pts), "Sandboxing AI agents in Linux" (119pts). NIST comment request on agent security got 49pts. HN community is focused on the runtime isolation problem specifically.

## Landscape structure

12 governance-adjacent subcategories in the agents domain, 1,263 repos total:

| Subcategory | Repos | Avg Quality | Max Quality | Total Stars |
|---|---|---|---|---|
| agent-authorization-guardrails | 250 | 24.1 | 61 | 2,853 |
| agent-security-hardening | 181 | 23.7 | 64 | 3,118 |
| agent-identity-standards | 142 | 23.4 | 69 | 1,926 |
| agent-observability-debugging | 124 | 21.8 | 77 | 4,202 |
| agent-code-sandboxing | 114 | 29.8 | **85** | **28,264** |
| ai-agent-vulnerability-scanning | 106 | 24.7 | 66 | 1,604 |
| agent-governance-frameworks | 98 | 22.1 | 44 | 358 |
| agent-credential-security | 80 | 23.5 | 52 | 861 |
| agent-skill-security | 64 | 23.8 | 49 | 267 |
| agent-cost-governance | 61 | 22.5 | 40 | 454 |
| agent-reliability-engineering | 34 | 25.1 | 57 | 541 |
| agent-monitoring-debugging | 9 | 52.7 | 66 | 39,885 |

**Key insight:** Sandboxing has the highest average quality (29.8) and most stars by far (28K). Monitoring has few repos but highest quality (52.7 avg — these are established tools like AgentOps, TruLens, Tracecat). Authorization/guardrails has the most repos (250) but low avg quality (24.1) — lots of experimental projects.

## Tier 1: Featured repos (recommendations)

### Execution sandboxing (the most mature governance layer)
- **E2B** (85/100, 11.3K stars, 37 commits/30d) — the market leader for cloud agent sandboxes
- **Alibaba OpenSandbox** (83/100, 7.7K stars, 352 commits/30d) — enterprise-grade, Docker/K8s runtimes
- **boxlite** (60/100, 1.5K stars, 66 commits/30d) — embeddable, stateful, hardware isolation
- **agent-safehouse** (57/100, 1.2K stars, 108 commits/30d) — macOS-native, HN darling (492pts)
- **nono** (61/100, 980 stars, 244 commits/30d) — kernel-enforced, capability-based, Rust
- **zeroboot** (57/100, 1.6K stars, 24 commits/30d) — sub-millisecond VM sandboxes via COW forking
- **capsule** (225 stars) — WebAssembly isolation

### Policy enforcement & guardrails
- **Microsoft agent-governance-toolkit** (61/100, 47 stars) — the only repo claiming full OWASP Agentic Top 10 coverage. Policy enforcement, zero-trust identity, execution sandboxing, reliability engineering. Our GSC click came from this page.
- **guardrails-ai/guardrails** (6.5K stars, llm-tools domain) — LLM output validation, PII filtering, hallucination detection. Cross-domain: works for agents but focused on LLM output layer.
- **agentcontrol/agent-control** (116 stars) — centralized agent control plane, runtime behavior governance at scale
- **DashClaw** (121 stars, 61/100) — decision infrastructure: intercept actions, enforce policies, audit trails
- **destructive_command_guard** (670 stars) — blocking dangerous shell/git commands from agents
- **aport-agent-guardrails** (15 stars) — pre-action authorization, works with OpenClaw/Claude Code/CrewAI

### Security scanning & auditing
- **agent-audit** (104 stars, 52/100) — static scanner, 49 rules mapped to OWASP Agentic Top 10, works with LangChain/CrewAI/AutoGen
- **AgentSeal** (119 stars, 66/100) — scan machine for dangerous skills, MCP configs, supply chain attacks
- **artguard** (24 stars) — AI artifact scanner for malicious skills, MCP servers, IDE rule files
- **agent-shield** (2 stars) — governance readiness scanner: EU AI Act, GDPR, OWASP, NIST AI RMF compliance scoring
- **cosai-oasis/secure-ai-tooling** (65 stars) — CoSAI risk map framework

### Observability & monitoring (governance through visibility)
- **TruLens** (77/100, 3.2K stars) — evaluation and tracking for LLM experiments and agents
- **AgentOps** (66/100, 5.4K stars) — agent monitoring, cost tracking, benchmarking
- **coze-loop** (64/100, 5.4K stars) — next-gen agent optimization, full lifecycle from debug to monitoring
- **Tracecat** (64/100, 3.5K stars, 238 commits/30d) — AI-native security automation, built for agents
- **agentwatch** (CyberArk, 109 stars) — observability framework for agent interactions

### OWASP & standards
- **precize/Agentic-AI-Top10-Vulnerability** (175 stars) — the OWASP Agentic Top 10 itself, core reference
- **NIST AI Agent Security** — federal comment request (HN: 49pts), formalizing agent security standards
- **kevlar-benchmark** (27 stars) — red team benchmark for OWASP Agentic Top 10

## Tier 2: Warning repos (popular but stale, or governance-washing)

- Most repos in agent-governance-frameworks (98 repos, avg quality 22.1) are spec documents or demo projects, not production tools
- agent-skill-security (64 repos, avg quality 23.8) is dominated by simple pattern matchers
- Many "guardrail" repos are single-rule wrappers around LLM calls, not real governance infrastructure

## Key narratives for the deep dive

### 1. The governance stack has layers
Not one tool but a stack: sandboxing (runtime isolation) → guardrails (pre-action authorization) → monitoring (observability) → auditing (compliance). Different layers are at different maturity levels.

### 2. Sandboxing is the only mature layer
Sandboxing has real adoption (E2B 11K stars, OpenSandbox 7.7K stars) and high quality scores. It's also where HN attention concentrates. This makes sense — isolation is the most tractable problem. You can sandbox first and figure out governance later.

### 3. Policy enforcement is early but accelerating
Microsoft's toolkit and agentcontrol are the emerging leaders. The OWASP Agentic Top 10 is creating a shared vocabulary that didn't exist 6 months ago. But most repos in this space are experimental.

### 4. The compliance gap is real
Only agent-shield (2 stars) even attempts EU AI Act/GDPR/NIST mapping. For enterprises that need to deploy agents in regulated environments, there's almost nothing. This is the biggest gap and the biggest opportunity.

### 5. Monitoring is mature but not governance-specific
AgentOps, TruLens, and coze-loop are excellent monitoring tools, but they're observability tools repurposed for governance, not purpose-built governance platforms. The gap is between "see what your agent did" and "prevent your agent from doing the wrong thing."

## HN community signal

The sandboxing conversation is the loudest (492pts for Agent Safehouse). The Ask HN posts ("Why are so many rolling out their own AI/LLM agent sandboxing solution?" and "The new wave of AI agent sandboxes?") show the community recognizing this space is fragmenting rapidly.

The NIST comment request (49pts) signals institutional interest. "AI agents are coming for government" from Fast Company confirms the enterprise/public sector angle.

## Cross-domain references

- **guardrails-ai/guardrails** (llm-tools domain, 6.5K stars) — the LLM output validation layer. Not agent-specific but foundational.
- **SWE-agent** (agents domain, 18.7K stars) — the offensive side, showing why governance matters. NeurIPS 2024.

## Featured categories for manifest

- agents:agent-authorization-guardrails (250 repos)
- agents:agent-code-sandboxing (114 repos)
- agents:agent-governance-frameworks (98 repos)
- agents:ai-agent-vulnerability-scanning (106 repos)
- agents:agent-observability-debugging (124 repos)
- agents:agent-reliability-engineering (34 repos)
- agents:agent-credential-security (80 repos)
