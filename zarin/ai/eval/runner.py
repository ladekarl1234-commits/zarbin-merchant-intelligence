"""Run the Copilot eval cases and produce per-dimension quality indicators."""
from __future__ import annotations

from ... import copilot
from ...db import q1
from . import retrieval
from .cases import CASES, Case


def _default_merchant_and_range() -> tuple[str, str, str]:
    # merchant_key breaks GMV ties. The top GMV is not tied today, so this changes nothing now —
    # but this query chooses which merchant the whole eval scores against, and an eval score that
    # rests on an arbitrary tie-break is not a measurement.
    m = q1("SELECT merchant_key FROM merchant_stats "
           "ORDER BY gmv DESC NULLS LAST, merchant_key LIMIT 1")["merchant_key"]
    r = q1("SELECT min(d) AS f, max(d) AS t FROM sessions")
    return m, str(r["f"]), str(r["t"])


def _run_case(c: Case, merchant: str, f: str, t: str) -> dict:
    pf, pt = c.period or (f, t)
    # deterministic-only: eval must be reproducible with zero keys / zero network
    resp = copilot.answer(merchant, c.question, pf, pt, use_llm=False)
    answer = resp["answer_fa"]
    # A real decline names its own limit. Without this the "refusal" cases passed while the
    # copilot happily answered a different question (ZB-040).
    declines = any(s in answer for s in ("خارج از", "متوجه نشدم", "کافی نیست", "وجود ندارد",
                                         "قابل محاسبه نیست", "کوتاه است"))
    checks = {
        "intent_ok": resp["intent"] == c.expect_intent,
        "grounding_ok": len(resp.get("evidence") or []) >= c.min_evidence,
        "no_forbidden": all(s not in answer for s in c.forbid_substrings),
        "confidence_ok": (c.expect_confidence is None) or (resp.get("confidence") == c.expect_confidence),
        "declines_ok": (not c.expect_declines) or declines,
    }
    return {"id": c.id, "dimension": c.dimension, "intent": resp["intent"],
            "expected_intent": c.expect_intent, "confidence": resp.get("confidence"),
            "evidence_count": len(resp.get("evidence") or []), "checks": checks,
            "passed": all(checks.values())}


def run_eval(merchant: str | None = None) -> dict:
    if merchant:
        r = q1("SELECT min(d) AS f, max(d) AS t FROM sessions")
        f, t = str(r["f"]), str(r["t"])
    else:
        merchant, f, t = _default_merchant_and_range()

    results = [_run_case(c, merchant, f, t) for c in CASES]
    n = len(results)
    refusal = [r for c, r in zip(CASES, results) if c.is_refusal]

    def rate(pred) -> float:
        return round(sum(1 for r in results if pred(r)) / n, 4) if n else 0.0

    indicators = {
        # kept as SEPARATE dimensions on purpose — never one meaningless score
        "deterministic_correctness": rate(lambda r: r["checks"]["intent_ok"]),
        "grounding_quality": rate(lambda r: r["checks"]["grounding_ok"]),
        "refusal_safety": round(
            sum(1 for r in refusal if all(r["checks"].values())) / len(refusal), 4
        ) if refusal else None,
        "language_quality": None,      # requires human / LLM-judge — not auto-scored (honest)
        "business_usefulness": None,   # requires human — not auto-scored (honest)
    }
    # Routing quality on the 120-question held-out set, alongside the pre-retrieval router
    # as a baseline. Kept in the same payload because "did the copilot answer the question
    # that was asked" is the first thing AI-Ops has to be able to see; the per-case checks
    # above only ever look at questions the product already knew how to route.
    routing = retrieval.compare()
    indicators["routing_accuracy"] = routing["after"]["exact_accuracy"]
    indicators["routing_misroute_rate"] = routing["after"]["answerable"]["misrouted"]
    indicators["routing_unsafe_rate"] = routing["after"]["out_of_scope"]["unsafe"]

    return {
        "merchant": merchant, "period": {"from": f, "to": t},
        "total": n, "passed": sum(1 for r in results if r["passed"]),
        "indicators": indicators, "cases": results,
        "routing": {
            "n": routing["after"]["n"],
            "before": {k: routing["before"][k] for k in ("exact_accuracy", "answerable", "out_of_scope", "by_family")},
            "after": {k: routing["after"][k] for k in ("exact_accuracy", "answerable", "out_of_scope", "by_family")},
            "delta": routing["delta"],
            "note_fa": "مجموعه ارزیابی مسیریابی، مستقل از بانک نمونه‌های موتور و بدون دیدن کد نوشته شده است.",
        },
        "note_fa": "ارزیابی قطعی و آفلاین است. کیفیت زبانی و سودمندی کسب‌وکاری با قضاوت انسانی سنجیده می‌شوند و اینجا نمره خودکار نمی‌گیرند.",
    }
