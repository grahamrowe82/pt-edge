"""Shared LLM call helper for ingest modules.

Centralises the httpx -> Anthropic API pattern: rate limiting, retries,
429 backoff, markdown fence stripping, JSON parsing.

Usage:
    result = await call_haiku(prompt, max_tokens=2048)
    # result is parsed JSON (dict or list) or None on failure

    text = await call_haiku_text(prompt, max_tokens=20)
    # text is raw string or None on failure
"""
import asyncio
import json
import logging

import httpx

from app.ingest.rate_limit import ANTHROPIC_LIMITER
from app.settings import settings

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"


async def call_haiku(
    prompt: str,
    *,
    max_tokens: int = 2048,
    retries: int = 3,
    timeout: float = 60.0,
) -> dict | list | None:
    """Call Claude Haiku and return parsed JSON, or None on failure."""
    if not settings.ANTHROPIC_API_KEY:
        return None

    for attempt in range(retries):
        await ANTHROPIC_LIMITER.acquire()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": _MODEL,
                        "max_tokens": max_tokens,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
        except httpx.HTTPError as e:
            logger.warning(f"LLM HTTP error (attempt {attempt + 1}/{retries}): {e}")
            await asyncio.sleep(2**attempt * 5)
            continue

        if resp.status_code == 429:
            wait = min(2**attempt * 15, 120)
            logger.warning(f"Anthropic 429, backing off {wait}s (attempt {attempt + 1}/{retries})")
            await asyncio.sleep(wait)
            continue

        if resp.status_code != 200:
            logger.warning(f"Anthropic API {resp.status_code}: {resp.text[:200]}")
            return None

        try:
            data = resp.json()
            text_content = data.get("content", [{}])[0].get("text", "").strip()
            # Strip markdown fences
            if "```" in text_content:
                text_content = text_content.split("```")[1]
                if text_content.startswith("json"):
                    text_content = text_content[4:]
                text_content = text_content.strip()
            return json.loads(text_content)
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return None

    return None


async def call_haiku_text(
    prompt: str,
    *,
    max_tokens: int = 512,
    retries: int = 3,
    timeout: float = 60.0,
) -> str | None:
    """Call Claude Haiku and return raw text (not JSON), or None on failure."""
    if not settings.ANTHROPIC_API_KEY:
        return None

    for attempt in range(retries):
        await ANTHROPIC_LIMITER.acquire()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": _MODEL,
                        "max_tokens": max_tokens,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
        except httpx.HTTPError as e:
            logger.warning(f"LLM HTTP error (attempt {attempt + 1}/{retries}): {e}")
            await asyncio.sleep(2**attempt * 5)
            continue

        if resp.status_code == 429:
            wait = min(2**attempt * 15, 120)
            logger.warning(f"Anthropic 429, backing off {wait}s (attempt {attempt + 1}/{retries})")
            await asyncio.sleep(wait)
            continue

        if resp.status_code != 200:
            logger.warning(f"Anthropic API {resp.status_code}: {resp.text[:200]}")
            return None

        try:
            data = resp.json()
            return data.get("content", [{}])[0].get("text", "").strip() or None
        except (IndexError, KeyError) as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return None

    return None
