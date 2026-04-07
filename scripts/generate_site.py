"""Generate static AI directory site.

Usage:
    python scripts/generate_site.py [--domain mcp] [--output-dir ./site] [--base-url https://mcp.phasetransitions.ai]

Queries the domain's quality materialized view and renders Jinja2 templates
to static HTML files. Supports: mcp, agents, rag, ai-coding.
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import numpy as np
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import text

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.db import engine, readonly_engine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_QUALITY_SCORE = 10
PER_PAGE = 100

DOMAIN_CONFIG = {
    "mcp": {
        "view": "mv_mcp_quality",
        "snapshot_table": "mcp_quality_snapshots",
        "snapshot_domain_filter": None,
        "label": "MCP Server",
        "label_plural": "MCP Servers",
        "noun": "server",
        "noun_plural": "servers",
        "description": "Quality-scored directory of MCP servers, updated daily.",
        "explainer": "The Model Context Protocol (MCP) lets AI assistants connect to external tools and services. This directory tracks every MCP server on GitHub, scored daily.",
    },
    "agents": {
        "view": "mv_agents_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "agents",
        "label": "AI Agent",
        "label_plural": "AI Agents",
        "noun": "agent",
        "noun_plural": "agents",
        "description": "Quality-scored directory of AI agent frameworks and tools, updated daily.",
        "explainer": "AI agents are autonomous systems that plan, reason, and execute multi-step tasks using LLMs. This directory tracks agent frameworks, SDKs, and tools.",
    },
    "rag": {
        "view": "mv_rag_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "rag",
        "label": "RAG",
        "label_plural": "RAG Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of retrieval-augmented generation tools, updated daily.",
        "explainer": "Retrieval-augmented generation (RAG) combines LLMs with external knowledge sources for more accurate, grounded responses.",
    },
    "ai-coding": {
        "view": "mv_ai_coding_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "ai-coding",
        "label": "AI Coding",
        "label_plural": "AI Coding Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of AI-powered coding tools, updated daily.",
        "explainer": "AI coding tools assist with code generation, review, completion, and codebase navigation using large language models.",
    },
    "voice-ai": {
        "view": "mv_voice_ai_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "voice-ai",
        "label": "Voice AI",
        "label_plural": "Voice AI Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of voice AI tools — TTS, STT, voice agents, and audio processing.",
        "explainer": "Voice AI covers text-to-speech synthesis, speech recognition, voice cloning, voice agents, and audio processing.",
    },
    "diffusion": {
        "view": "mv_diffusion_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "diffusion",
        "label": "Diffusion",
        "label_plural": "Diffusion Models",
        "noun": "model",
        "noun_plural": "models",
        "description": "Quality-scored directory of diffusion models and image generation tools.",
        "explainer": "Diffusion models generate images, video, and 3D content from text prompts. Includes Stable Diffusion, ComfyUI workflows, and fine-tuning tools.",
    },
    "vector-db": {
        "view": "mv_vector_db_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "vector-db",
        "label": "Vector Database",
        "label_plural": "Vector Databases",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of vector databases and similarity search tools.",
        "explainer": "Vector databases store and query high-dimensional embeddings for semantic search, RAG pipelines, and recommendation systems.",
    },
    "embeddings": {
        "view": "mv_embeddings_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "embeddings",
        "label": "Embeddings",
        "label_plural": "Embedding Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of embedding models, servers, and utilities.",
        "explainer": "Embedding models convert text, images, and code into dense vector representations for search, clustering, and similarity.",
    },
    "prompt-engineering": {
        "view": "mv_prompt_eng_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "prompt-engineering",
        "label": "Prompt Engineering",
        "label_plural": "Prompt Engineering Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of prompt engineering tools, frameworks, and libraries.",
        "explainer": "Prompt engineering tools help design, optimise, and manage prompts for large language models — including frameworks, guardrails, and output parsers.",
    },
    "ml-frameworks": {
        "view": "mv_ml_frameworks_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "ml-frameworks",
        "label": "ML Framework",
        "label_plural": "ML Frameworks",
        "noun": "framework",
        "noun_plural": "frameworks",
        "description": "Quality-scored directory of machine learning frameworks, training libraries, and ML infrastructure.",
        "explainer": "ML frameworks provide the foundational libraries for training, evaluating, and deploying machine learning models.",
    },
    "llm-tools": {
        "view": "mv_llm_tools_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "llm-tools",
        "label": "LLM Tool",
        "label_plural": "LLM Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of large language model tools, wrappers, and utilities.",
        "explainer": "LLM tools include API wrappers, fine-tuning utilities, inference servers, and evaluation frameworks for large language models.",
    },
    "nlp": {
        "view": "mv_nlp_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "nlp",
        "label": "NLP",
        "label_plural": "NLP Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of natural language processing tools and libraries.",
        "explainer": "NLP tools process and analyse human language — text classification, named entity recognition, translation, summarisation, and more.",
    },
    "transformers": {
        "view": "mv_transformers_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "transformers",
        "label": "Transformer",
        "label_plural": "Transformer Models",
        "noun": "model",
        "noun_plural": "models",
        "description": "Quality-scored directory of transformer models, fine-tuning tools, and inference engines.",
        "explainer": "Transformer models and tools for fine-tuning, quantisation, inference optimisation, and deployment of attention-based architectures.",
    },
    "generative-ai": {
        "view": "mv_generative_ai_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "generative-ai",
        "label": "Generative AI",
        "label_plural": "Generative AI Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of generative AI tools, chatbots, and content generation.",
        "explainer": "Generative AI tools create text, images, audio, and other content using foundation models — chatbots, content generators, and creative tools.",
    },
    "computer-vision": {
        "view": "mv_computer_vision_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "computer-vision",
        "label": "Computer Vision",
        "label_plural": "Computer Vision Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of computer vision tools, models, and libraries.",
        "explainer": "Computer vision tools for image classification, object detection, segmentation, OCR, and visual understanding.",
    },
    "data-engineering": {
        "view": "mv_data_engineering_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "data-engineering",
        "label": "Data Engineering",
        "label_plural": "Data Engineering Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of data engineering tools, pipelines, and ETL frameworks.",
        "explainer": "Data engineering tools for building data pipelines, ETL workflows, data quality, and data infrastructure.",
    },
    "mlops": {
        "view": "mv_mlops_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "mlops",
        "label": "MLOps",
        "label_plural": "MLOps Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of MLOps tools for model deployment, monitoring, and lifecycle management.",
        "explainer": "MLOps tools for model deployment, monitoring, experiment tracking, and ML lifecycle management.",
    },
    "perception": {
        "view": "mv_perception_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "perception",
        "label": "Perception",
        "label_plural": "Perception Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of web scraping, browser automation, and data extraction tools for AI agents.",
        "explainer": "Perception tools give AI agents eyes and hands on the web — browser automation, web scraping, data extraction, and anti-detection infrastructure.",
    },
    # --- New domains (added 2026-04-07) ---
    "llm-inference": {
        "view": "mv_llm_inference_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "llm-inference",
        "label": "LLM Inference",
        "label_plural": "LLM Inference Engines",
        "noun": "engine",
        "noun_plural": "engines",
        "description": "Quality-scored directory of LLM inference engines and local model runners, updated daily.",
        "explainer": "LLM inference engines for self-hosted model serving — vLLM, TGI, SGLang, Ollama, llama.cpp, and the tools that make local inference fast and efficient.",
    },
    "ai-evals": {
        "view": "mv_ai_evals_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "ai-evals",
        "label": "AI Evals",
        "label_plural": "AI Evaluation Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of AI evaluation, benchmarking, and observability tools, updated daily.",
        "explainer": "Tools for evaluating, benchmarking, and observing AI systems — from LLM eval harnesses to production observability platforms like Langfuse and LangSmith.",
    },
    "fine-tuning": {
        "view": "mv_fine_tuning_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "fine-tuning",
        "label": "Fine-Tuning",
        "label_plural": "Fine-Tuning Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of LLM and model fine-tuning tools, updated daily.",
        "explainer": "Tools for fine-tuning language models and adapting pre-trained models — LoRA, QLoRA, PEFT adapters, and full fine-tuning frameworks like Unsloth and Axolotl.",
    },
    "document-ai": {
        "view": "mv_document_ai_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "document-ai",
        "label": "Document AI",
        "label_plural": "Document AI Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of document parsing, OCR, and data extraction tools, updated daily.",
        "explainer": "Document parsing and extraction tools for AI pipelines — OCR engines, PDF parsers, table extractors, and the plumbing that turns unstructured documents into structured data.",
    },
    "ai-safety": {
        "view": "mv_ai_safety_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "ai-safety",
        "label": "AI Safety",
        "label_plural": "AI Safety Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of AI safety, guardrails, and security tools, updated daily.",
        "explainer": "Guardrails, content filtering, red teaming, and adversarial robustness tools — the safety layer between AI models and production deployment.",
    },
    "recommendation-systems": {
        "view": "mv_recommendation_systems_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "recommendation-systems",
        "label": "RecSys",
        "label_plural": "Recommendation Systems",
        "noun": "library",
        "noun_plural": "libraries",
        "description": "Quality-scored directory of recommendation system libraries, updated daily.",
        "explainer": "Recommendation engines and collaborative filtering libraries — from classical matrix factorisation to deep learning recommenders and production frameworks.",
    },
    "audio-ai": {
        "view": "mv_audio_ai_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "audio-ai",
        "label": "Audio AI",
        "label_plural": "Audio AI Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of audio AI tools for music generation, source separation, and audio classification, updated daily.",
        "explainer": "Audio generation, music AI, source separation, and sound classification tools — distinct from speech/voice AI, focused on non-speech audio applications.",
    },
    "synthetic-data": {
        "view": "mv_synthetic_data_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "synthetic-data",
        "label": "Synthetic Data",
        "label_plural": "Synthetic Data Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of synthetic data generation and augmentation tools, updated daily.",
        "explainer": "Synthetic data generation, augmentation, and simulation tools — creating training data when real data is scarce, private, or expensive to label.",
    },
    "time-series": {
        "view": "mv_time_series_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "time-series",
        "label": "Time Series",
        "label_plural": "Time Series Tools",
        "noun": "library",
        "noun_plural": "libraries",
        "description": "Quality-scored directory of time series forecasting and analysis tools, updated daily.",
        "explainer": "Time series forecasting, anomaly detection, and classification libraries — from statistical models to neural forecasters and foundation models for temporal data.",
    },
    "multimodal": {
        "view": "mv_multimodal_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "multimodal",
        "label": "Multimodal",
        "label_plural": "Multimodal AI Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of multimodal AI and vision-language tools, updated daily.",
        "explainer": "Vision-language models, cross-modal retrieval, and multimodal learning tools — combining text, image, audio, and video understanding in unified systems.",
    },
    "3d-ai": {
        "view": "mv_3d_ai_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "3d-ai",
        "label": "3D AI",
        "label_plural": "3D AI Tools",
        "noun": "tool",
        "noun_plural": "tools",
        "description": "Quality-scored directory of 3D AI tools for NeRF, gaussian splatting, and 3D reconstruction, updated daily.",
        "explainer": "Neural radiance fields, gaussian splatting, point cloud processing, and 3D reconstruction tools — the spatial AI stack for building and understanding 3D worlds.",
    },
    "scientific-ml": {
        "view": "mv_scientific_ml_quality",
        "snapshot_table": "quality_snapshots",
        "snapshot_domain_filter": "scientific-ml",
        "label": "Scientific ML",
        "label_plural": "Scientific ML Tools",
        "noun": "library",
        "noun_plural": "libraries",
        "description": "Quality-scored directory of scientific machine learning tools, updated daily.",
        "explainer": "Physics-informed neural networks, neural operators, and computational science tools — bridging deep learning with physical laws and scientific simulation.",
    },
}

TIER_CLASSES = {
    "verified":     "bg-green-100 text-green-800",
    "established":  "bg-blue-100 text-blue-800",
    "emerging":     "bg-yellow-100 text-yellow-800",
    "experimental": "bg-gray-100 text-gray-600",
}

TIER_BAR_COLORS = {
    "verified":     "bg-green-500",
    "established":  "bg-blue-500",
    "emerging":     "bg-yellow-500",
    "experimental": "bg-gray-400",
}

TIER_RANGES = {
    "verified":     "70\u2013100",
    "established":  "50\u201369",
    "emerging":     "30\u201349",
    "experimental": "10\u201329",
}

DIRECTORIES = [
    {"path": "/servers/", "label": "MCP", "domain": "mcp"},
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

# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

def human_stars(n):
    """Format star count for titles: 1200 -> '1.2K', 84000 -> '84K'."""
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.1f}K".replace(".0K", "K")
    return str(n)


def tier_classes(tier):
    return TIER_CLASSES.get(tier, TIER_CLASSES["experimental"])

def tier_bar_color(tier):
    return TIER_BAR_COLORS.get(tier, TIER_BAR_COLORS["experimental"])

def score_bar_color(score, max_score):
    pct = (score or 0) / max_score if max_score else 0
    if pct >= 0.75:
        return "bg-green-500"
    if pct >= 0.5:
        return "bg-blue-500"
    if pct >= 0.25:
        return "bg-yellow-500"
    return "bg-gray-400"

def metrics_paragraph(server):
    """Build a dynamic metrics context paragraph from live data."""
    parts = []
    stars = server.get("stars") or 0
    downloads = server.get("downloads_monthly") or 0
    if stars >= 100 or downloads >= 1000:
        bits = []
        if stars:
            bits.append(f"{stars:,} stars")
        if downloads:
            bits.append(f"{downloads:,} monthly downloads")
        parts.append(" and ".join(bits))
    rev_deps = server.get("reverse_dep_count") or 0
    if rev_deps > 0:
        parts.append(f"Used by {rev_deps:,} other package{'s' if rev_deps != 1 else ''}")
    commits = server.get("commits_30d") or 0
    if commits > 0:
        parts.append(f"Actively maintained with {commits:,} commit{'s' if commits != 1 else ''} in the last 30 days")
    elif server.get("risk_flags") and "stale_6m" in server["risk_flags"]:
        parts.append("No commits in the last 6 months")
    pkgs = []
    if server.get("pypi_package"):
        pkgs.append("PyPI")
    if server.get("npm_package"):
        pkgs.append("npm")
    if pkgs:
        parts.append(f"Available on {' and '.join(pkgs)}")
    if not parts:
        return ""
    return ". ".join(parts) + "."

def decision_paragraph(category_label, servers, noun_plural):
    """Build a decision paragraph for a category page from live data."""
    count = len(servers)
    if count == 0:
        return ""
    verified = [s for s in servers if s.get("quality_tier") == "verified"]
    established = [s for s in servers if s.get("quality_tier") == "established"]
    top = servers[0]
    # Avoid "MongoDB MCP Servers servers" — don't append noun if already in label
    if noun_plural in category_label.lower():
        parts = [f"There are {count} {category_label.lower()} tracked."]
    else:
        parts = [f"There are {count} {category_label.lower()} {noun_plural} tracked."]
    if verified:
        parts.append(f"{len(verified)} score above 70 (verified tier).")
    elif established:
        parts.append(f"{len(established)} score above 50 (established tier).")
    parts.append(
        f"The highest-rated is {top['full_name']} at {int(top['quality_score'])}/100"
        f" with {top['stars'] or 0:,} stars"
        + (f" and {top['downloads_monthly'] or 0:,} monthly downloads" if top.get('downloads_monthly') else "")
        + "."
    )
    active = [s for s in servers[:10] if (s.get("commits_30d") or 0) > 0]
    if active:
        parts.append(f"{len(active)} of the top 10 are actively maintained.")
    return " ".join(parts)

# ---------------------------------------------------------------------------
# Data queries
# ---------------------------------------------------------------------------

def fetch_category_meta(domain):
    """Load display labels and scope definitions from category_centroids."""
    try:
        with readonly_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT label, display_label, description FROM category_centroids
                WHERE domain = :domain
            """), {"domain": domain}).fetchall()
        return {
            r._mapping["label"]: {
                "display_label": r._mapping["display_label"] or r._mapping["label"].replace("-", " ").title(),
                "desc": r._mapping["description"] or "",
            }
            for r in rows
        }
    except Exception:
        return {}

def fetch_global_total():
    """Total ai_repos count across all domains."""
    try:
        with readonly_engine.connect() as conn:
            return conn.execute(text("SELECT COUNT(*) FROM ai_repos")).scalar()
    except Exception:
        return 220000

def fetch_servers(view_name):
    """All qualifying repos from the given quality view."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT full_name, name, description, ai_summary,
                   problem_domains, use_this_if, not_ideal_if,
                   stars, forks,
                   language, license, archived, category, subcategory,
                   last_pushed_at, pypi_package, npm_package,
                   downloads_monthly, dependency_count, commits_30d,
                   reverse_dep_count,
                   maintenance_score, adoption_score, maturity_score, community_score,
                   quality_score, quality_tier, risk_flags
            FROM {view_name}
            WHERE quality_score >= :min_score
              AND description IS NOT NULL
              AND description != ''
            ORDER BY quality_score DESC NULLS LAST
        """), {"min_score": MIN_QUALITY_SCORE}).fetchall()
    results = []
    for r in rows:
        d = dict(r._mapping)
        if d.get("license") in ("NOASSERTION", ""):
            d["license"] = None
        results.append(d)
    return results


def fetch_repo_briefs(domain):
    """Repo briefs keyed by full_name for a given domain."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ar.full_name, rb.title, rb.summary, rb.evidence
            FROM repo_briefs rb
            JOIN ai_repos ar ON ar.id = rb.ai_repo_id
            WHERE ar.domain = :domain
        """), {"domain": domain}).fetchall()
    return {r.full_name: {"brief_title": r.title, "brief_summary": r.summary,
                          "brief_evidence": r.evidence} for r in rows}


def fetch_domain_brief(domain):
    """Landscape brief for a domain, or None."""
    with readonly_engine.connect() as conn:
        row = conn.execute(text("""
            SELECT title, summary, evidence
            FROM domain_briefs
            WHERE domain = :domain
        """), {"domain": domain}).fetchone()
    if row:
        return {"title": row.title, "summary": row.summary, "evidence": row.evidence}
    return None


def fetch_briefings(domain):
    """Recent briefings for a domain."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT slug, title, summary, updated_at
            FROM briefings
            WHERE domain = :domain
            ORDER BY updated_at DESC
            LIMIT 5
        """), {"domain": domain}).fetchall()
    return [{"slug": r.slug, "title": r.title, "summary": r.summary,
             "updated_at": r.updated_at} for r in rows]


def fetch_hn_posts(domain):
    """HN discussion posts keyed by full_name for a given domain."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ar.full_name, hp.hn_id, hp.title, hp.points, hp.num_comments,
                   hp.posted_at
            FROM hn_posts hp
            JOIN projects p ON hp.project_id = p.id
            JOIN ai_repos ar ON p.ai_repo_id = ar.id
            WHERE ar.domain = :domain
              AND hp.points > 0
            ORDER BY hp.points DESC
        """), {"domain": domain}).fetchall()
    lookup = {}
    for r in rows:
        lookup.setdefault(r.full_name, [])
        if len(lookup[r.full_name]) < 5:
            lookup[r.full_name].append({
                "hn_id": r.hn_id, "title": r.title,
                "points": r.points, "num_comments": r.num_comments,
                "posted_at": r.posted_at,
            })
    return lookup


def fetch_releases(domain):
    """Recent releases keyed by full_name for a given domain."""
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ar.full_name, r.version, r.title, r.url, r.released_at
            FROM releases r
            JOIN projects p ON r.project_id = p.id
            JOIN ai_repos ar ON p.ai_repo_id = ar.id
            WHERE ar.domain = :domain
            ORDER BY r.released_at DESC
        """), {"domain": domain}).fetchall()
    lookup = {}
    for r in rows:
        lookup.setdefault(r.full_name, [])
        if len(lookup[r.full_name]) < 5:
            lookup[r.full_name].append({
                "version": r.version, "title": r.title,
                "url": r.url, "released_at": r.released_at,
            })
    return lookup


def fetch_trending(view_name, snapshot_table, domain_filter=None):
    """Repos with biggest score improvement since earliest available snapshot."""
    domain_clause = "AND s.domain = :domain_filter" if domain_filter else ""
    params = {"min_score": MIN_QUALITY_SCORE}
    if domain_filter:
        params["domain_filter"] = domain_filter

    with readonly_engine.connect() as conn:
        # Find earliest snapshot date
        date_sql = f"SELECT MIN(snapshot_date) FROM {snapshot_table}"
        if domain_filter:
            date_sql += " WHERE domain = :domain_filter"
        earliest = conn.execute(text(date_sql), params).scalar()
        if not earliest or earliest >= date.today():
            return [], 0

        rows = conn.execute(text(f"""
            SELECT m.full_name, m.name, m.description, m.quality_score,
                   m.quality_score - s.quality_score AS score_delta,
                   m.stars, m.subcategory, m.quality_tier
            FROM {view_name} m
            JOIN ai_repos ar ON ar.full_name = m.full_name
            JOIN {snapshot_table} s ON s.repo_id = ar.id
              AND s.snapshot_date = :earliest_date
              {domain_clause}
            WHERE m.quality_score >= :min_score
              AND m.description IS NOT NULL
              AND m.description != ''
              AND m.quality_score - s.quality_score > 0
            ORDER BY m.quality_score - s.quality_score DESC
            LIMIT 100
        """), {**params, "earliest_date": earliest}).fetchall()

        trending_days = (date.today() - earliest).days
    return [dict(r._mapping) for r in rows], trending_days


# ---------------------------------------------------------------------------
# Site generation
# ---------------------------------------------------------------------------

def build_category_data(servers, category_meta=None):
    """Group servers by subcategory and compute aggregates."""
    meta = category_meta or {}
    by_cat = {}
    for s in servers:
        cat = s.get("subcategory") or "uncategorized"
        by_cat.setdefault(cat, []).append(s)

    categories = []
    for key, group in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        cm = meta.get(key, {})
        categories.append({
            "subcategory": key,
            "label": cm.get("display_label", key.replace("-", " ").title()),
            "desc": cm.get("desc", ""),
            "count": len(group),
            "servers": group,
        })
    return categories


def build_related_lookup(categories):
    lookup = {}
    for cat in categories:
        top = cat["servers"][:6]
        lookup[cat["subcategory"]] = top
    return lookup


def fetch_deep_dive_links():
    """Build reverse lookups: repo full_name -> deep dives, and (domain, subcategory) -> deep dives.

    Two linking mechanisms:
    1. featured_repos: explicit per-repo links (repos whose live metrics appear in the deep dive)
    2. featured_categories: subcategory-level links (every repo in a relevant subcategory gets
       a "Featured in" link to the deep dive, so users browsing any part of the landscape can
       discover the zoomed-out analysis)
    """
    repo_lookup = {}
    category_lookup = {}
    try:
        with readonly_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT slug, title, featured_repos, featured_categories
                FROM deep_dives
                WHERE status = 'published'
            """)).fetchall()
        for r in rows:
            dd = {"slug": r._mapping["slug"], "title": r._mapping["title"]}
            for repo_name in (r._mapping["featured_repos"] or []):
                repo_lookup.setdefault(repo_name, []).append(dd)
            for cat_key in (r._mapping["featured_categories"] or []):
                category_lookup.setdefault(cat_key, []).append(dd)
    except Exception as e:
        print(f"  Warning: could not fetch deep dive links: {e}")
    return repo_lookup, category_lookup


def dynamic_threshold(score_a, score_b):
    """Higher-scored repos get a wider comparison window."""
    ms = max(score_a, score_b)
    if ms >= 70: return 0.65
    elif ms >= 50: return 0.72
    elif ms >= 30: return 0.78
    else: return 0.85


def fetch_embeddings_for_repos(full_names):
    """Fetch 1536d embeddings for a list of repos. Small per-category query."""
    if not full_names:
        return {}
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT full_name, embedding_1536::text as emb
            FROM ai_repos
            WHERE full_name = ANY(:names) AND embedding_1536 IS NOT NULL
        """), {"names": list(full_names)}).fetchall()
    result = {}
    for r in rows:
        m = r._mapping
        vec = np.fromstring(m["emb"].strip("[]"), sep=",", dtype=np.float32)
        norm = np.linalg.norm(vec)
        result[m["full_name"]] = vec / norm if norm > 0 else vec
    return result


def build_comparison_pairs(categories, domain):
    """Find comparison-worthy pairs via embedding similarity within each category."""
    all_pairs = []
    for cat in categories:
        servers = cat["servers"]
        if len(servers) < 2:
            continue
        # Limit to top 20 per category to keep queries small
        top = servers[:20]
        names = [s["full_name"] for s in top]
        emb_map = fetch_embeddings_for_repos(names)
        if len(emb_map) < 2:
            continue

        # Build vectors in order
        indexed = [(s, emb_map[s["full_name"]]) for s in top if s["full_name"] in emb_map]
        for i, (a, va) in enumerate(indexed):
            for j, (b, vb) in enumerate(indexed):
                if j <= i:
                    continue
                sim = float(va @ vb)
                thresh = dynamic_threshold(a["quality_score"], b["quality_score"])
                if sim >= thresh:
                    # Ensure A has higher score (or alphabetical if equal)
                    if a["quality_score"] < b["quality_score"]:
                        a, b = b, a
                    slug = f"{a['full_name'].replace('/', '-')}-vs-{b['full_name'].replace('/', '-')}"
                    all_pairs.append({
                        "repo_a": a, "repo_b": b,
                        "similarity": sim,
                        "category": cat["subcategory"],
                        "category_label": cat["label"],
                        "slug": slug,
                    })
    return all_pairs


def load_comparison_pairs(domain):
    """Load pre-computed comparison pairs from structural_cache."""
    try:
        with readonly_engine.connect() as conn:
            row = conn.execute(text(
                "SELECT value FROM structural_cache WHERE key = :key"
            ), {"key": f"comparison_pairs:{domain}"}).fetchone()
        if row:
            val = row._mapping["value"]
            return json.loads(val) if isinstance(val, str) else val
    except Exception:
        pass
    return []


def fetch_comparison_sentences():
    """Load pre-computed decision sentences."""
    try:
        with readonly_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT a.full_name as a_name, b.full_name as b_name, cs.sentence
                FROM comparison_sentences cs
                JOIN ai_repos a ON a.id = cs.repo_a_id
                JOIN ai_repos b ON b.id = cs.repo_b_id
                WHERE cs.sentence IS NOT NULL
            """)).fetchall()
        result = {}
        for r in rows:
            m = r._mapping
            result[(m["a_name"], m["b_name"])] = m["sentence"]
            result[(m["b_name"], m["a_name"])] = m["sentence"]
        return result
    except Exception:
        return {}


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Path(path).write_text(content)


def generate_sitemap(base_url, generated_urls, out_dir):
    """Write sitemap from the list of URLs that were actually generated.

    generated_urls is a list of dicts: {"path": "/servers/owner/repo/", "priority": "0.6", ...}
    This is the single source of truth — if a page wasn't generated, it's not in this list.
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for entry in generated_urls:
        loc = f"{base_url}{xml_escape(entry['path'])}"
        lastmod = f"<lastmod>{entry['lastmod']}</lastmod>" if entry.get("lastmod") else ""
        freq = entry.get("changefreq", "weekly")
        pri = entry.get("priority", "0.6")
        lines.append(f'  <url><loc>{loc}</loc>{lastmod}<changefreq>{freq}</changefreq><priority>{pri}</priority></url>')
    lines.append('</urlset>')
    write_file(os.path.join(out_dir, "sitemap.xml"), "\n".join(lines))


def verify_sitemap(sitemap_path, out_dir, base_url, base_path):
    """Verify every URL in the sitemap has a corresponding file on disk.

    Returns list of URLs without matching files.
    """
    import re
    prefix = f"{base_url}{base_path}"
    mismatches = []
    try:
        content = Path(sitemap_path).read_text()
    except FileNotFoundError:
        return []
    for match in re.finditer(r'<loc>([^<]+)</loc>', content):
        url = match.group(1)
        # Strip base URL + base path to get the path relative to out_dir
        path = url.replace(prefix, "").rstrip("/")
        if not path:
            path = "/"
        file_path = os.path.join(out_dir, path.lstrip("/"), "index.html")
        if not os.path.exists(file_path):
            mismatches.append(url)
    if mismatches:
        print(f"  WARNING: Sitemap has {len(mismatches)} URLs without pages on disk")
        for m in mismatches[:10]:
            print(f"    Missing: {m}")
    return mismatches


def generate_robots(base_url, base_path, out_dir):
    content = (
        f"User-agent: *\nAllow: /\n\n"
        f"Sitemap: {base_url}{base_path}/sitemap.xml\n"
        f"Sitemap: {base_url}/insights/sitemap.xml\n"
        f"\n"
        f"# PT-Edge API — programmatic access to all data on this site\n"
        f"# Docs: https://pt-edge.onrender.com/api/docs\n"
        f"# Get a key: POST https://pt-edge.onrender.com/api/v1/keys (no auth required, no email required)\n"
        f"# OpenAPI spec: https://pt-edge.onrender.com/api/v1/openapi.json\n"
        f"\n"
        f"# Atom feed for deep dive insights\n"
        f"# Feed: {base_url}/insights/feed.atom\n"
    )
    write_file(os.path.join(out_dir, "robots.txt"), content)


def generate_portal(output_dir, base_url):
    """Generate the all-domains portal homepage."""
    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)

    global_total = fetch_global_total()

    # Get per-domain counts
    with readonly_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT domain, COUNT(*) AS cnt
            FROM ai_repos
            WHERE domain <> 'uncategorized'
              AND subcategory IS NOT NULL AND subcategory <> ''
            GROUP BY domain
        """)).fetchall()
    domain_counts = {r.domain: r.cnt for r in rows}

    # Build portal domain list
    portal_domains = []
    for d in DIRECTORIES:
        dcfg = DOMAIN_CONFIG.get(d["domain"], {})
        count = domain_counts.get(d["domain"], 0)
        portal_domains.append({
            "path": d["path"] if d["domain"] != "mcp" else "/servers/",
            "label": dcfg.get("label", d["label"]),
            "label_plural": dcfg.get("label_plural", d["label"]),
            "description": dcfg.get("description", ""),
            "count": count,
            "domain": d["domain"],
        })
    portal_domains.sort(key=lambda x: x["count"], reverse=True)

    write_file(
        os.path.join(output_dir, "index.html"),
        env.get_template("portal.html").render(
            domains=portal_domains,
            global_total=f"{global_total:,}",
            directories=DIRECTORIES,
            base_url=base_url.rstrip("/"),
            base_path="",
            domain="portal",
            domain_label="AI Tools",
            domain_label_plural="AI Tools",
            noun="project",
            noun_plural="projects",
        ),
    )
    print(f"  Portal homepage generated ({len(portal_domains)} domains, {global_total:,} total)")


def main():
    parser = argparse.ArgumentParser(description="Generate static AI directory site")
    parser.add_argument("--domain", default="mcp", choices=list(DOMAIN_CONFIG.keys()),
                        help="Domain to generate (default: mcp)")
    parser.add_argument("--output-dir", default="./site", help="Output directory")
    parser.add_argument("--base-url", default="https://mcp.phasetransitions.ai",
                        help="Base URL for canonical links")
    parser.add_argument("--skip-comparisons", action="store_true",
                        help="Skip comparison page generation (faster startup)")
    parser.add_argument("--portal", action="store_true",
                        help="Generate all-domains portal homepage only")
    args = parser.parse_args()

    if args.portal:
        print("Generating portal homepage...")
        generate_portal(args.output_dir, args.base_url)
        return

    domain = args.domain
    cfg = DOMAIN_CONFIG[domain]
    out_dir = args.output_dir
    base_url = args.base_url.rstrip("/")
    # MCP is at root, others get a path prefix
    base_path = "" if domain == "mcp" else f"/{domain}"
    t0 = time.time()

    print(f"Generating {cfg['label']} directory (domain={domain})...")

    # Set up Jinja2
    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    env.filters["human_stars"] = human_stars
    env.globals["tier_classes"] = tier_classes
    env.globals["tier_bar_color"] = tier_bar_color
    env.globals["score_bar_color"] = score_bar_color
    env.globals["metrics_paragraph"] = metrics_paragraph
    env.globals["decision_paragraph"] = decision_paragraph
    env.globals["base_url"] = base_url
    env.globals["base_path"] = base_path.rstrip("/")
    env.globals["directories"] = DIRECTORIES

    # Global total for footer context
    global_total = fetch_global_total()

    # Domain-specific context passed to all templates
    domain_ctx = {
        "domain": domain,
        "domain_label": cfg["label"],
        "domain_label_plural": cfg["label_plural"],
        "noun": cfg["noun"],
        "noun_plural": cfg["noun_plural"],
        "domain_description": cfg["description"],
        "domain_explainer": cfg.get("explainer", ""),
        "global_total": f"{global_total:,}",
    }

    # Phase 1: Query data
    print(f"  Fetching {cfg['noun_plural']}...")
    servers = fetch_servers(cfg["view"])
    total_count = len(servers)
    print(f"  {total_count} qualifying {cfg['noun_plural']}")

    print("  Loading repo briefs...")
    briefs = fetch_repo_briefs(domain)
    brief_count = 0
    for s in servers:
        b = briefs.get(s["full_name"])
        if b:
            s.update(b)
            brief_count += 1
    print(f"  {brief_count} repo briefs matched")

    print("  Loading HN posts...")
    hn_lookup = fetch_hn_posts(domain)
    hn_count = 0
    for s in servers:
        posts = hn_lookup.get(s["full_name"])
        if posts:
            s["hn_posts"] = posts
            hn_count += 1
    print(f"  {hn_count} projects with HN discussions")

    print("  Loading releases...")
    release_lookup = fetch_releases(domain)
    release_count = 0
    for s in servers:
        rels = release_lookup.get(s["full_name"])
        if rels:
            s["releases"] = rels
            release_count += 1
    print(f"  {release_count} projects with releases")

    print("  Fetching trending...")
    trending_days = 0
    try:
        trending, trending_days = fetch_trending(
            cfg["view"], cfg["snapshot_table"], cfg["snapshot_domain_filter"]
        )
    except Exception as e:
        print(f"  Trending query failed: {e}")
        trending = []
    print(f"  {len(trending)} trending {cfg['noun_plural']} ({trending_days}d window)")

    # Build derived data
    category_meta = fetch_category_meta(domain)
    categories = build_category_data(servers, category_meta)
    related_lookup = build_related_lookup(categories)
    # Lookup for category label + count, used by detail pages
    cat_meta_lookup = {
        c["subcategory"]: {"label": c["label"], "count": c["count"]}
        for c in categories
    }

    tier_counts = {}
    for s in servers:
        t = s["quality_tier"]
        tier_counts[t] = tier_counts.get(t, 0) + 1

    tiers = {}
    for t_name in ["verified", "established", "emerging", "experimental"]:
        tiers[t_name] = {
            "count": tier_counts.get(t_name, 0),
            "classes": TIER_CLASSES[t_name],
            "range": TIER_RANGES[t_name],
        }

    ctx = {"total_count": total_count, **domain_ctx}

    # Pre-load comparison pairs for cross-linking (cheap cache read)
    # Pre-load deep dive reverse links (repo -> deep dives featuring it)
    print("  Loading deep dive links...")
    deep_dive_repo_lookup, deep_dive_cat_lookup = fetch_deep_dive_links()
    if deep_dive_repo_lookup or deep_dive_cat_lookup:
        repo_count = sum(len(v) for v in deep_dive_repo_lookup.values())
        cat_count = len(deep_dive_cat_lookup)
        print(f"  {repo_count} explicit repo links + {cat_count} category-level links")

    print("  Loading comparison pairs from cache...")
    cached_pairs = load_comparison_pairs(domain)
    server_map = {s["full_name"]: s for s in servers}
    comparison_lookup = {}
    cat_comparisons = {}
    top_comparisons = []

    if cached_pairs:
        for cp in cached_pairs:
            a = server_map.get(cp["repo_a"])
            b = server_map.get(cp["repo_b"])
            if not a or not b:
                continue
            a_name = cp["repo_a"].split("/")[1] if "/" in cp["repo_a"] else cp["repo_a"]
            b_name = cp["repo_b"].split("/")[1] if "/" in cp["repo_b"] else cp["repo_b"]
            comparison_lookup.setdefault(cp["repo_a"], []).append(
                {"slug": cp["slug"], "partner": b_name, "partner_full": cp["repo_b"]})
            comparison_lookup.setdefault(cp["repo_b"], []).append(
                {"slug": cp["slug"], "partner": a_name, "partner_full": cp["repo_a"]})
            cat = cp.get("category", "")
            combined_stars = (a.get("stars") or 0) + (b.get("stars") or 0)
            cat_comparisons.setdefault(cat, []).append({
                "slug": cp["slug"], "name_a": a_name, "name_b": b_name,
                "score_a": int(a.get("quality_score", 0)),
                "score_b": int(b.get("quality_score", 0)),
                "combined_stars": combined_stars,
            })
        for cat in cat_comparisons:
            cat_comparisons[cat].sort(key=lambda x: -x["combined_stars"])
        top_comparisons = sorted(
            [c for comps in cat_comparisons.values() for c in comps],
            key=lambda x: -x["combined_stars"]
        )[:6]
        print(f"  {len(cached_pairs)} cached pairs, {len(comparison_lookup)} repos with comparisons")

    # Phase 2: Render pages — collect generated URLs for sitemap
    generated_urls = []

    print("  Loading domain brief...")
    domain_brief = fetch_domain_brief(domain)
    if domain_brief:
        print(f"  Domain brief: {domain_brief['title'][:60]}")

    print("  Loading briefings...")
    briefings = fetch_briefings(domain)
    if briefings:
        print(f"  {len(briefings)} briefings for {domain}")

    print("  Generating homepage...")
    write_file(
        os.path.join(out_dir, "index.html"),
        env.get_template("index.html").render(
            top_servers=servers[:20],
            tiers=tiers,
            categories=[{"subcategory": c["subcategory"], "label": c["label"], "count": c["count"]} for c in categories],
            top_comparisons=top_comparisons,
            domain_brief=domain_brief,
            briefings=briefings,
            **ctx,
        ),
    )
    generated_urls.append({"path": f"{base_path}/", "changefreq": "daily", "priority": "1.0"})

    print("  Generating index pages...")
    total_pages = math.ceil(total_count / PER_PAGE)
    index_tpl = env.get_template("servers_index.html")
    for page in range(1, total_pages + 1):
        offset = (page - 1) * PER_PAGE
        page_servers = servers[offset:offset + PER_PAGE]
        path = os.path.join(out_dir, "servers", "index.html") if page == 1 else \
               os.path.join(out_dir, "servers", "page", str(page), "index.html")
        write_file(path, index_tpl.render(
            servers=page_servers, page=page, total_pages=total_pages,
            offset=offset, per_page=PER_PAGE, **ctx,
        ))
        url_path = f"{base_path}/servers/" if page == 1 else f"{base_path}/servers/page/{page}/"
        generated_urls.append({"path": url_path, "changefreq": "daily", "priority": "0.9"})
    print(f"  {total_pages} index pages")

    print(f"  Generating {cfg['noun']} detail pages...")
    detail_tpl = env.get_template("server_detail.html")
    last_owner = None
    for i, s in enumerate(servers):
        parts = s["full_name"].split("/", 1)
        if len(parts) != 2:
            continue
        owner, repo = parts
        cat_key = s.get("subcategory") or "uncategorized"
        related = [r for r in related_lookup.get(cat_key, [])
                   if r["full_name"] != s["full_name"]][:5]

        path = os.path.join(out_dir, "servers", owner, repo, "index.html")
        if owner != last_owner:
            os.makedirs(os.path.join(out_dir, "servers", owner), exist_ok=True)
            last_owner = owner
        # Merge deep dive links: explicit repo links + subcategory-level links (deduplicated)
        dd_links = list(deep_dive_repo_lookup.get(s["full_name"], []))
        dd_cat_key = f"{domain}:{cat_key}" if cat_key != "uncategorized" else ""
        if dd_cat_key:
            for dd in deep_dive_cat_lookup.get(dd_cat_key, []):
                if dd["slug"] not in {d["slug"] for d in dd_links}:
                    dd_links.append(dd)
        cat_info = cat_meta_lookup.get(cat_key, {})
        write_file(path, detail_tpl.render(server=s, related_servers=related,
                                          comparisons=comparison_lookup.get(s["full_name"], [])[:10],
                                          deep_dive_links=dd_links,
                                          category_label=cat_info.get("label", ""),
                                          category_count=cat_info.get("count", 0),
                                          **ctx))
        lastmod = ""
        if s.get("last_pushed_at"):
            if isinstance(s["last_pushed_at"], datetime):
                lastmod = s["last_pushed_at"].strftime("%Y-%m-%d")
            elif isinstance(s["last_pushed_at"], date):
                lastmod = s["last_pushed_at"].isoformat()
        generated_urls.append({"path": f"{base_path}/servers/{s['full_name']}/",
                               "lastmod": lastmod, "priority": "0.6"})

        if (i + 1) % 5000 == 0:
            print(f"  {i + 1}/{total_count} detail pages...")
    print(f"  {total_count} detail pages")

    print("  Generating category pages...")
    cat_tpl = env.get_template("category.html")
    write_file(
        os.path.join(out_dir, "categories", "index.html"),
        env.get_template("categories_index.html").render(
            categories=[{"subcategory": c["subcategory"], "label": c["label"], "desc": c["desc"], "count": c["count"]} for c in categories],
            **ctx,
        ),
    )
    generated_urls.append({"path": f"{base_path}/categories/", "changefreq": "weekly", "priority": "0.8"})
    for cat in categories:
        write_file(
            os.path.join(out_dir, "categories", cat["subcategory"], "index.html"),
            cat_tpl.render(subcategory=cat["subcategory"], category_label=cat["label"],
                           category_desc=cat["desc"], servers=cat["servers"],
                           category_comparisons=cat_comparisons.get(cat["subcategory"], [])[:10],
                           **ctx),
        )
        generated_urls.append({"path": f"{base_path}/categories/{cat['subcategory']}/",
                               "changefreq": "weekly", "priority": "0.8"})
    print(f"  {len(categories)} category pages")

    print("  Generating trending page...")
    write_file(
        os.path.join(out_dir, "trending", "index.html"),
        env.get_template("trending.html").render(trending=trending, trending_days=trending_days, **ctx),
    )
    generated_urls.append({"path": f"{base_path}/trending/", "changefreq": "daily", "priority": "0.7"})

    print("  Generating about + methodology pages...")
    write_file(
        os.path.join(out_dir, "about", "index.html"),
        env.get_template("about.html").render(**ctx),
    )
    write_file(
        os.path.join(out_dir, "methodology", "index.html"),
        env.get_template("methodology.html").render(**ctx),
    )
    generated_urls.append({"path": f"{base_path}/about/", "changefreq": "monthly", "priority": "0.4"})
    generated_urls.append({"path": f"{base_path}/methodology/", "changefreq": "monthly", "priority": "0.4"})

    # Generate comparison pages (lookups already built earlier)
    comparison_pairs = []
    if cached_pairs:
        sentences = fetch_comparison_sentences()
        print(f"  Generating comparison pages ({len(sentences)} decision sentences)...")

        comp_tpl = env.get_template("comparison.html")
        for cp in cached_pairs:
            a = server_map.get(cp["repo_a"])
            b = server_map.get(cp["repo_b"])
            if not a or not b:
                continue
            cat_m = category_meta.get(cp.get("category", ""), {})
            cat_label = cat_m.get("display_label", cp.get("category", "").replace("-", " ").title())
            slug = cp["slug"]
            sentence = sentences.get((cp["repo_a"], cp["repo_b"]), "")

            # Related comparisons: other pairs involving A or B
            related = []
            seen = {slug}
            for r in comparison_lookup.get(cp["repo_a"], []) + comparison_lookup.get(cp["repo_b"], []):
                if r["slug"] not in seen:
                    seen.add(r["slug"])
                    # Determine both names for display
                    other_a = cp["repo_a"].split("/")[1] if r["partner_full"] != cp["repo_a"] else r["partner"]
                    other_b = r["partner"] if r["partner_full"] != cp["repo_a"] else cp["repo_a"].split("/")[1]
                    related.append({"slug": r["slug"], "name_a": other_a, "name_b": other_b})
                if len(related) >= 6:
                    break

            write_file(
                os.path.join(out_dir, "compare", slug, "index.html"),
                comp_tpl.render(
                    repo_a=a, repo_b=b, slug=slug, sentence=sentence,
                    comparison_category=cp.get("category", ""),
                    category_label=cat_label,
                    related_comparisons=related,
                    **ctx,
                ),
            )
            comparison_pairs.append(cp)
            generated_urls.append({"path": f"{base_path}/compare/{slug}/",
                                   "changefreq": "weekly", "priority": "0.7"})

            if len(comparison_pairs) % 1000 == 0:
                print(f"  {len(comparison_pairs)} comparison pages...")

        print(f"  {len(comparison_pairs)} comparison pages")
    else:
        print("  No cached pairs (run weekly_structural.py to populate)")

    # Phase 3: SEO assets
    print(f"  Generating sitemap.xml ({len(generated_urls)} URLs) + robots.txt...")
    sitemap_path = os.path.join(out_dir, "sitemap.xml")
    generate_sitemap(base_url, generated_urls, out_dir)
    generate_robots(base_url, base_path, out_dir)

    # Verify sitemap/page alignment
    mismatches = verify_sitemap(sitemap_path, out_dir, base_url, base_path)
    if mismatches:
        print(f"  WARNING: {len(mismatches)} sitemap URLs have no page on disk")

    elapsed = time.time() - t0
    total_files = total_count + total_pages + len(categories) + len(comparison_pairs) + 5
    print(f"\nDone! {cfg['label']}: {total_files} files in {elapsed:.1f}s → {out_dir}/")


if __name__ == "__main__":
    main()
