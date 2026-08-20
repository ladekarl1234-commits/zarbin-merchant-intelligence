"""AI telemetry — every AI-supported answer is recorded and aggregated for AI-Ops.

Nothing here is fabricated: an aggregate is only shown if events exist to back it.
The event is the AI response contract minus the answer text (we keep metadata, not
content) plus an opaque merchant label for cost-per-merchant.
"""
from __future__ import annotations

from collections import Counter

from ..config import TELEMETRY_DIR
from ..store import EventLog

_events = EventLog(TELEMETRY_DIR / "ai_events.jsonl")
_feedback = EventLog(TELEMETRY_DIR / "ai_feedback.jsonl")


def record(*, intent: str, source: str, grounded: bool, fallback: bool, success: bool,
           provider: str | None, model: str | None, latency_ms: int | None,
           prompt_tokens: int | None, completion_tokens: int | None, total_tokens: int | None,
           cost_usd: float | None, evidence_count: int, quality_flags: list[str],
           merchant_scope: str, surface: str = "merchant") -> None:
    _events.add({
        "surface": surface, "intent": intent, "source": source, "grounded": grounded,
        "fallback": fallback, "success": success, "provider": provider, "model": model,
        "latency_ms": latency_ms, "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens, "total_tokens": total_tokens,
        "cost_usd": cost_usd, "evidence_count": evidence_count,
        "quality_flags": quality_flags, "merchant_scope": merchant_scope,
    })


def record_feedback(*, merchant_scope: str, intent: str, useful: bool, surface: str = "merchant") -> None:
    _feedback.add({"merchant_scope": merchant_scope, "intent": intent, "useful": useful, "surface": surface})


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    i = min(len(s) - 1, round(q * (len(s) - 1)))
    return round(s[i], 1)


def summary() -> dict:
    ev = _events.recent()
    total = len(ev)
    fb = _feedback.recent()
    if not total:
        return {"total": 0, "has_data": False,
                "note_fa": "هنوز درخواستی برای دستیار هوشمند ثبت نشده است."}

    llm = [e for e in ev if e.get("source") == "llm"]
    lat = [e["latency_ms"] for e in llm if e.get("latency_ms") is not None]
    fallbacks = sum(1 for e in ev if e.get("fallback"))
    grounded = sum(1 for e in ev if e.get("grounded"))
    zero_ev = sum(1 for e in ev if not e.get("evidence_count"))
    with_ev = total - zero_ev
    halluc = sum(1 for e in ev if "hallucination_risk" in (e.get("quality_flags") or []))
    cost = round(sum(e.get("cost_usd") or 0.0 for e in ev), 6)
    tokens = sum(e.get("total_tokens") or 0 for e in ev)
    thumbs_up = sum(1 for e in fb if e.get("useful"))

    return {
        "total": total, "has_data": True,
        "llm_requests": len(llm),
        "deterministic_requests": total - len(llm),
        "success": sum(1 for e in ev if e.get("success")),
        "failed": sum(1 for e in ev if not e.get("success")),
        "fallback": fallbacks,
        "fallback_rate": round(fallbacks / total, 4),
        "grounded_rate": round(grounded / total, 4),
        "evidence_coverage": round(with_ev / total, 4),
        "zero_evidence": zero_ev,
        "hallucination_risk": halluc,
        "latency_ms": {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95), "p99": _pct(lat, 0.99)},
        "tokens_total": tokens,
        "cost_usd_total": cost,
        "cost_per_request": round(cost / len(llm), 6) if llm else 0.0,
        "models": [{"model": m, "count": c} for m, c in Counter(e.get("model") for e in llm if e.get("model")).most_common()],
        "providers": [{"provider": p, "count": c} for p, c in Counter(e.get("provider") for e in llm if e.get("provider")).most_common()],
        "intents": [{"intent": i, "count": c} for i, c in Counter(e.get("intent") for e in ev).most_common()],
        "feedback": {"total": len(fb), "useful": thumbs_up, "not_useful": len(fb) - thumbs_up},
        "recent": [{k: e.get(k) for k in ("ts", "surface", "intent", "source", "fallback", "grounded",
                                          "model", "latency_ms", "cost_usd", "evidence_count")}
                   for e in ev[-15:]][::-1],
    }


def reset() -> None:  # testing hook
    _events.clear()
    _feedback.clear()
