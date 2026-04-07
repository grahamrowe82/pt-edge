# Revised Domain Expansion Plan

*7 April 2026 — replaces the 11 domains in discovery-expansion.md*

## Principle

Add domains where AI agents get asked tool-selection questions. Not domains that have lots of GitHub repos. A domain earns its place if a developer regularly asks "what's the best X?" and expects a structured comparison in return.

## Current domains (18)

mcp, agents, perception, rag, ai-coding, llm-tools, diffusion, voice-ai, generative-ai, embeddings, vector-db, prompt-engineering, nlp, computer-vision, transformers, mlops, data-engineering, ml-frameworks

## Proposed additions

### Tier 1 — Clear gaps, high tool-selection intensity

These are categories where developers ask comparison questions daily and we have no answer.

| Domain | What it covers | Example "what's the best X?" queries | GitHub topics | Est. repos |
|--------|---------------|--------------------------------------|---------------|------------|
| `llm-inference` | Self-hosted LLM serving and local runners | "vLLM vs TGI vs SGLang vs Ollama vs llama.cpp" | `llm-inference`, `model-serving`, `llm-server`, `inference-engine`, `gguf`, `ollama` | 3,000-8,000 |
| `ai-evals` | LLM evaluation, benchmarking, observability, tracing | "Langfuse vs LangSmith vs Braintrust"; "lm-eval-harness vs HELM vs OpenCompass" | `llm-evaluation`, `ai-evaluation`, `benchmarking`, `llm-observability`, `ai-observability`, `tracing` | 2,000-5,000 |
| `fine-tuning` | LLM and model fine-tuning tools | "Unsloth vs Axolotl vs TRL vs LLaMA-Factory vs Torchtune" | `fine-tuning`, `finetuning`, `lora`, `qlora`, `peft`, `llm-finetuning` | 3,000-8,000 |
| `document-ai` | Document parsing, OCR, table extraction for AI pipelines | "Docling vs MinerU vs LlamaParse vs Unstructured vs Marker" | `ocr`, `document-parsing`, `pdf-extraction`, `document-ai`, `table-extraction`, `pdf-to-text` | 3,000-6,000 |
| `ai-safety` | Guardrails, content filtering, red teaming, adversarial robustness | "NeMo Guardrails vs Galileo vs Rebuff vs LLM Guard" | `guardrails`, `ai-safety`, `llm-security`, `red-teaming`, `adversarial-robustness`, `content-moderation` | 1,500-4,000 |

### Tier 2 — Real tool-selection activity, slightly less intense

| Domain | What it covers | Example queries | GitHub topics | Est. repos |
|--------|---------------|----------------|---------------|------------|
| `recommendation-systems` | Collaborative filtering, content-based, sequential recs | "RecBole vs Surprise vs LightFM vs DeepCTR" | `recommender-system`, `collaborative-filtering`, `recommendation-engine`, `content-based-filtering` | 8,000-15,000 |
| `audio-ai` | Music generation, source separation, audio classification (distinct from voice-ai's TTS/ASR focus) | "AudioCraft vs Riffusion vs MusicGen"; "Demucs vs Spleeter" | `audio-generation`, `music-generation`, `audio-classification`, `source-separation`, `sound-event-detection` | 3,000-6,000 |
| `synthetic-data` | Training data generation, augmentation, simulation for ML | "Gretel vs SDV vs Faker vs Albumentations" | `synthetic-data`, `data-augmentation`, `data-generation`, `synthetic-data-generation` | 2,000-5,000 |
| `time-series` | Forecasting, anomaly detection, classification on temporal data | "Darts vs NeuralForecast vs GluonTS vs Chronos vs TimesFM" | `time-series`, `forecasting`, `time-series-analysis`, `time-series-forecasting` | 5,000-10,000 |

### Tier 3 — Emerging or niche but defensible

| Domain | What it covers | Example queries | GitHub topics | Est. repos |
|--------|---------------|----------------|---------------|------------|
| `multimodal` | Vision-language models, cross-modal retrieval, audio-visual | "LLaVA vs InternVL vs Qwen-VL vs CogVLM" | `multimodal`, `vision-language`, `vlm`, `multimodal-learning` | 2,000-5,000 |
| `3d-ai` | NeRF, gaussian splatting, point clouds, 3D reconstruction | "Nerfstudio vs instant-ngp vs gsplat" | `nerf`, `gaussian-splatting`, `3d-reconstruction`, `point-cloud`, `3d-generation` | 1,500-3,000 |
| `scientific-ml` | Physics-informed neural nets, neural operators, molecular ML | "DeepXDE vs Modulus vs FourierNeuralOperator" | `physics-informed-neural-networks`, `scientific-computing`, `neural-operator`, `computational-biology` | 2,000-5,000 |

## What we're NOT adding (and why)

| Domain from original plan | Why not |
|---------------------------|---------|
| Reinforcement learning | Tool selection converged (Stable-Baselines3 + Gymnasium). Huge repo count but no active comparison debate. |
| Robotics | Highly domain-specific hardware-coupled field. Not what AI agents get asked for tool recommendations. |
| Graph neural networks | PyG vs DGL and the conversation ended. Not enough ongoing selection pressure. |
| Federated learning | Academic field with near-zero practitioner tool-selection discussion. |
| Interpretability/XAI | SHAP dominates. Minimal comparison activity outside research. |
| Edge AI/TinyML | Small ecosystem, overlaps with model compression. More of a deployment target than a tool category. |
| Simulation | Too niche standalone. Consumed within robotics/RL contexts. |
| Drug discovery | "AI applied to chemistry" not "AI tooling." Could revisit if demand signals appear. |

## Existing domains to reconsider (not blocking, but worth noting)

These aren't changes for this PR, but flags for a future restructuring pass:

- **`generative-ai`** — Catch-all bucket. People don't ask "which generative-ai tool?" They ask about image gen (diffusion), text gen (llm-tools), audio gen (audio-ai). Risk: becomes a dumping ground for repos that don't fit elsewhere.
- **`transformers`** — Overlaps with `llm-tools` and `ml-frameworks`. The repos here are mostly models (DeepSeek, Llama) not tools.
- **`nlp`** — Classical NLP tool selection (spaCy vs NLTK) is dying as LLMs absorb these tasks. The high-activity NLP questions are now LLM-adjacent and live in other domains.
- **`prompt-engineering`** — More technique than tool category. Repos tend to be prompt collections, not tools developers compare.

No action needed now — these domains have existing pages and retrieval traffic. But if they persistently underperform on retrieval, consider merging or redefining them.

## Impact summary

| | Original plan | Revised plan |
|---|---|---|
| New domains | 11 | 12 |
| Focus | Academic ML breadth | Tool-selection intensity |
| Expected new repos | 70,000-125,000 | 35,000-80,000 |
| Retrieval surface expansion | Wide but shallow | Narrower but deeper — every new domain answers questions agents actually get asked |
| Total domains | 29 | 30 |

The revised plan trades raw repo count for retrieval relevance. Fewer repos, but each one sits in a domain where an agent is likely to need it.

## Implementation

Same mechanical process as the original PR 3: for each new domain, add entries to `DOMAINS` + `DOMAIN_ORDER` in `ai_repo_domains.py`, `DOMAIN_CONFIG` in `generate_site.py`, `DOMAIN_VIEW_MAP` in `enrich_repo_brief.py` and `project_briefs.py`, a line in `start.sh`, and a migration for the `mv_*_quality` materialized view.

Could split into two PRs if 12 domains in one go is too large:
- **PR 3a:** Tier 1 (5 domains) — highest leverage, ship first
- **PR 3b:** Tiers 2+3 (7 domains) — follow-up
