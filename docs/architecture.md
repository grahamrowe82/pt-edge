# Architecture

## Three-Layer Ecosystem Model

The AI ecosystem has three layers, not one supply chain. Each layer iterates at a different speed.

### Layer 1: Models (quarterly)
Makes tokens. Labs compete here. GPT-5.4, Claude Opus 4.6, Gemini 3.1 Pro, Llama 4. This is what benchmarks measure and what gets HN points. Major releases every 2-8 weeks per lab.

### Layer 2: Tools (weekly)
Makes tokens useful. Cursor, Claude Code, Windsurf, Cline, Aider. These determine how much of a model's capability actually gets extracted by a user. A model might score 57 on an intelligence index but if the tool doesn't scaffold the interaction correctly, the user gets 30% of that capability. New capabilities every 1-2 weeks per tool.

### Layer 3: Meta (daily/continuous)
Makes tools better. everything-claude-code, claude-mem, awesome-claude-skills, skills files, memory configurations. This is where practitioners encode what works. The meta-ecosystem around Claude Code alone is 273K+ stars across 4+ major projects. 10+ commits/day.

### Key Dynamics

**The causal arrow runs backwards.** The meta-layer drives tool improvement drives model demand — not just models -> tools -> users. The AI-builds-AI loop is happening at the tool layer: Claude Code -> developers build extensions -> extensions make Claude Code more effective -> next round builds faster.

**The 69:1 engineering ratio.** Labs produce 596 commits/month. The independent ecosystem produces 40,933 commits/month. The value creation is overwhelmingly in the ecosystem, not the labs. The ecosystem's pace of iteration — not benchmark scores — determines how fast AI gets more useful in practice.

**Iteration velocity differential.** The bottleneck in AI capability is rarely the model. Infrastructure moves 10-50x faster than models, tools move 5-10x faster, and the meta-layer is continuous. Practical advice: upgrade your tools and infrastructure first, you'll get more capability per unit of effort than upgrading models.

## Data Flow

```
Ingest Sources
├── GitHub/PyPI/npm/conda    → engineering signals (stars, downloads, commits, releases)
├── HN Algolia               → Western developer discourse
├── V2EX                     → Chinese developer discourse
├── Newsletter RSS           → editorial consensus (Zvi, Simon Willison, Latent Space,
│                               Ethan Mollick, Ben Evans, Pragmatic Engineer)
├── Lab blogs/changelogs     → what labs are shipping (OpenAI, Google AI)
└── Docker Hub               → container pull counts
         │
         ▼
    Postgres DB ──────────────────────────────────────────┐
    (single source of truth)                              │
         │                                                │
         ├── MCP Server ──► Claude sessions query live    │
         │                                                │
         ├── Evidence.dev ──► phasetransitions.ai         │
         │   dashboards + living guidebook                │
         │                                                │
         ├── Newsletter ──► curated weekly editorial      │
         │                                                │
         └── Consulting ──► Graham Road engagements       │
                                                          │
    Embeddings (pgvector, text-embedding-3-large)         │
    ├── Projects: name + description + topics             │
    ├── Methodology: title + summary                      │
    └── Newsletter topics: title + summary + mentions ────┘
```

## Causal Signals (Not Yet Built)

Two signals that exist in PT-Edge's data but aren't yet connected:

### Downstream Velocity
When a lab ships, how fast does the ecosystem respond? The data exists across `whats_new` (release timestamps) and `lab_pulse` (event timestamps). The fix is a join: for each lab Key Event, find all tracked project releases within 48-72 hours and flag them as "probable responses." A model launch that triggers 6 downstream patches in 48 hours is more consequential than one that triggers 1 patch in a week.

### Competitive Collision
When a lab ships a feature, which tracked projects are threatened? GPT-5.4's Tool Search vs LangChain's tool routing, Claude's built-in memory vs Mem0, OpenAI's computer use vs browser automation agents. Semantic embeddings can detect this: embed the lab event description and match against tracked project descriptions. High similarity = competitive exposure.

## Platform Gravity (Not Yet Built)

For each major tool, aggregate the stars and commits of all community projects that reference it. The tool with the largest meta-ecosystem has the strongest network effect, regardless of its own install numbers. Cursor might have more users than Claude Code, but if Claude Code has 3x the community extension ecosystem, it's the stronger platform bet.

---

*Sourced from feedback items #47, #48, #49, #50, #51, #52, #63. Resolved from active feedback on 2026-03-09.*
