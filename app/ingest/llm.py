"""Shared LLM call helper for ingest modules.

Centralises the httpx -> Gemini API pattern: budget tracking, retries,
429 backoff, JSON parsing.

Usage:
    result = await call_llm(prompt, max_tokens=2048)
    # result is parsed JSON (dict or list) or None on failure

    text = await call_llm_text(prompt, max_tokens=20)
    # text is raw string or None on failure

Budget and rate limiting are handled by acquire_budget("gemini") which
reads limits from the database. Budget is only decremented after the
HTTP request actually fires via record_call(). See app/ingest/budget.py.
"""

import asyncio
import json
import logging

import httpx

from app.ingest.budget import (
    ResourceExhaustedError,
    ResourceThrottledError,
    acquire_budget,
    record_call,
    record_success,
    record_throttle,
)
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

    if not await acquire_budget("gemini"):
        raise ResourceExhaustedError("gemini")

    url = _GEMINI_URL.format(model=settings.GEMINI_MODEL)

    for attempt in range(retries):
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

        # Request fired — count it regardless of response status
        await record_call("gemini")

        if resp.status_code == 429:
            await record_throttle("gemini")
            raise ResourceThrottledError("gemini")

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
            await record_success("gemini")
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

    if not await acquire_budget("gemini"):
        raise ResourceExhaustedError("gemini")

    url = _GEMINI_URL.format(model=settings.GEMINI_MODEL)

    for attempt in range(retries):
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

        # Request fired — count it regardless of response status
        await record_call("gemini")

        if resp.status_code == 429:
            await record_throttle("gemini")
            raise ResourceThrottledError("gemini")

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
            await record_success("gemini")
            return text or None
        except (IndexError, KeyError) as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return None

    return None
