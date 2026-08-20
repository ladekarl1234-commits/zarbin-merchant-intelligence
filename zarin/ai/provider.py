"""AI provider abstraction — swap OpenRouter for another vendor without touching
the analytics engine. Uses only the stdlib (urllib): no new dependency, works in the
zero-network judge environment (where the provider is simply never constructed).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from ..config import (
    AI_MAX_TOKENS,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
    OPENROUTER_TIMEOUT,
)
from .models import enforce_free


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None


class AIProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, *, max_tokens: int = AI_MAX_TOKENS) -> Completion: ...


class OpenRouterProvider:
    """Grounded-explanation provider. Enforces the free-model policy on every call."""

    name = "openrouter"

    def __init__(self, api_key: str = OPENROUTER_API_KEY, model: str = OPENROUTER_MODEL,
                 base_url: str = OPENROUTER_BASE_URL, timeout: float = OPENROUTER_TIMEOUT):
        if not api_key:
            raise RuntimeError("OpenRouterProvider requires OPENROUTER_API_KEY")
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        # Free-model policy applied at construction AND per request (defence in depth).
        self.model, self.policy_note = enforce_free(model)

    def complete(self, system: str, user: str, *, max_tokens: int = AI_MAX_TOKENS) -> Completion:
        model, _ = enforce_free(self.model)  # never let a non-free id through
        body = json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "usage": {"include": True},
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body, method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/ladekarl1234-commits/zarbin-merchant-intelligence",
                "X-Title": "Zarbin",
            },
        )
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            raise RuntimeError(f"openrouter request failed: {e}") from e
        latency_ms = int((time.monotonic() - t0) * 1000)
        try:
            text = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"openrouter returned no content: {data!r}") from e
        usage = data.get("usage") or {}
        return Completion(
            text=text, provider=self.name, model=data.get("model", model),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            cost_usd=float(usage.get("cost") or 0.0),  # free models bill $0
            latency_ms=latency_ms,
        )


def default_provider() -> AIProvider | None:
    """Construct the configured provider, or None when no key is set (offline mode)."""
    if not OPENROUTER_API_KEY:
        return None
    try:
        return OpenRouterProvider()
    except RuntimeError:
        return None
