"""API documentation page rendered from templates/api_docs.html."""

import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

router = APIRouter(tags=["docs"])

# Jinja2 environment for rendering the docs template
_template_dir = os.path.join(os.path.dirname(__file__), "..", "..", "templates")
_env = Environment(loader=FileSystemLoader(_template_dir), autoescape=False)

# Directory nav links (same as generate_site.py DIRECTORIES)
_DIRECTORIES = [
    {"path": "/", "label": "MCP", "domain": "mcp"},
    {"path": "/agents/", "label": "Agents", "domain": "agents"},
    {"path": "/rag/", "label": "RAG", "domain": "rag"},
    {"path": "/ai-coding/", "label": "AI Coding", "domain": "ai-coding"},
    {"path": "/voice-ai/", "label": "Voice AI", "domain": "voice-ai"},
    {"path": "/diffusion/", "label": "Diffusion", "domain": "diffusion"},
    {"path": "/vector-db/", "label": "Vector DB", "domain": "vector-db"},
    {"path": "/embeddings/", "label": "Embeddings", "domain": "embeddings"},
    {"path": "/prompt-engineering/", "label": "Prompts", "domain": "prompt-engineering"},
    {"path": "/ml-frameworks/", "label": "ML Frameworks", "domain": "ml-frameworks"},
    {"path": "/llm-tools/", "label": "LLM Tools", "domain": "llm-tools"},
    {"path": "/nlp/", "label": "NLP", "domain": "nlp"},
    {"path": "/transformers/", "label": "Transformers", "domain": "transformers"},
    {"path": "/generative-ai/", "label": "Gen AI", "domain": "generative-ai"},
    {"path": "/computer-vision/", "label": "CV", "domain": "computer-vision"},
    {"path": "/data-engineering/", "label": "Data Eng", "domain": "data-engineering"},
    {"path": "/mlops/", "label": "MLOps", "domain": "mlops"},
    {"path": "/perception/", "label": "Perception", "domain": "perception"},
]


@router.get("/api/docs", response_class=HTMLResponse)
async def api_docs():
    html = _env.get_template("api_docs.html").render(
        base_path="",
        base_url="https://mcp.phasetransitions.ai",
        domain="api",
        domain_label="API",
        domain_label_plural="API Endpoints",
        noun="endpoint",
        noun_plural="endpoints",
        global_total="220,000+",
        directories=_DIRECTORIES,
    )
    return HTMLResponse(content=html)
