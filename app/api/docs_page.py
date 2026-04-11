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
    {"path": "/llm-inference/", "label": "LLM Inference", "domain": "llm-inference"},
    {"path": "/ai-evals/", "label": "AI Evals", "domain": "ai-evals"},
    {"path": "/fine-tuning/", "label": "Fine-Tuning", "domain": "fine-tuning"},
    {"path": "/document-ai/", "label": "Document AI", "domain": "document-ai"},
    {"path": "/ai-safety/", "label": "AI Safety", "domain": "ai-safety"},
    {"path": "/recommendation-systems/", "label": "RecSys", "domain": "recommendation-systems"},
    {"path": "/audio-ai/", "label": "Audio AI", "domain": "audio-ai"},
    {"path": "/synthetic-data/", "label": "Synthetic Data", "domain": "synthetic-data"},
    {"path": "/time-series/", "label": "Time Series", "domain": "time-series"},
    {"path": "/multimodal/", "label": "Multimodal", "domain": "multimodal"},
    {"path": "/3d-ai/", "label": "3D AI", "domain": "3d-ai"},
    {"path": "/scientific-ml/", "label": "Scientific ML", "domain": "scientific-ml"},
]


_COMMON_CONTEXT = dict(
    base_path="",
    base_url="https://mcp.phasetransitions.ai",
    noun="endpoint",
    noun_plural="endpoints",
    global_total="220,000+",
    directories=_DIRECTORIES,
)


@router.get("/api/docs", response_class=HTMLResponse)
async def api_docs():
    html = _env.get_template("api_docs.html").render(
        **_COMMON_CONTEXT,
        domain="api",
        domain_label="API",
        domain_label_plural="API Endpoints",
    )
    return HTMLResponse(content=html)


@router.get("/mcp/docs", response_class=HTMLResponse)
async def mcp_docs():
    html = _env.get_template("mcp_docs.html").render(
        **_COMMON_CONTEXT,
        domain="mcp",
        domain_label="MCP",
        domain_label_plural="MCP Tools",
    )
    return HTMLResponse(content=html)


@router.get("/cli/docs", response_class=HTMLResponse)
async def cli_docs():
    html = _env.get_template("cli_docs.html").render(
        **_COMMON_CONTEXT,
        domain="cli",
        domain_label="CLI",
        domain_label_plural="CLI Commands",
    )
    return HTMLResponse(content=html)
