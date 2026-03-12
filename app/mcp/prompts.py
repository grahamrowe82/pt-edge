"""MCP Prompts — compound query workflows packaged as one-click starting points."""

from app.mcp.instance import mcp


@mcp.prompt(name="evaluate-technology")
async def evaluate_technology(topic: str) -> list[dict]:
    """Which technology should I use? Systematic evaluation of tools,
    frameworks, or approaches in a specific AI domain.

    Args:
        topic: The domain to evaluate (e.g. "agent framework", "vector database")
    """
    return [
        {
            "role": "user",
            "content": f"""Evaluate the "{topic}" landscape using PT-Edge tools. Follow this workflow:

**Step 1 — Quantitative comparison**
Call compare() with the top 3-5 known projects in this space. If more than 5, split into batches and run in parallel.

**Step 2 — Hype reality check**
For any project with surprisingly high stars or low downloads, call hype_check() to get the stars-vs-downloads ratio.

**Step 3 — Ecosystem depth** (run these 3 in parallel)
- find_model("{topic}") — HuggingFace models built for/on these tools
- find_mcp_server("{topic}") — MCP ecosystem adoption
- find_ai_tool("{topic}") — catch entrants you don't already know about

**Step 4 — Community sentiment**
Call hn_pulse("{topic}") for practitioner discourse. Look for complaints, praise, and migration signals.

**Step 5 — Synthesize**
Combine into a recommendation covering:
- Position (stars, downloads, tier)
- Trajectory (momentum)
- Hype vs reality (hype ratio)
- Ecosystem (models, MCP servers, dependents)
- Sentiment (HN discourse)

Highlight SURPRISES — newcomers outpacing incumbents, invisible infrastructure with massive adoption, or popular projects with fading momentum.

Run the full chain, then synthesize once at the end. Do not narrate each tool call.""",
        }
    ]


@mcp.prompt(name="build-something")
async def build_something(task: str) -> list[dict]:
    """I need to build X. Discovers frameworks, APIs, models, datasets,
    and MCP servers relevant to an implementation task.

    Args:
        task: What you want to build (e.g. "RAG pipeline", "MCP server for Postgres")
    """
    return [
        {
            "role": "user",
            "content": f"""I need to build: "{task}". Use PT-Edge to find everything I need.

**Step 1 — Parallel discovery sweep** (run ALL 5 simultaneously)
- find_ai_tool("{task}") — frameworks and libraries
- find_public_api("{task}") — REST APIs with OpenAPI specs
- find_model("{task}") — HuggingFace models for the task
- find_dataset("{task}") — training/eval data if relevant
- find_mcp_server("{task}") — existing MCP servers to reuse or learn from

**Step 2 — Deep dive on best candidates** (sequential, based on Step 1)
For the most promising API:
- get_api_spec(provider) — fetch the OpenAPI overview
- get_api_endpoints(provider, path_filter) — endpoint schemas for code generation

For the most promising framework/library:
- get_dependencies(repo) — check dependency weight

**Step 3 — Synthesize a recommended stack**
For each layer, recommend the best option with evidence:
- Core framework/library (why this one?)
- Data source / API (integration story)
- Model (if applicable — size, license, quality tradeoffs)
- Infrastructure (hosting, scaling)

Include dependency counts, license info, and red flags (stale repos, heavy deps).

Run the full pipeline, then present the complete recommended stack.""",
        }
    ]


@mcp.prompt(name="due-diligence")
async def due_diligence(project: str) -> list[dict]:
    """Should we adopt project X? Comprehensive health check covering metrics,
    hype vs reality, ecosystem position, and community sentiment.

    Args:
        project: Project name or slug to evaluate (e.g. "langchain", "fastapi")
    """
    return [
        {
            "role": "user",
            "content": f"""Run due diligence on "{project}" using PT-Edge.

**Step 1 — Full profile**
Call project_pulse("{project}") for the complete snapshot: stars, downloads, releases, tier, lifecycle, contributors, and activity.

**Step 2 — Hype reality check**
Call hype_check("{project}") — is this project's reputation earned or inflated?

**Step 3 — Ecosystem position** (run in parallel)
- related("{project}") — what projects appear alongside it in HN discussions?
- find_dependents("{project}") — who depends on this package in production?

**Step 4 — Community sentiment**
Call hn_pulse("{project}") for practitioner discourse. Look for:
- Recurring complaints or pain points
- Migration patterns (people moving to or away from it)
- Maintainer responsiveness
- Enterprise adoption signals

**Step 5 — Verdict**
Synthesize into an adoption recommendation:

HEALTH: Actively maintained? Release cadence? Contributor trend?
ADOPTION: Real downloads vs star count? Who depends on it?
ECOSYSTEM: What complements it? What competes?
SENTIMENT: What do practitioners love/hate?
RISK: Bus factor, funding, license, breaking changes?

Give a clear GO / CAUTION / AVOID recommendation with reasoning.

Run the full chain, then deliver the verdict.""",
        }
    ]


@mcp.prompt(name="weekly-briefing")
async def weekly_briefing() -> list[dict]:
    """What happened in AI this week? Comprehensive briefing covering releases,
    growth trends, emerging signals, and community discourse.
    """
    return [
        {
            "role": "user",
            "content": """Generate a weekly AI briefing using PT-Edge.

**Step 1 — What shipped** (run in parallel)
- whats_new(days=7) — releases, trending projects, HN discussion
- trending(window="7d") — top 20 by star growth
- radar() — untracked projects gaining attention

**Step 2 — Momentum shifts**
- movers(window="7d") — biggest accelerations and decelerations

**Step 3 — Community pulse**
- hn_pulse() — what the HN community is buzzing about

**Step 4 — Synthesize the briefing**

HEADLINE: Single most important development this week (1 sentence)

WHAT SHIPPED: Notable releases and launches (3-5 bullets)

MOMENTUM SHIFTS: Projects accelerating or decelerating (with why)

EMERGING SIGNALS: Things from radar() not widely known yet

COMMUNITY DISCOURSE: Key themes from HN — what practitioners debate

WORTH WATCHING: 2-3 things to keep an eye on next week

Keep it concise. Prioritize signal over noise. Highlight surprises.""",
        }
    ]


# ---------------------------------------------------------------------------
# Registry for JSON-RPC handler
# ---------------------------------------------------------------------------

PROMPTS = [
    {
        "name": "evaluate-technology",
        "description": "Which technology should I use? Systematic evaluation workflow.",
        "arguments": [
            {"name": "topic", "description": "The domain to evaluate (e.g. 'agent framework', 'vector database')", "required": True},
        ],
    },
    {
        "name": "build-something",
        "description": "I need to build X. Discovers frameworks, APIs, models, datasets, and MCP servers.",
        "arguments": [
            {"name": "task", "description": "What you want to build (e.g. 'RAG pipeline', 'MCP server for Postgres')", "required": True},
        ],
    },
    {
        "name": "due-diligence",
        "description": "Should we adopt project X? Comprehensive health and adoption check.",
        "arguments": [
            {"name": "project", "description": "Project name or slug to evaluate (e.g. 'langchain', 'fastapi')", "required": True},
        ],
    },
    {
        "name": "weekly-briefing",
        "description": "What happened in AI this week? Releases, trends, and discourse.",
        "arguments": [],
    },
]

_PROMPT_HANDLERS = {
    "evaluate-technology": evaluate_technology,
    "build-something": build_something,
    "due-diligence": due_diligence,
    "weekly-briefing": weekly_briefing,
}


async def get_prompt(name: str, arguments: dict) -> dict:
    """Dispatch a prompt get by name. Returns MCP-formatted result."""
    handler = _PROMPT_HANDLERS.get(name)
    if not handler:
        return {"messages": [], "description": f"Unknown prompt: {name}"}
    messages = await handler(**arguments)
    return {"messages": messages}
