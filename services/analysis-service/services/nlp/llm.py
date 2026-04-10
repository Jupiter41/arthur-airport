"""LLM adapter with OpenAI-compatible API support and template fallback.

Supports any OpenAI-compatible endpoint (OpenAI, Groq, Together, Ollama, etc.)
via environment variables. Falls back to template-based generation when no
LLM is configured.

Environment variables:
    LLM_BASE_URL:  Base URL (default: https://api.openai.com/v1)
    LLM_API_KEY:   API key (required for LLM mode)
    LLM_MODEL:     Model name (default: gpt-4o-mini)
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
_LLM_API_KEY = os.getenv("LLM_API_KEY", "")
_LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")


def is_llm_available() -> bool:
    """Check if an LLM API key is configured."""
    return bool(_LLM_API_KEY)


async def llm_chat(
    system_prompt: str,
    user_message: str,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str | None:
    """Send a chat completion request to the configured LLM.

    Returns the assistant's response text, or None on failure.
    """
    if not is_llm_available():
        return None

    import httpx

    url = f"{_LLM_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {_LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": _LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception:
        logger.exception("LLM API call failed")
        return None


async def llm_chat_json(
    system_prompt: str,
    user_message: str,
    temperature: float = 0.3,
    max_tokens: int = 512,
) -> dict[str, Any] | None:
    """Send a chat request and parse the response as JSON.

    Returns parsed dict, or None on failure.
    """
    import json

    # Add JSON instruction to system prompt
    full_system = system_prompt + "\n\nRespond ONLY with valid JSON. No markdown, no explanation."

    text = await llm_chat(full_system, user_message, temperature, max_tokens)
    if text is None:
        return None

    # Strip potential markdown code fencing
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("LLM response was not valid JSON: %s", text[:200])
        return None


def get_config() -> dict[str, str]:
    """Return current LLM configuration for API consumers."""
    return {
        "base_url": _LLM_BASE_URL,
        "model": _LLM_MODEL,
        "available": is_llm_available(),
    }
