"""Thin LLM abstraction: Anthropic, OpenAI-compatible APIs (OpenAI, Groq, Gemini) and a scripted fake.

Model names change often. Defaults below are examples - override with ``--model``
or the ``LLM_MODEL`` environment variable and check your provider's current model list.
"""

from __future__ import annotations

import os
import time
from typing import Protocol


class LLM(Protocol):
    def complete(self, system: str, messages: list[dict]) -> str: ...


def _with_backoff(fn, attempts: int = 4):
    """Retry transient API failures (rate limits, timeouts) with exponential backoff."""
    for i in range(attempts):
        try:
            return fn()
        except Exception:  # noqa: BLE001 - SDK-specific exceptions differ per provider
            if i == attempts - 1:
                raise
            time.sleep(2**i)


class AnthropicLLM:
    def __init__(self, model: str | None = None, max_tokens: int = 1024):
        import anthropic  # lazy import so tests/CI do not need the SDK

        self.model = model or os.getenv("LLM_MODEL") or "claude-sonnet-5-5"
        self.max_tokens = max_tokens
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    def complete(self, system: str, messages: list[dict]) -> str:
        resp = _with_backoff(
            lambda: self.client.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=system, messages=messages
            )
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


# provider -> (base_url, api-key env var, example default model)
OPENAI_COMPAT = {
    "openai": (None, "OPENAI_API_KEY", "gpt-4o-mini"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-2.0-flash"),
}


class OpenAICompatLLM:
    def __init__(self, provider: str, model: str | None = None, max_tokens: int = 1024):
        import openai  # lazy import

        base_url, key_env, default_model = OPENAI_COMPAT[provider]
        api_key = os.getenv(key_env)
        if not api_key:
            raise RuntimeError(f"Set {key_env} to use the '{provider}' provider.")
        self.model = model or os.getenv("LLM_MODEL") or default_model
        self.max_tokens = max_tokens
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def complete(self, system: str, messages: list[dict]) -> str:
        resp = _with_backoff(
            lambda: self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "system", "content": system}, *messages],
            )
        )
        return resp.choices[0].message.content or ""


class ScriptedLLM:
    """Returns pre-written responses in order. Used by tests and the benchmark ``--oracle`` self-check."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, system: str, messages: list[dict]) -> str:
        self.calls.append((system, [dict(m) for m in messages]))
        if not self.responses:
            raise RuntimeError("ScriptedLLM ran out of responses.")
        return self.responses.pop(0)


def get_llm(provider: str | None = None, model: str | None = None) -> LLM:
    provider = (provider or os.getenv("LLM_PROVIDER") or "anthropic").lower()
    if provider == "anthropic":
        return AnthropicLLM(model)
    if provider in OPENAI_COMPAT:
        return OpenAICompatLLM(provider, model)
    raise ValueError(f"Unknown provider '{provider}'. Choose from: anthropic, {', '.join(OPENAI_COMPAT)}.")
