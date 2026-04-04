"""Shared LLM call helper for ingest modules.

Centralises the httpx -> Gemini API pattern: rate limiting, retries,
429 backoff, JSON parsing.

Usage:
    result = await call_llm(prompt, max_tokens=2048)
    # result is parsed JSON (dict or list) or None on failure

    text = await call_llm_text(prompt, max_tokens=20)
    # text is raw string or None on failure

Note: function names kept as call_llm/call_llm_text for backwards

"""
import asyncio
import json
import logging

import httpx

from app.ingest.rate_limit import GEMINI_LIMITER
from app.settings import settings

logger = logging.getLogger(__name__)

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


async def call_llm(
    prompt: str,
    *,
    max_tokens: int = 2048,
    retries: int = 3,
    timeout: float = 60.0,
) -> dict | list | None:
    """Call Gemini and return parsed JSON, or None on failure."""
    if not settings.GEMINI_API_KEY:
        return None

    url = _GEMINI_URL.format(model=settings.GEMINI_MODEL)

    for attempt in range(retries):
        await GEMINI_LIMITER.acquire()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    url,
                    params={"key": settings.GEMINI_API_KEY},
                    headers={"content-type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "maxOutputTokens": max_tokens,
                            "responseMimeType": "application/json",
                            "thinkingConfig": {"thinkingBudget": 0},
                        },
                    },
                )
        except httpx.HTTPError as e:
            logger.warning(f"LLM HTTP error (attempt {attempt + 1}/{retries}): {e}")
            await asyncio.sleep(2**attempt * 5)
            continue

        if resp.status_code == 429:
            wait = min(2**attempt * 15, 120)
            logger.warning(f"Gemini 429, backing off {wait}s (attempt {attempt + 1}/{retries})")
            await asyncio.sleep(wait)
            continue

        if resp.status_code != 200:
            logger.warning(f"Gemini API {resp.status_code}: {resp.text[:200]}")
            return None

        try:
            data = resp.json()
            text_content = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )
            return json.loads(text_content)
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return None

    return None


async def call_llm_text(
    prompt: str,
    *,
    max_tokens: int = 512,
    retries: int = 3,
    timeout: float = 60.0,
) -> str | None:
    """Call Gemini and return raw text (not JSON), or None on failure."""
    if not settings.GEMINI_API_KEY:
        return None

    url = _GEMINI_URL.format(model=settings.GEMINI_MODEL)

    for attempt in range(retries):
        await GEMINI_LIMITER.acquire()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    url,
                    params={"key": settings.GEMINI_API_KEY},
                    headers={"content-type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "maxOutputTokens": max_tokens,
                            "thinkingConfig": {"thinkingBudget": 0},
                        },
                    },
                )
        except httpx.HTTPError as e:
            logger.warning(f"LLM HTTP error (attempt {attempt + 1}/{retries}): {e}")
            await asyncio.sleep(2**attempt * 5)
            continue

        if resp.status_code == 429:
            wait = min(2**attempt * 15, 120)
            logger.warning(f"Gemini 429, backing off {wait}s (attempt {attempt + 1}/{retries})")
            await asyncio.sleep(wait)
            continue

        if resp.status_code != 200:
            logger.warning(f"Gemini API {resp.status_code}: {resp.text[:200]}")
            return None

        try:
            data = resp.json()
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )
            return text or None
        except (IndexError, KeyError) as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return None

    return None
