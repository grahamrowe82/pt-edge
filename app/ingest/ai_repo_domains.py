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
    "perception": {
        "topics": ["web-scraping", "browser-automation", "web-crawler", "web-crawling", "scraping"],
        "min_stars": 2,
    },
    "rag": {
        "topics": ["rag", "retrieval-augmented-generation"],
        "min_stars": 0,
    },
    "ai-coding": {
        "topics": ["ai-coding", "code-generation", "copilot", "code-assistant"],
        "min_stars": 0,
    },
    "llm-tools": {
        "topics": ["llm", "large-language-models", "langchain", "gpt", "chatgpt"],
        "min_stars": 3,
    },
    "diffusion": {
        "topics": ["stable-diffusion", "diffusion-models", "text-to-image", "image-generation"],
        "min_stars": 2,
    },
    "voice-ai": {
        "topics": ["text-to-speech", "speech-recognition", "voice-ai", "tts", "asr"],
        "min_stars": 2,
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
    "nlp": {
        "topics": ["nlp", "natural-language-processing", "text-classification", "named-entity-recognition"],
        "min_stars": 3,
    },
    "computer-vision": {
        "topics": ["computer-vision", "object-detection", "image-segmentation"],
        "min_stars": 3,
    },
    "transformers": {
        "topics": ["transformers", "llama"],
        "min_stars": 2,
    },
    "mlops": {
        "topics": ["mlops", "experiment-tracking", "model-serving"],
        "min_stars": 2,
    },
    "data-engineering": {
        "topics": ["data-pipeline", "etl", "data-engineering", "feature-store"],
        "min_stars": 3,
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
    "perception",
    "ai-coding",
    "prompt-engineering",
    "diffusion",
    "voice-ai",
    "nlp",
    "computer-vision",
    "transformers",
    "llm-tools",
    "generative-ai",
    "mlops",
    "data-engineering",
    "ml-frameworks",
]

# Manual domain overrides for known misclassifications.
# Key: (github_owner, github_repo) → correct domain.
DOMAIN_OVERRIDES: dict[tuple[str, str], str] = {
    ("ollama", "ollama"): "llm-tools",
    ("run-llama", "llama_index"): "rag",
    ("mlflow", "mlflow"): "mlops",
    ("iterative", "dvc"): "data-engineering",
    ("dagster-io", "dagster"): "data-engineering",
    ("PrefectHQ", "prefect"): "data-engineering",
    ("deepseek-ai", "DeepSeek-V3"): "transformers",
    ("deepseek-ai", "DeepSeek-R1"): "transformers",
    # perception
    ("browser-use", "browser-use"): "perception",
    ("unclecode", "crawl4ai"): "perception",
    ("D4Vinci", "Scrapling"): "perception",
    ("firecrawl", "firecrawl"): "perception",
    ("Skyvern-AI", "skyvern"): "perception",
    ("Panniantong", "Agent-Reach"): "perception",
    # ai-coding
    ("Aider-AI", "aider"): "ai-coding",
    ("cline", "cline"): "ai-coding",
    ("continuedev", "continue"): "ai-coding",
    ("stackblitz-labs", "bolt.diy"): "ai-coding",
    # mlops
    ("wandb", "wandb"): "mlops",
    ("ray-project", "ray"): "mlops",
    # voice-ai
    ("openai", "whisper"): "voice-ai",
    # diffusion
    ("Stability-AI", "generative-models"): "diffusion",
    ("black-forest-labs", "flux"): "diffusion",
}
