"""Free-model policy — the guard that keeps AI cost at zero.

OpenRouter convention: a model whose id ends with ':free' is billed at $0. That
suffix is the ONLY thing we treat as proof of free. `openrouter/auto` is rejected
because OpenRouter bills auto-routing at the selected model's standard rate
(verified against OpenRouter model-routing docs, 2026-08).

Policy: allowed iff id endswith ':free' OR id in FREE_ALLOWLIST. A configured
non-free model is never silently used — `enforce_free()` normalizes it back to the
default free model and records why, so a typo can never spend money.
"""
from __future__ import annotations

# Known free model ids that do not carry the ':free' suffix but are zero-price.
# Kept empty by default: the ':free' suffix already covers OpenRouter's free tier,
# and an over-broad allowlist is exactly how a paid model slips through.
FREE_ALLOWLIST: frozenset[str] = frozenset()

# Never allowed, even though they look "meta": these route to (and bill for) paid models.
BANNED = frozenset({"openrouter/auto", "openrouter/free", "auto"})

DEFAULT_FREE_MODEL = "deepseek/deepseek-chat-v3-0324:free"


def is_free(model: str) -> bool:
    """True iff `model` is provably zero-price under the policy above."""
    m = (model or "").strip()
    if not m or m in BANNED:
        return False
    return m.endswith(":free") or m in FREE_ALLOWLIST


def enforce_free(model: str) -> tuple[str, str | None]:
    """Return (model_to_use, rejection_reason).

    rejection_reason is None when the requested model was already free; otherwise
    the model is replaced by DEFAULT_FREE_MODEL and the reason explains the swap.
    """
    if is_free(model):
        return model, None
    reason = (
        f"requested model {model!r} is not on the free allowlist "
        f"(must end with ':free'); forced to {DEFAULT_FREE_MODEL}"
    )
    return DEFAULT_FREE_MODEL, reason
