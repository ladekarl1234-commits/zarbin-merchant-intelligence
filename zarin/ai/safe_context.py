"""Evidence-safe context layer — the only thing allowed to cross to an external model.

The model receives *derived, aggregate* facts: the deterministic Persian answer, and
each metric's name / definition / methodology / caveats. It NEVER receives raw payment
rows, card identifiers, session ids, executed SQL, query parameters, secrets, or any
other merchant's data. `build()` emits an allowlisted structure by construction, and
`assert_safe()` is a belt-and-braces scan that fails loudly if a banned field leaks in.
"""
from __future__ import annotations

# Substrings that must never appear as a key anywhere in an outbound payload.
_BANNED_KEY_SUBSTRINGS = (
    "sql", "param", "payer", "card", "session_key", "session_id", "settled",
    "secret", "credential", "password", "authorization", "api_key", "token",
)


def _safe_metric(ev: dict) -> dict:
    """Project one evidence payload down to model-safe fields only."""
    return {
        "name": ev.get("name_fa"),
        "definition": ev.get("definition_fa"),
        "methodology": ev.get("formula"),
        "grain": ev.get("grain"),
        "caveats": ev.get("caveats", []),
        "sample_size": ev.get("n"),
        "period": ev.get("period"),
    }


def build(*, question: str, merchant_scope: str, intent: str,
          deterministic_answer_fa: str, evidence: list[dict],
          confidence: str | None = None) -> dict:
    """Assemble the model-safe context for one grounded explanation request.

    `deterministic_answer_fa` already contains every number (computed by the engine,
    in Persian, aggregate). The model's job is only to rephrase/prioritize it.
    """
    payload = {
        "merchant_scope": merchant_scope,   # opaque label like "M156"; not PII
        "question": question,
        "intent": intent,
        "confidence": confidence,
        "computed_answer_fa": deterministic_answer_fa,
        "metrics": [_safe_metric(e) for e in (evidence or [])],
    }
    assert_safe(payload)
    return payload


def assert_safe(obj: object, _path: str = "") -> None:
    """Recursively verify no banned key appears. Raises ValueError on leak."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            for bad in _BANNED_KEY_SUBSTRINGS:
                if bad in kl:
                    raise ValueError(f"unsafe key {k!r} at {_path or '<root>'} would leak to the model")
            assert_safe(v, f"{_path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            assert_safe(v, f"{_path}[{i}]")
