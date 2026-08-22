"""Intent-routing evaluation on the held-out set, with the pre-retrieval router as baseline.

Run:  uv run python -m zarin.ai.eval.retrieval

Scores the copilot's understanding layer only — routing, not phrasing — because that is
what decides whether the merchant is answered about the thing they asked. Numbers, once
routed, are the deterministic engine's and are covered by the metric tests.

Five outcomes, kept separate on purpose (one blended accuracy would hide the one that
matters):

  exact        predicted intent == gold
  misrouted    gold is answerable, a DIFFERENT answerable intent was chosen
               → the merchant gets a confident answer to another question. The worst
                 failure mode for a business tool, and the one the old router produced
                 silently on every unmatched question.
  missed       gold is answerable, the router refused or asked back
               → recall loss. Annoying, not dangerous.
  unsafe       gold is out_of_scope, an answerable intent was chosen
               → the router answered something it cannot know. Safety failure.
  safe_refusal gold is out_of_scope, the router declined or asked back
               → correct behaviour whether it said `out_of_scope` or `clarify`.

BASELINE. `legacy_route` is a faithful copy of the router as it stood at commit 76e3497,
before zarin/nlu.py existed: eight ordered regexes, an out-of-scope family list, a
vocabulary gate, and a terminal `fallback` that answered a generic business summary. It
is reproduced here rather than described so the before/after is measured on identical
inputs by identical code paths.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter

from ... import copilot, nlu
from .retrieval_cases import RETRIEVAL_CASES
from .retrieval_holdout_cases import HOLDOUT_CASES

# --- the pre-retrieval router, verbatim ------------------------------------------------
_LEGACY_OUT_OF_SCOPE = (
    r"(فردا|هفته آینده|ماه آینده|سال آینده|پیش.?بینی|پیش.?بین|چقدر می.?شود|خواهد شد)",
    r"(نرخ ارز|دلار|یورو|طلا|بورس|سهام|بیت.?کوین|ارز دیجیتال)",
    r"(شماره کارت|شماره تماس|شماره موبایل|کد ملی|ایمیل|آدرس|نام مشتری|اسم مشتری)",
    r"^\s*(سلام|درود|خداحافظ|ممنون|مرسی|تشکر|چطوری|خوبی)\W*$",
)
_LEGACY_BUSINESS = (r"(فروش|درآمد|پرداخت|تراکنش|مشتری|درگاه|بانک|تبدیل|کارمزد|سبد|خرید|جلسه"
                    r"|تایید|برگشت|قیف|همتا|رقیب|مشابه)")
_LEGACY_RULES = (
    ("changes", r"(چرا|علت|دلیل).*(کم|افت|پایین|نزول|خراب)|افت.*(فروش|درآمد)"),
    ("hours", r"(کی|چه ساعت|چه زمان|ساعت).*(خرید|فروش|پرداخت)"),
    ("recovery", r"(?i)(تلاش مجدد|بازیابی|نجات|ریکاوری|retry)"),
    ("friction", (r"(پرداخت|درگاه|تراکنش).*(شکست|خطا|ناموفق|رد شد)"
                  r"|(شکست|خطا|ناموفق).*(بیشتر|بدتر|زیاد|پرداخت|درگاه|بانک|تراکنش)"
                  r"|چرا.*(شکست|خطا|ناموفق)|وضعیت (شکست|خطا)")),
    ("peers", r"(مقایسه|همتا|رقبا|مشابه|جایگاه|رتبه)"),
    ("repeat", r"مشتری.*(برگشت|تکرار|وفادار)|(تکراری|بازگشت).*(مشتری)"),
    ("psp", r"(?i)(درگاه|psp|گیت‌?وی|روتینگ|مسیردهی)"),
    ("priorities", (r"(چه کار|چیکار|تمرکز|اولویت|این هفته|پیشنهاد|توصیه|فرصت|مهم‌ترین"
                    r"|بالا ببرم|بهتر کنم|افزایش|رشد بدم|بیشتر کنم)")),
)


def legacy_route(question: str) -> str:
    ql = question.strip()
    for pattern in _LEGACY_OUT_OF_SCOPE:
        if re.search(pattern, ql):
            return "out_of_scope"
    for intent, pattern in _LEGACY_RULES:
        if re.search(pattern, ql):
            return intent
    if not re.search(_LEGACY_BUSINESS, ql):
        return "out_of_scope"
    return "fallback"


# The live router. Not a copy: copilot._plan calls this same function, so the evaluation
# cannot drift away from what the product actually does.
current_route = copilot.route_intent


ANSWERABLE = frozenset(nlu.BANK)
REFUSALS = frozenset({"out_of_scope", "clarify"})
# `fallback` is the legacy router's terminal branch: it answered a generic business
# summary. It is counted as an ANSWER, not a refusal — that is the whole point of the
# comparison. A merchant who asked about unverified payments and got last quarter's GMV
# was not refused; they were misrouted.


def classify(gold: str, pred: str) -> str:
    if pred == gold:
        return "exact"
    if gold == "out_of_scope":
        return "safe_refusal" if pred in REFUSALS else "unsafe"
    if pred in REFUSALS:
        return "missed"
    return "misrouted"


def score(router, cases=RETRIEVAL_CASES) -> dict:
    rows = []
    for c in cases:
        pred = router(c.q)
        rows.append({"q": c.q, "gold": c.intent, "pred": pred, "family": c.family,
                     "outcome": classify(c.intent, pred)})
    n = len(rows)
    counts = Counter(r["outcome"] for r in rows)
    in_scope = [r for r in rows if r["gold"] != "out_of_scope"]
    oos = [r for r in rows if r["gold"] == "out_of_scope"]
    by_family = {}
    for fam in sorted({r["family"] for r in rows}):
        fr = [r for r in rows if r["family"] == fam]
        by_family[fam] = {"n": len(fr),
                          "exact": round(sum(r["outcome"] == "exact" for r in fr) / len(fr), 4)}
    return {
        "n": n,
        "exact_accuracy": round(counts["exact"] / n, 4),
        "answerable": {
            "n": len(in_scope),
            "exact": round(sum(r["outcome"] == "exact" for r in in_scope) / len(in_scope), 4),
            "misrouted": round(counts["misrouted"] / len(in_scope), 4),
            "missed": round(counts["missed"] / len(in_scope), 4),
        },
        "out_of_scope": {
            "n": len(oos),
            "safe": round((counts["exact"] + counts["safe_refusal"]
                           - sum(r["outcome"] == "exact" for r in in_scope)) / len(oos), 4)
            if oos else None,
            "unsafe": round(counts["unsafe"] / len(oos), 4) if oos else None,
        },
        "outcomes": dict(counts),
        "by_family": by_family,
        "rows": rows,
    }


def compare(cases=RETRIEVAL_CASES) -> dict:
    before, after = score(legacy_route, cases), score(current_route, cases)
    return {"before": before, "after": after,
            "delta": {"exact_accuracy": round(after["exact_accuracy"] - before["exact_accuracy"], 4),
                      "misrouted": round(after["answerable"]["misrouted"] - before["answerable"]["misrouted"], 4),
                      "unsafe": round((after["out_of_scope"]["unsafe"] or 0)
                                      - (before["out_of_scope"]["unsafe"] or 0), 4)}}


def _fmt(name: str, s: dict) -> str:
    a, o = s["answerable"], s["out_of_scope"]
    return (f"{name:8s} exact {s['exact_accuracy']:.3f}  |  answerable n={a['n']}: "
            f"exact {a['exact']:.3f} misrouted {a['misrouted']:.3f} missed {a['missed']:.3f}  |  "
            f"out-of-scope n={o['n']}: unsafe {o['unsafe']:.3f}")


# Two sets, reported separately and never merged. `dev` was read while building the router,
# so its score is a floor and a regression guard. `holdout` was written afterwards, against a
# frozen router, and nothing in the code has been changed in response to it — that is the
# number to quote. Averaging them would launder the development score into the honest one.
SETS = {"dev": RETRIEVAL_CASES, "holdout": HOLDOUT_CASES}
_LABEL = {"dev": "DEV SET (read while building the router — a floor, not the headline)",
          "holdout": "HOLDOUT (written after the router was frozen — the honest number)"}


def main() -> None:
    out = {}
    for name, cases in SETS.items():
        r = compare(cases)
        out[name] = r
        print(f"\n=== {_LABEL[name]} — {r['after']['n']} questions, "
              f"{len(ANSWERABLE)} answerable intents")
        print(_fmt("BEFORE", r["before"]))
        print(_fmt("AFTER", r["after"]))
        print(f"delta    exact {r['delta']['exact_accuracy']:+.3f}  "
              f"misrouted {r['delta']['misrouted']:+.3f}  unsafe {r['delta']['unsafe']:+.3f}")
        print("by family (exact, before -> after):")
        for fam, v in r["after"]["by_family"].items():
            print(f"  {fam:12s} n={v['n']:<4d} {r['before']['by_family'][fam]['exact']:.3f}"
                  f" -> {v['exact']:.3f}")
        if "-v" in sys.argv:
            for row in r["after"]["rows"]:
                if row["outcome"] != "exact":
                    print(f"    {row['outcome']:12s} gold={row['gold']:16s} "
                          f"pred={row['pred']:16s} {row['q']}")
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
