"""LLM adapter with Mistral-first routing and OpenAI-compatible fallback.

Routing strategy:
    1. Mistral AI (if MISTRAL_API_KEY is set) — primary model
    2. Generic OpenAI-compatible endpoint (if LLM_API_KEY is set) — fallback
    3. Template-based generation — no-LLM fallback

Mistral uses its own OpenAI-compatible endpoint at https://api.mistral.ai/v1.
The same chat completions format works for both providers.

Environment variables:
    MISTRAL_API_KEY: Mistral AI key (primary provider)
    LLM_BASE_URL:   Fallback base URL (default: https://api.openai.com/v1)
    LLM_API_KEY:    Fallback API key
    LLM_MODEL:      Fallback model name (default: gpt-4o-mini)
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ── Provider configuration ───────────────────────────────────

_MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
_MISTRAL_BASE_URL = "https://api.mistral.ai/v1"
_MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

_LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
_LLM_API_KEY = os.getenv("LLM_API_KEY", "")
_LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")


def _resolve_provider() -> tuple[str, str, str, str]:
    """Resolve which LLM provider to use.

    Returns (provider_name, base_url, api_key, model).
    """
    if _MISTRAL_API_KEY:
        return "mistral", _MISTRAL_BASE_URL, _MISTRAL_API_KEY, _MISTRAL_MODEL
    if _LLM_API_KEY:
        return "openai-compatible", _LLM_BASE_URL, _LLM_API_KEY, _LLM_MODEL
    return "none", "", "", ""


def is_llm_available() -> bool:
    """Check if any LLM API key is configured."""
    return bool(_MISTRAL_API_KEY) or bool(_LLM_API_KEY)


async def llm_chat(
    system_prompt: str,
    user_message: str,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str | None:
    """Send a chat completion request to the resolved LLM provider.

    Routing: Mistral (primary) → generic OpenAI-compatible (fallback) → None.
    Returns the assistant's response text, or None on failure.
    """
    provider, base_url, api_key, model = _resolve_provider()

    if provider == "none":
        return None

    logger.debug("LLM request → provider=%s model=%s", provider, model)

    import httpx

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
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
            content = data["choices"][0]["message"]["content"]
            logger.debug("LLM response received: provider=%s, tokens=%s",
                         provider, data.get("usage", {}).get("total_tokens", "?"))
            return content
    except Exception:
        logger.exception("LLM API call failed (provider=%s, model=%s)", provider, model)

        # If Mistral failed, try fallback to generic LLM
        if provider == "mistral" and _LLM_API_KEY:
            logger.info("Falling back from Mistral to generic LLM provider")
            return await _fallback_llm_chat(system_prompt, user_message, temperature, max_tokens)

        return None


async def _fallback_llm_chat(
    system_prompt: str,
    user_message: str,
    temperature: float,
    max_tokens: int,
) -> str | None:
    """Fallback to generic OpenAI-compatible LLM when Mistral fails."""
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
            logger.debug("Fallback LLM response received: model=%s", _LLM_MODEL)
            return data["choices"][0]["message"]["content"]
    except Exception:
        logger.exception("Fallback LLM API call also failed")
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
    provider, base_url, _, model = _resolve_provider()
    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "available": is_llm_available(),
        "mistral_configured": bool(_MISTRAL_API_KEY),
        "fallback_configured": bool(_LLM_API_KEY),
    }
