"""Minimal LLM client for the Refactoring Advisory Agent (uses only ``requests``).

Everything is configured with environment variables, so no key ever lives in the repo:

    LLM_PROVIDER   "anthropic" or "openai"  (openai = any OpenAI-compatible endpoint,
                   including many hosted providers and local servers)
    LLM_MODEL      model name from your provider's docs (required, no default on purpose
                   so a stale model name never ships)
    LLM_API_KEY    your key (optional only for a local openai-compatible server)
    LLM_BASE_URL   optional override, e.g. a local server or a provider's compatible endpoint

PowerShell example:
    $env:LLM_PROVIDER = "anthropic"
    $env:LLM_MODEL    = "<model name from the provider docs>"
    $env:LLM_API_KEY  = "<your key>"

If the settings are missing, ``is_configured()`` is False and callers keep their
template advice. Errors never include response bodies or the key.
"""
from __future__ import annotations

import os

import requests

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_ANTHROPIC_URL = "https://api.anthropic.com"
DEFAULT_OPENAI_URL = "https://api.openai.com/v1"


class LLMError(Exception):
    """A failed LLM call. The message is safe to show (status or error class only)."""


def _settings() -> tuple[str, str, str, str]:
    return (
        os.environ.get("LLM_PROVIDER", "").strip().lower(),
        os.environ.get("LLM_MODEL", "").strip(),
        os.environ.get("LLM_API_KEY", "").strip(),
        os.environ.get("LLM_BASE_URL", "").strip(),
    )


def is_configured() -> bool:
    provider, model, key, base_url = _settings()
    if provider not in ("anthropic", "openai") or not model:
        return False
    return bool(key) or (provider == "openai" and bool(base_url))


def identity() -> str:
    """Provider and model, used to keep cached answers from mixing across models."""
    provider, model, _, _ = _settings()
    return f"{provider}:{model}"


def complete(system: str, user: str, max_tokens: int = 400, timeout: tuple[int, int] = (5, 45)) -> str:
    provider, model, key, base_url = _settings()
    try:
        if provider == "anthropic":
            url = (base_url or DEFAULT_ANTHROPIC_URL).rstrip("/") + "/v1/messages"
            headers = {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION,
                       "content-type": "application/json"}
            body = {"model": model, "max_tokens": max_tokens, "system": system,
                    "messages": [{"role": "user", "content": user}]}
        else:
            url = (base_url or DEFAULT_OPENAI_URL).rstrip("/") + "/chat/completions"
            headers = {"content-type": "application/json"}
            if key:
                headers["authorization"] = f"Bearer {key}"
            body = {"model": model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}]}
        response = requests.post(url, headers=headers, json=body, timeout=timeout)
    except requests.RequestException as error:
        raise LLMError(type(error).__name__) from None

    if response.status_code != 200:
        raise LLMError(f"HTTP {response.status_code}")
    try:
        data = response.json()
        if provider == "anthropic":
            return "".join(block.get("text", "") for block in data["content"] if block.get("type") == "text")
        return data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise LLMError("unexpected response format") from None
