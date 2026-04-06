"""Ingest frontier models from OpenRouter API."""

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import engine, SessionLocal
from app.models import Lab

logger = logging.getLogger(__name__)

OPENROUTER_API = "https://openrouter.ai/api/v1/models"

# Map OpenRouter provider prefixes to our lab slugs.
PROVIDER_TO_LAB = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google-deepmind",
    "meta-llama": "meta-ai",
    "mistralai": "mistral-ai",
    "cohere": "cohere",
    "deepseek": "deepseek",
    "qwen": "qwen",
    "zhipuai": "zhipu-ai",
}

# Skip models matching these patterns (test, free-tier duplicates, very old).
SKIP_PATTERNS = [":free", ":extended", ":beta", ":nitro", ":floor"]


def _per_token_to_mtok(per_token_str: str | None) -> str | None:
    """Convert OpenRouter per-token price string to $/MTok display string."""
    if not per_token_str:
        return None
    try:
        per_token = float(per_token_str)
        if per_token == 0:
            return None  # free tier
        per_mtok = per_token * 1_000_000
        if per_mtok >= 1:
            return f"${per_mtok:.2f}/MTok"
        return f"${per_mtok:.4f}/MTok"
    except (ValueError, TypeError):
        return None


def _extract_capabilities(model: dict) -> dict:
    """Extract structured capabilities from OpenRouter model data."""
    caps = {}
    arch = model.get("architecture", {})
    input_mods = arch.get("input_modalities") or []
    output_mods = arch.get("output_modalities") or []

    if "image" in input_mods:
        caps["vision"] = True
    if "file" in input_mods:
        caps["file_input"] = True
    if "image" in output_mods:
        caps["image_generation"] = True

    params = model.get("supported_parameters") or []
    if "include_reasoning" in params or "reasoning" in params:
        caps["reasoning"] = True
    if "tools" in params:
        caps["function_calling"] = True

    return caps


async def ingest_models() -> dict:
    """Fetch frontier models from OpenRouter and upsert into DB."""
    # Build lab slug -> id map
    session = SessionLocal()
    try:
        labs = session.query(Lab).all()
        lab_slug_to_id = {lab.slug: lab.id for lab in labs}
    finally:
        session.close()

    # Fetch from OpenRouter
    async with httpx.AsyncClient(
        headers={"User-Agent": "pt-edge/1.0"}, timeout=30.0,
    ) as client:
        resp = await client.get(OPENROUTER_API)
        if resp.status_code != 200:
            logger.error(f"OpenRouter API returned {resp.status_code}")
            return {"error": f"HTTP {resp.status_code}"}

        data = resp.json()

    all_models = data.get("data", [])
    logger.info(f"OpenRouter returned {len(all_models)} models")

    upserted = 0
    skipped = 0
    with engine.connect() as conn:
        for m in all_models:
            openrouter_id = m.get("id", "")

            # Skip non-tracked providers
            provider = openrouter_id.split("/")[0] if "/" in openrouter_id else ""
            lab_slug = PROVIDER_TO_LAB.get(provider)
            if not lab_slug:
                continue

            lab_id = lab_slug_to_id.get(lab_slug)
            if not lab_id:
                continue

            # Skip test/free/beta variants
            if any(pat in openrouter_id for pat in SKIP_PATTERNS):
                skipped += 1
                continue

            # Skip very small context windows (likely old/toy models)
            context_window = m.get("context_length") or 0
            if context_window < 4096:
                skipped += 1
                continue

            name = m.get("name", openrouter_id)
            # Clean up provider prefix from display name (e.g. "OpenAI: GPT-4o" → "GPT-4o")
            if ": " in name:
                name = name.split(": ", 1)[1]

            slug = openrouter_id.replace("/", "-")
            pricing = m.get("pricing", {})
            arch = m.get("architecture", {})
            top_provider = m.get("top_provider", {})

            released_at = None
            created_ts = m.get("created")
            if created_ts:
                try:
                    released_at = datetime.fromtimestamp(created_ts, tz=timezone.utc).isoformat()
                except (ValueError, OSError):
                    pass

            import json
            caps = _extract_capabilities(m)

            conn.execute(text("""
                INSERT INTO frontier_models
                    (lab_id, name, slug, openrouter_id, context_window,
                     max_completion_tokens, pricing_input, pricing_output,
                     modality, capabilities, released_at, status)
                VALUES
                    (:lab_id, :name, :slug, :openrouter_id, :context_window,
                     :max_completion_tokens, :pricing_input, :pricing_output,
                     :modality, CAST(:capabilities AS jsonb), CAST(:released_at AS timestamptz), 'active')
                ON CONFLICT (openrouter_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    context_window = EXCLUDED.context_window,
                    max_completion_tokens = EXCLUDED.max_completion_tokens,
                    pricing_input = EXCLUDED.pricing_input,
                    pricing_output = EXCLUDED.pricing_output,
                    modality = EXCLUDED.modality,
                    capabilities = EXCLUDED.capabilities,
                    updated_at = NOW()
            """), {
                "lab_id": lab_id,
                "name": name,
                "slug": slug,
                "openrouter_id": openrouter_id,
                "context_window": context_window,
                "max_completion_tokens": top_provider.get("max_completion_tokens"),
                "pricing_input": _per_token_to_mtok(pricing.get("prompt")),
                "pricing_output": _per_token_to_mtok(pricing.get("completion")),
                "modality": arch.get("modality"),
                "capabilities": json.dumps(caps) if caps else None,
                "released_at": released_at,
            })
            upserted += 1

        conn.commit()

    logger.info(f"Model ingest: {upserted} upserted, {skipped} skipped")
    return {"upserted": upserted, "skipped": skipped}
