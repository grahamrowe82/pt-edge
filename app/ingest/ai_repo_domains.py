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
    # --- New domains (added 2026-04-07) ---
    "llm-inference": {
        "topics": ["llm-inference", "model-serving", "llm-server", "inference-engine", "gguf", "ollama"],
        "min_stars": 3,
    },
    "ai-evals": {
        "topics": ["llm-evaluation", "ai-evaluation", "benchmarking", "llm-observability", "ai-observability", "tracing"],
        "min_stars": 2,
    },
    "fine-tuning": {
        "topics": ["fine-tuning", "finetuning", "lora", "qlora", "peft", "llm-finetuning"],
        "min_stars": 2,
    },
    "document-ai": {
        "topics": ["ocr", "document-parsing", "pdf-extraction", "document-ai", "table-extraction", "pdf-to-text"],
        "min_stars": 2,
    },
    "ai-safety": {
        "topics": ["guardrails", "ai-safety", "llm-security", "red-teaming", "adversarial-robustness", "content-moderation"],
        "min_stars": 2,
    },
    "recommendation-systems": {
        "topics": ["recommender-system", "collaborative-filtering", "recommendation-engine", "content-based-filtering"],
        "min_stars": 3,
    },
    "audio-ai": {
        "topics": ["audio-generation", "music-generation", "audio-classification", "source-separation", "sound-event-detection"],
        "min_stars": 2,
    },
    "synthetic-data": {
        "topics": ["synthetic-data", "data-augmentation", "data-generation", "synthetic-data-generation"],
        "min_stars": 3,
    },
    "time-series": {
        "topics": ["time-series", "forecasting", "time-series-analysis", "time-series-forecasting"],
        "min_stars": 3,
    },
    "multimodal": {
        "topics": ["multimodal", "vision-language", "vlm", "multimodal-learning"],
        "min_stars": 3,
    },
    "3d-ai": {
        "topics": ["nerf", "gaussian-splatting", "3d-reconstruction", "point-cloud", "3d-generation"],
        "min_stars": 2,
    },
    "scientific-ml": {
        "topics": ["physics-informed-neural-networks", "scientific-computing", "neural-operator", "computational-biology"],
        "min_stars": 3,
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
    "llm-inference",
    "fine-tuning",
    "ai-evals",
    "ai-safety",
    "document-ai",
    "3d-ai",
    "audio-ai",
    "prompt-engineering",
    "diffusion",
    "voice-ai",
    "recommendation-systems",
    "time-series",
    "synthetic-data",
    "multimodal",
    "scientific-ml",
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
    # scientific computing misclassified as ai-coding
    ("casadi", "casadi"): "ml-frameworks",
    ("brian-team", "brian2"): "ml-frameworks",
    ("devitocodes", "devito"): "ml-frameworks",
    # foundational seeds — pinned domains (see FOUNDATIONAL_SEEDS below)
    ("openai", "openai-python"): "llm-tools",
    ("anthropics", "anthropic-sdk-python"): "llm-tools",
    ("openai", "tiktoken"): "llm-tools",
    ("pydantic", "pydantic"): "llm-tools",
    ("tiangolo", "fastapi"): "ml-frameworks",
    ("encode", "uvicorn"): "ml-frameworks",
    ("encode", "httpx"): "ml-frameworks",
    ("tiangolo", "typer"): "ml-frameworks",
    ("Textualize", "rich"): "ml-frameworks",
    ("pallets", "click"): "ml-frameworks",
    ("python-pillow", "Pillow"): "computer-vision",
    ("modelcontextprotocol", "python-sdk"): "mcp",
    ("modelcontextprotocol", "typescript-sdk"): "mcp",
    ("Farama-Foundation", "Gymnasium"): "ml-frameworks",
    ("microsoft", "LightGBM"): "ml-frameworks",
    ("dmlc", "xgboost"): "ml-frameworks",
    ("cohere-ai", "cohere-python"): "llm-tools",
    ("groq", "groq-python"): "llm-tools",
    ("mistralai", "client-python"): "llm-tools",
    ("google-gemini", "generative-ai-python"): "llm-tools",
    ("Dao-AILab", "flash-attention"): "transformers",
    ("facebookresearch", "faiss"): "vector-db",
    ("omni-us", "jsonargparse"): "ml-frameworks",
    ("omegaconf", "omegaconf"): "ml-frameworks",
    ("Lightning-AI", "pytorch-lightning"): "ml-frameworks",
    ("joblib", "joblib"): "ml-frameworks",
}

# Foundational AI infrastructure repos that aren't discovered by topic search
# but are heavily depended on by repos in the dataset.
# Format: (owner, repo, domain, pypi_package, npm_package)
FOUNDATIONAL_SEEDS: list[tuple[str, str, str, str | None, str | None]] = [
    # LLM provider SDKs
    ("openai", "openai-python", "llm-tools", "openai", None),
    ("anthropics", "anthropic-sdk-python", "llm-tools", "anthropic", None),
    ("cohere-ai", "cohere-python", "llm-tools", "cohere", None),
    ("groq", "groq-python", "llm-tools", "groq", None),
    ("mistralai", "client-python", "llm-tools", "mistralai", None),
    ("google-gemini", "generative-ai-python", "llm-tools", "google-generativeai", None),
    ("openai", "tiktoken", "llm-tools", "tiktoken", None),
    # MCP SDKs
    ("modelcontextprotocol", "python-sdk", "mcp", "mcp", None),
    ("modelcontextprotocol", "typescript-sdk", "mcp", None, "@modelcontextprotocol/sdk"),
    # Core AI frameworks
    ("pydantic", "pydantic", "llm-tools", "pydantic", None),
    ("tiangolo", "fastapi", "ml-frameworks", "fastapi", None),
    ("encode", "uvicorn", "ml-frameworks", "uvicorn", None),
    ("encode", "httpx", "ml-frameworks", "httpx", None),
    ("tiangolo", "typer", "ml-frameworks", "typer", None),
    ("Textualize", "rich", "ml-frameworks", "rich", None),
    ("pallets", "click", "ml-frameworks", "click", None),
    ("python-pillow", "Pillow", "computer-vision", "pillow", None),
    ("huggingface", "huggingface_hub", "ml-frameworks", "huggingface-hub", None),
    # ML infrastructure
    ("Farama-Foundation", "Gymnasium", "ml-frameworks", "gymnasium", None),
    ("microsoft", "LightGBM", "ml-frameworks", "lightgbm", None),
    ("dmlc", "xgboost", "ml-frameworks", "xgboost", None),
    ("Lightning-AI", "pytorch-lightning", "ml-frameworks", "pytorch-lightning", None),
    ("Dao-AILab", "flash-attention", "transformers", "flash-attn", None),
    ("facebookresearch", "faiss", "vector-db", "faiss-cpu", None),
    ("omni-us", "jsonargparse", "ml-frameworks", "jsonargparse", None),
    ("omegaconf", "omegaconf", "ml-frameworks", "omegaconf", None),
    ("joblib", "joblib", "ml-frameworks", "joblib", None),
]
