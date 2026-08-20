# ADR-0003 — OpenRouter provider abstraction + free-model policy

Status: Accepted · Date: 2026-08

## Context
The copilot may use an external model via OpenRouter. Requirement: **free models only**, never
accidentally spend money, and keep the provider swappable without touching the analytics engine.

## Decision
- **Provider abstraction** (`ai/provider.py`): an `AIProvider` protocol; `OpenRouterProvider`
  implements it with the **stdlib only** (`urllib`) — no new dependency, and it is simply never
  constructed in the zero-key judge environment. Another vendor = another `AIProvider`.
- **Free-model policy** (`ai/models.py`): a model is allowed **iff its id ends with `:free`**
  (OpenRouter's zero-price convention) or is in an explicit allowlist. `enforce_free()` runs at
  construction **and** on every request; a non-free id is replaced by the default free model and
  the reason recorded. The default (`deepseek/deepseek-chat-v3-0324:free`) is free.
- **`openrouter/auto` is BANNED.** Per OpenRouter's model-routing docs (verified 2026-08),
  auto-routing "pays the standard rate for whichever model is selected" — it is not free-safe.
- Endpoint `https://openrouter.ai/api/v1/chat/completions`; headers `Authorization: Bearer …`,
  `HTTP-Referer`, `X-Title`. Cost/tokens read from the response `usage` (free = $0).

## Consequences
- A typo in `OPENROUTER_MODEL` can never bill: it is forced to a `:free` model.
- Cost tracking is real (from provider metadata) and aggregated in Control Center → AI-Ops.
- Adding OpenAI/Anthropic/etc. later is one file; the engine is untouched.

## Rejected
- Trusting `openrouter/auto` / `openrouter/free` as "free" — they route to (and bill for) paid models.
- A broad allowlist of model ids — over-broad allowlists are exactly how a paid model slips through;
  the `:free` suffix is the conservative, verifiable rule.
