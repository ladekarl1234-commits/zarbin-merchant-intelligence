"""AI gateway + observability.

Design rule: deterministic analytics remain the source of truth. The model may explain
or prioritize only numbers that are already present in structured evidence.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from . import copilot
from .config import ROOT

AI_EVENTS_PATH = Path(os.environ.get("ZARIN_AI_EVENTS_PATH", ROOT / "data" / "runtime" / "ai_events.jsonl"))
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _free_model_policy(requested: str | None) -> str:
    """Enforce the product rule: OpenRouter must use a free router/model only."""
    model = (requested or "openrouter/free").strip()
    if model == "openrouter/free" or model.endswith(":free"):
        return model
    return "openrouter/free"


OPENROUTER_MODEL = _free_model_policy(os.environ.get("OPENROUTER_MODEL"))
_LOCK = Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_event(event: dict[str, Any]) -> None:
    try:
        AI_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, AI_EVENTS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _safe_evidence(base: dict[str, Any]) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for e in base.get("evidence", []):
        safe.append({
            "metric_id": e.get("metric_id"),
            "name_fa": e.get("name_fa"),
            "definition_fa": e.get("definition_fa"),
            "formula": e.get("formula"),
            "n": e.get("n"),
            "period": e.get("period"),
            "caveats": e.get("caveats", []),
            "method_fa": e.get("method_fa"),
        })
    return safe


def _call_openrouter(system: str, question: str, context: dict[str, Any]) -> tuple[str, str]:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    payload = json.dumps({
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Question: {question}\nContext JSON:\n{json.dumps(context, ensure_ascii=False)}"},
        ],
        "temperature": 0.15,
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8630",
            "X-Title": "Zarbin Merchant Intelligence",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310 - fixed HTTPS endpoint
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenRouter HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"OpenRouter unavailable: {exc}") from exc
    text = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    if not text:
        raise RuntimeError("OpenRouter returned an empty answer")
    return text, body.get("model") or OPENROUTER_MODEL


def _openrouter_explain(question: str, base: dict[str, Any], merchant: str, period: tuple[str, str]) -> tuple[str, str]:
    context = {
        "merchant": merchant,
        "period": {"from": period[0], "to": period[1]},
        "deterministic_answer_fa": base.get("answer_fa", ""),
        "evidence": _safe_evidence(base),
    }
    system = (
        "You are the Persian explanation layer for a merchant analytics product. The JSON context is the only source of truth. "
        "Never invent a number, causal claim, metric, benchmark, customer fact, or recommendation not grounded in the context. "
        "Do not expose SQL or technical jargon unless asked. Answer in clear natural Persian for a non-technical Iranian merchant. "
        "If evidence is insufficient, say so plainly."
    )
    return _call_openrouter(system, question, context)


def answer(merchant: str, question: str, f: str, t: str) -> dict[str, Any]:
    started = time.perf_counter()
    base = copilot.answer(merchant, question, f, t)
    mode, model, fallback, error = "deterministic", "zarbin-rules", False, None
    answer_fa = base["answer_fa"]
    if os.environ.get("OPENROUTER_API_KEY"):
        try:
            answer_fa, model = _openrouter_explain(question, base, merchant, (f, t))
            mode = "openrouter"
        except RuntimeError as exc:
            fallback, error = True, str(exc)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    grounded = bool(base.get("evidence"))
    event = {
        "ts": _now(), "merchant": merchant, "intent": base.get("intent", "unknown"), "mode": mode,
        "model": model, "latency_ms": latency_ms, "success": True, "fallback": fallback,
        "grounded": grounded, "evidence_count": len(base.get("evidence", [])), "cost_usd": 0.0, "error": error,
    }
    _append_event(event)
    return {**base, "answer_fa": answer_fa, "ai": {"mode": mode, "model": model, "fallback": fallback,
            "grounded": grounded, "latency_ms": latency_ms, "cost_usd": 0.0, "error": error}}


def _read_events(limit: int = 500) -> list[dict[str, Any]]:
    if not AI_EVENTS_PATH.exists():
        return []
    try:
        lines = AI_EVENTS_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def stats() -> dict[str, Any]:
    events = _read_events()
    if not events:
        return {"requests": 0, "success_rate": None, "grounded_rate": None, "fallback_rate": None,
                "avg_latency_ms": None, "p95_latency_ms": None, "cost_usd": 0.0, "models": {}, "intents": {},
                "recent": [], "openrouter_configured": bool(os.environ.get("OPENROUTER_API_KEY")),
                "default_model": OPENROUTER_MODEL}
    latencies = sorted(float(e.get("latency_ms", 0)) for e in events)
    p95 = latencies[min(len(latencies) - 1, int(0.95 * (len(latencies) - 1)))]
    n = len(events)
    return {
        "requests": n,
        "success_rate": sum(bool(e.get("success")) for e in events) / n,
        "grounded_rate": sum(bool(e.get("grounded")) for e in events) / n,
        "fallback_rate": sum(bool(e.get("fallback")) for e in events) / n,
        "avg_latency_ms": sum(latencies) / n,
        "p95_latency_ms": p95,
        "cost_usd": sum(float(e.get("cost_usd", 0)) for e in events),
        "models": dict(Counter(str(e.get("model", "unknown")) for e in events)),
        "intents": dict(Counter(str(e.get("intent", "unknown")) for e in events)),
        "recent": list(reversed(events[-20:])),
        "openrouter_configured": bool(os.environ.get("OPENROUTER_API_KEY")),
        "default_model": OPENROUTER_MODEL,
    }


def admin_answer(question: str, ops: dict[str, Any]) -> dict[str, Any]:
    """Grounded operations copilot over already-computed control-plane telemetry."""
    started = time.perf_counter()
    ai = ops["ai"]
    api = ops.get("api", {})
    sources = ops["sources"]
    q = question.lower()
    if "fallback" in q or "فالبک" in q or "جایگزین" in q:
        rate = ai.get("fallback_rate")
        answer_fa = "هنوز درخواست AI ثبت نشده است." if rate is None else f"نرخ fallback فعلی {rate * 100:.1f}٪ است. اگر از هدف ۵٪ بالاتر رفته، ابتدا دسترسی OpenRouter و خطاهای درخواست‌های اخیر را بررسی کنید."
        intent = "ai_fallback"
    elif "api" in q or "ای‌پی‌آی" in q or "خطای سرویس" in q:
        p95 = api.get("p95_latency_ms")
        error = api.get("error_rate")
        answer_fa = "هنوز نمونه کافی از API ثبت نشده است." if p95 is None else f"P95 فعلی API حدود {p95:.0f} میلی‌ثانیه و نرخ خطای ۵۰۰ به بالا {(error or 0) * 100:.1f}٪ است."
        intent = "api_health"
    elif "کند" in q or "سرعت" in q or "تاخیر" in q or "latency" in q:
        p95 = ai.get("p95_latency_ms")
        answer_fa = "هنوز داده‌ای برای زمان پاسخ AI نداریم." if p95 is None else f"P95 زمان پاسخ AI حدود {p95:.0f} میلی‌ثانیه است. هدف اولیه زیر ۱۰۰۰ میلی‌ثانیه تعریف شده است."
        intent = "ai_latency"
    elif "هزینه" in q or "cost" in q:
        answer_fa = f"هزینه ثبت‌شده مدل در این نسخه ${ai.get('cost_usd', 0):.4f} است. policy فقط openrouter/free یا مدل‌های صریح :free را می‌پذیرد؛ هزینه زیرساخت جدا از هزینه مدل است."
        intent = "ai_cost"
    elif "منبع" in q or "گوگل" in q or "analytics" in q:
        missing = [s["label"] for s in sources if not s["configured"]]
        answer_fa = "همه منابع تعریف‌شده آماده‌اند." if not missing else "این منابع هنوز نیازمند تنظیم‌اند: " + "، ".join(missing)
        intent = "source_health"
    else:
        grounded = ai.get("grounded_rate")
        answer_fa = (
            f"مرکز کنترل {ops['platform']['merchants']} پذیرنده و {ops['platform']['sessions']:,} جلسه را پوشش می‌دهد. "
            + ("هنوز نمونه کافی برای سنجش کیفیت AI نداریم." if grounded is None else f"{grounded * 100:.1f}٪ پاسخ‌های ثبت‌شده حداقل یک شاهد قابل ردیابی داشته‌اند.")
        )
        intent = "ops_summary"

    mode, model, fallback, error = "deterministic", "zarbin-ops-rules", False, None
    if os.environ.get("OPENROUTER_API_KEY"):
        safe_context = {
            "deterministic_answer_fa": answer_fa,
            "api": api,
            "ai": {k: ai.get(k) for k in ("requests", "grounded_rate", "fallback_rate", "avg_latency_ms", "p95_latency_ms", "cost_usd", "models", "intents")},
            "sources": sources,
            "source_insights": ops.get("source_insights", []),
            "ga4": ops.get("ga4"),
            "slo": ops.get("slo", {}),
            "platform": ops.get("platform", {}),
        }
        system = (
            "You are the Persian operations copilot for an analytics platform. Use only the supplied telemetry and source insights. "
            "Never invent incidents, costs, causes, or numbers. Distinguish observation from recommendation. "
            "Answer briefly and clearly for a product/engineering manager."
        )
        try:
            answer_fa, model = _call_openrouter(system, question, safe_context)
            mode = "openrouter"
        except RuntimeError as exc:
            fallback, error = True, str(exc)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    _append_event({"ts": _now(), "merchant": "__admin__", "intent": intent, "mode": mode, "model": model,
                   "latency_ms": latency_ms, "success": True, "fallback": fallback, "grounded": True,
                   "evidence_count": 1, "cost_usd": 0.0, "error": error})
    return {"answer_fa": answer_fa, "intent": intent, "ai": {"mode": mode, "model": model,
            "fallback": fallback, "grounded": True, "latency_ms": latency_ms, "cost_usd": 0.0, "error": error}}
