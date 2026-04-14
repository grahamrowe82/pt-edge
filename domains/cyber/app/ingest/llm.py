"""Gemini LLM helper for CyberEdge — same pattern as core app/ingest/llm.py.

Usage:
    result = await call_llm(prompt)        # parsed JSON or None
    text = await call_llm_text(prompt)      # raw text or None
"""

import asyncio
import json
import logging

import httpx

from domains.cyber.app.settings import settings

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
            logger.warning("Gemini rate limited — backing off")
            await asyncio.sleep(2**attempt * 10)
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
