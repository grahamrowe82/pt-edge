"""Domain configuration for AI repo discovery.

Each domain maps to:
  - topics: GitHub topic queries (each becomes `topic:<name>`)
  - min_stars: minimum star threshold (filters noise for massive topics)
"""

DOMAINS: dict[str, dict] = {
    "mcp": {
        "topics": ["mcp-server", "model-context-protocol"],
        "min_stars": 0,
    },
    "agents": {
        "topics": ["ai-agents", "ai-agent", "multi-agent"],
        "min_stars": 0,
    },
    "rag": {
        "topics": ["rag", "retrieval-augmented-generation"],
        "min_stars": 0,
    },
    "llm-tools": {
        "topics": ["llm", "large-language-models", "langchain", "gpt", "chatgpt"],
        "min_stars": 3,
    },
    "generative-ai": {
        "topics": ["generative-ai", "genai"],
        "min_stars": 0,
    },
    "embeddings": {
        "topics": ["embeddings", "semantic-search"],
        "min_stars": 0,
    },
    "vector-db": {
        "topics": ["vector-database"],
        "min_stars": 0,
    },
    "prompt-engineering": {
        "topics": ["prompt-engineering"],
        "min_stars": 0,
    },
    "transformers": {
        "topics": ["transformers", "llama"],
        "min_stars": 2,
    },
    "ml-frameworks": {
        "topics": ["machine-learning", "deep-learning", "artificial-intelligence"],
        "min_stars": 5,
    },
}

# Ordered from most specific to most general — controls domain assignment priority.
# When a repo appears in multiple domains, the first domain to claim it wins.
DOMAIN_ORDER: list[str] = [
    "mcp",
    "vector-db",
    "embeddings",
    "rag",
    "agents",
    "prompt-engineering",
    "transformers",
    "llm-tools",
    "generative-ai",
    "ml-frameworks",
]
