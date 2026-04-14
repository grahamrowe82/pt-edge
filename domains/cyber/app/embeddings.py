"""Embedding service for CyberEdge semantic search and categorization.

Thin async module wrapping OpenAI text-embedding-3-large.
All errors return None — never raises. DB is the cache.

Usage:
    from app.embeddings import embed_one, embed_batch, build_cve_text, is_enabled

    if is_enabled():
        text = build_cve_text(cve_id, description, attack_vector, attack_complexity)
        vec = await embed_one(text)
"""

import logging
from typing import Optional

from domains.cyber.app.settings import settings

logger = logging.getLogger(__name__)

MODEL = "text-embedding-3-large"
DIMENSIONS = 1536
MAX_BATCH_SIZE = 2048
MAX_TEXT_CHARS = 6000


def is_enabled() -> bool:
    """True if OPENAI_API_KEY is set."""
    return bool(settings.OPENAI_API_KEY)


# ---------------------------------------------------------------------------
# Text builders — single source of truth for what goes into each embedding.
# Changing these = need to regenerate all embeddings.
# ---------------------------------------------------------------------------


def build_cve_text(
    cve_id: str,
    description: str | None = None,
    attack_vector: str | None = None,
    attack_complexity: str | None = None,
) -> str:
    """Build embedding text for a CVE."""
    parts = [cve_id or ""]
    if description:
        parts[0] += f": {description[:2000]}"
    if attack_vector:
        parts.append(f"Attack vector: {attack_vector}")
    if attack_complexity:
        parts.append(f"Complexity: {attack_complexity}")
    return ". ".join(parts) + "."


def build_software_text(
    name: str,
    vendor_name: str | None = None,
    version: str | None = None,
    part: str | None = None,
) -> str:
    """Build embedding text for a software product."""
    parts = [name or ""]
    if vendor_name:
        parts.append(f"Vendor: {vendor_name}")
    if version:
        parts.append(f"Version: {version}")
    if part:
        part_label = {"a": "Application", "o": "Operating System", "h": "Hardware"}.get(part, part)
        parts.append(f"Type: {part_label}")
    return ". ".join(parts) + "."


def build_vendor_text(
    name: str,
    product_count: int | None = None,
) -> str:
    """Build embedding text for a vendor."""
    parts = [name or ""]
    if product_count and product_count > 0:
        parts.append(f"Products: {product_count}")
    return ". ".join(parts) + "."


def build_weakness_text(
    cwe_id: str,
    name: str | None = None,
    description: str | None = None,
    abstraction: str | None = None,
) -> str:
    """Build embedding text for a CWE weakness."""
    parts = [cwe_id or ""]
    if name:
        parts[0] += f": {name}"
    if description:
        parts.append(description[:2000])
    if abstraction:
        parts.append(f"Abstraction: {abstraction}")
    return ". ".join(parts) + "."


def build_technique_text(
    technique_id: str,
    name: str | None = None,
    description: str | None = None,
    platforms: list[str] | None = None,
) -> str:
    """Build embedding text for an ATT&CK technique."""
    parts = [technique_id or ""]
    if name:
        parts[0] += f": {name}"
    if description:
        parts.append(description[:2000])
    if platforms:
        parts.append(f"Platforms: {', '.join(platforms[:10])}")
    return ". ".join(parts) + "."


def build_product_text(
    display_name: str,
    vendor_name: str | None = None,
    part: str | None = None,
    top_weaknesses: list[str] | None = None,
    cve_count: int | None = None,
) -> str:
    """Build embedding text for a product (aggregated from CPE versions).

    Richer than software text — includes weakness profile so the model
    understands what TYPE of software this is (CMS, browser, firmware, etc).
    """
    parts = [display_name or ""]
    if vendor_name:
        parts.append(f"by {vendor_name}")
    if part:
        part_label = {"a": "Application", "o": "Operating System", "h": "Hardware"}.get(part, part)
        parts.append(f"Type: {part_label}")
    if top_weaknesses:
        parts.append(f"Vulnerability types: {', '.join(top_weaknesses[:5])}")
    if cve_count and cve_count > 0:
        parts.append(f"{cve_count} known vulnerabilities")
    return ". ".join(parts) + "."


def build_pattern_text(
    capec_id: str,
    name: str | None = None,
    description: str | None = None,
    severity: str | None = None,
) -> str:
    """Build embedding text for a CAPEC attack pattern."""
    parts = [capec_id or ""]
    if name:
        parts[0] += f": {name}"
    if description:
        parts.append(description[:2000])
    if severity:
        parts.append(f"Severity: {severity}")
    return ". ".join(parts) + "."


# ---------------------------------------------------------------------------
# Embedding functions
# ---------------------------------------------------------------------------


async def embed_one(text: str, dimensions: int = DIMENSIONS) -> Optional[list[float]]:
    """Embed a single text. Returns None if disabled or on error."""
    if not is_enabled():
        return None
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    try:
        resp = await client.embeddings.create(input=[text], model=MODEL, dimensions=dimensions)
        return resp.data[0].embedding
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        return None
    finally:
        await client.close()


async def embed_batch(texts: list[str], dimensions: int = DIMENSIONS) -> list[Optional[list[float]]]:
    """Embed multiple texts. Chunks to MAX_BATCH_SIZE. Returns aligned list.

    Truncates texts beyond MAX_TEXT_CHARS. On chunk failure, retries
    individually so only truly problematic texts get None.
    """
    if not is_enabled():
        return [None] * len(texts)

    safe_texts = [t[:MAX_TEXT_CHARS] if len(t) > MAX_TEXT_CHARS else t for t in texts]
    results: list[Optional[list[float]]] = [None] * len(safe_texts)

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    from app.core.ingest.budget import acquire_budget, record_call, ResourceExhaustedError

    try:
        for start in range(0, len(safe_texts), MAX_BATCH_SIZE):
            chunk = safe_texts[start:start + MAX_BATCH_SIZE]
            try:
                if not await acquire_budget("openai"):
                    raise ResourceExhaustedError("openai")
                resp = await client.embeddings.create(input=chunk, model=MODEL, dimensions=dimensions)
                await record_call("openai")
                for item in resp.data:
                    results[start + item.index] = item.embedding
            except Exception as e:
                logger.warning(f"Batch chunk failed (offset {start}, size {len(chunk)}): {e}")
                for i, text in enumerate(chunk):
                    try:
                        if not await acquire_budget("openai"):
                            raise ResourceExhaustedError("openai")
                        resp = await client.embeddings.create(
                            input=[text], model=MODEL, dimensions=dimensions,
                        )
                        await record_call("openai")
                        results[start + i] = resp.data[0].embedding
                    except Exception as e2:
                        logger.warning(f"Individual embed failed (index {start + i}): {e2}")
    finally:
        await client.close()

    return results
